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
#
# Unconditional assignment, not ``setdefault``: the local
# ``docker-compose.yml`` ships the api container with
# ``ENV=development`` baked in. ``setdefault`` was a no-op there,
# which meant ``app.core.ratelimit`` picked the ``redis_url`` storage
# backend instead of ``memory://`` and every pytest-xdist worker
# shared one Redis bucket. The per-test ``reset_for_tests()`` call
# raced with other workers' ongoing tests, so any test that drained a
# bucket past its limit could see the limiter quietly reset mid-run
# and the expected ``429`` never fired. Forcing ``ENV=test`` here
# gives each worker its own in-process memory limiter and the
# rate-limit suite runs deterministic under ``-n 4`` (CI's
# ``ENV: test`` env already had this right; the bug was local-only,
# but pinning it here matches CI behaviour everywhere).
os.environ["ENV"] = "test"  # see comment above; xdist+memory limiter
# PyJWT raises `InsecureKeyLengthWarning` for HS256 keys
# under 32 bytes (and `filterwarnings = ["error"]` promotes that
# to a test failure). FORCE-overwrite the value: the dev `.env`
# in the api container ships a short `myjwtsecret`, and
# `setdefault` would leave it in place. We unconditionally swap
# in a 64-byte fixture secret so the test suite doesn't fight
# RFC 7518 §3.2 — production keys still come from the real env.
os.environ["JWT_SECRET"] = "test-secret-please-change-this-is-a-long-enough-key-for-rfc7518"
os.environ["SECRET_KEY"] = "test-secret-please-change-this-is-a-long-enough-key-for-rfc7518"

from app.core.config import get_settings
from app.core.security import hash_password
from app.db import base as db_base
from app.db.session import get_db
from app.main import create_app
from app.models import *  # noqa: F403  ensure mappers registered
from app.models.user import Role, User


