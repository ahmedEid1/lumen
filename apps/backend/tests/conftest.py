"""Shared test fixtures.

Tests run against a real Postgres + Redis to avoid mock/prod drift.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Ensure test env is set before app modules read config.
os.environ.setdefault("ENV", "test")
os.environ.setdefault("JWT_SECRET", "test-secret-please-change")
os.environ.setdefault("SECRET_KEY", "test-secret-please-change")

from app.core.config import get_settings  # noqa: E402
from app.db import base as db_base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import *  # noqa: E402, F403  ensure mappers registered
from app.core.security import hash_password  # noqa: E402
from app.models.user import Role, User  # noqa: E402


@pytest.fixture(scope="session")
def event_loop():  # type: ignore[override]
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def _engine():
    settings = get_settings()
    base_url = settings.database_url
    # Switch to a transient DB name to isolate test runs.
    test_db = f"lumen_test_{uuid.uuid4().hex[:8]}"
    admin_url = base_url.rsplit("/", 1)[0] + "/postgres"
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{test_db}"'))
    await admin_engine.dispose()

    test_url = base_url.rsplit("/", 1)[0] + f"/{test_db}"
    db_base._engine = None  # force re-init
    db_base._sessionmaker = None
    os.environ["DATABASE_URL"] = test_url
    get_settings.cache_clear()  # type: ignore[attr-defined]

    engine = create_async_engine(test_url, future=True)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
        await conn.run_sync(db_base.Base.metadata.create_all)

    db_base._engine = engine
    db_base._sessionmaker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    try:
        yield engine
    finally:
        await engine.dispose()
        admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin_engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)'))
        await admin_engine.dispose()


@pytest_asyncio.fixture
async def db_session(_engine) -> AsyncIterator[AsyncSession]:
    async with db_base.get_sessionmaker()() as session:
        # Clean tables between tests (fast for our small set).
        await session.execute(text(
            "TRUNCATE assets, audit_events, notifications, chat_messages, reviews, lesson_progress, "
            "enrollments, lessons, modules, course_tags, courses, tags, subjects, auth_refresh_tokens, "
            "users RESTART IDENTITY CASCADE"
        ))
        await session.commit()
        yield session


@pytest_asyncio.fixture
async def app(_engine):
    app = create_app()

    async def _override_db() -> AsyncIterator[AsyncSession]:
        async with db_base.get_sessionmaker()() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_db
    return app


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Give every test a fresh in-memory limiter so buckets don't leak across tests."""
    from app.core import ratelimit as ratelimit_mod

    ratelimit_mod.reset_for_tests()
    yield


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest_asyncio.fixture
async def make_user(db_session: AsyncSession):
    async def _make(
        *,
        email: str | None = None,
        password: str = "Password!1234",
        role: Role = Role.student,
        full_name: str = "Test User",
    ) -> User:
        user = User(
            email=email or f"u-{uuid.uuid4().hex[:8]}@lumen.test",
            password_hash=hash_password(password),
            full_name=full_name,
            role=role,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        return user

    return _make


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient, make_user):
    async def _login(*, role: Role = Role.student) -> dict[str, str]:
        email = f"login-{uuid.uuid4().hex[:8]}@lumen.test"
        password = "Password!1234"
        await make_user(email=email, password=password, role=role)
        r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _login