@pytest.fixture(scope="session")
def event_loop():  # type: ignore[override]
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def _engine():
    settings = get_settings()
    base_url = settings.database_url
    # Switch to a transient DB name to isolate test runs. Each
    # pytest-xdist worker is a separate process with its own session,
    # so it gets its own DB — but we prefix the UUID with the
    # xdist worker id (e.g. ``gw0``, ``gw1``) so a hung `pg_stat_activity`
    # query during CI debugging immediately tells us which worker is
    # stuck. When pytest runs without xdist the env var is missing
    # and the prefix collapses to ``main``.
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "main")
    test_db = f"lumen_test_{worker_id}_{uuid.uuid4().hex[:8]}"
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

    # Drop the freshly-created DB on any setup failure between the
    # ``CREATE DATABASE`` above and the ``yield`` below. Without this,
    # a transient ``CREATE EXTENSION vector`` or ``metadata.create_all``
    # failure (e.g. a schema migration drifting from a model class)
    # would leak ``lumen_test_gwN_<uuid>`` databases on the postgres
    # server — invisible on CI (the postgres service container is
    # ephemeral per job) but real on any long-lived shared postgres.
    # We don't catch the ``thread`` timeout-method ``os._exit`` path
    # — that one bypasses every Python finally hook by design — but
    # it's a vanishingly rare case once the suite is healthy.
    async def _drop_test_db() -> None:
        admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            async with admin.connect() as conn:
                await conn.execute(
                    text(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)')
                )
        finally:
            await admin.dispose()

    engine = create_async_engine(test_url, future=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
            # Phase E0 — ``lesson_chunks`` declares a ``vector(384)`` column,
            # which requires the pgvector extension. Tests run against the
            # same ``db`` service as dev (``pgvector/pgvector:pg17``) so
            # this should always succeed in CI / make test. We split it
            # into its own statement so a missing extension surfaces here
            # with the real Postgres error, not as a cryptic create_all
            # failure half a screen later.
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(db_base.Base.metadata.create_all)
    except BaseException:
        # Setup failed before we could yield. Dispose the half-init'd
        # engine and drop the orphan DB before re-raising — the normal
        # finally below won't run since we never entered the yield.
        await engine.dispose()
        await _drop_test_db()
        raise

    db_base._engine = engine
    db_base._sessionmaker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    try:
        yield engine
    finally:
        await engine.dispose()
        await _drop_test_db()


def _all_table_names() -> str:
    """Comma-separated list of every table in the metadata, suitable for
    splicing into a ``TRUNCATE`` statement.

    Originally the TRUNCATE list was a hand-maintained literal. That
    drifted: by the time we hit Phase I, six tables (``course_draft_traces``,
    ``learning_paths``, ``learning_path_steps``, ``agent_traces``,
    ``retrieval_audits``, ``mcp_clients``) had been added to the model
    layer but never added here. Most weren't load-bearing for isolation
    (CASCADE cleared them via FK), but ``course_draft_traces`` (FK
    ``SET NULL`` on courses) and ``agent_traces`` (no FK) survived
    cleanup and could leak state into the next test. Building the list
    from ``Base.metadata.tables`` means new tables join the truncate
    set automatically the moment they're declared.
    """
    return ", ".join(f'"{t}"' for t in db_base.Base.metadata.tables.keys())


@pytest_asyncio.fixture
async def db_session(_engine) -> AsyncIterator[AsyncSession]:
    async with db_base.get_sessionmaker()() as session:
        # Clean every table between tests. ``RESTART IDENTITY CASCADE``
        # resets sequences and follows FKs, so even tables not listed
        # by name would still get cleared — but listing them explicitly
        # via the metadata catches the case where a new table has no
        # FK to anything we *do* list (e.g. ``agent_traces``) and would
        # otherwise quietly accumulate rows across tests.
        await session.execute(
            text(f"TRUNCATE {_all_table_names()} RESTART IDENTITY CASCADE")
        )
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
    # the api ships a CSRF-origin middleware that rejects
    # cookie-authenticated mutations whose Origin header isn't in
    # `cors_origins`. The httpx test client doesn't set Origin by
    # default, so every cookie-authed POST/PATCH/DELETE came back
    # 403. We whitelist `http://testserver` (matching base_url) so
    # tests that pass `Origin: http://testserver` explicitly (the
    # CSRF tests in test_csrf_origin.py do) hit the trusted path,
    # AND any test that authenticates via Bearer (the `auth_headers`
    # fixture does this) bypasses the CSRF check entirely. The
    # remaining cookie-only tests still need Origin per-call —
    # that's intentional, the middleware is doing its job.
    os.environ["CORS_ORIGINS"] = '["http://localhost:3000","http://web:3000","http://testserver"]'
    get_settings.cache_clear()  # type: ignore[attr-defined]
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        # Default Origin matches base_url so cookie-authed mutations
        # in most tests don't trip the CSRF guard. Tests that need
        # to exercise CSRF rejection (test_csrf_origin.py) explicitly
        # override with `headers={"Origin": "..."}` per request.
        headers={"Origin": "http://testserver"},
    ) as c:
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
async def seed_lesson(client: AsyncClient):
    """Add one trivial module+lesson to a course so it satisfies the
    publish-time minimum-content check introduced in iteration 43.
    Most legacy tests publish empty courses; rather than retrofit every
    one of them with duplicated boilerplate, call this once."""

    async def _seed(course_id: str, headers: dict) -> str:
        m = await client.post(
            f"/api/v1/courses/{course_id}/modules",
            json={"title": "Seeded module"},
            headers=headers,
        )
        assert m.status_code == 201, m.text
        module_id = m.json()["id"]
        lesson = await client.post(
            f"/api/v1/courses/modules/{module_id}/lessons",
            json={
                "title": "Seeded lesson",
                "type": "text",
                "data": {"type": "text", "body_markdown": "seed"},
            },
            headers=headers,
        )
        assert lesson.status_code == 201, lesson.text
        return lesson.json()["id"]

    return _seed


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
