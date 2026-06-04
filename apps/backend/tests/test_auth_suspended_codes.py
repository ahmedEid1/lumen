"""S6.7 — distinct auth codes for suspended vs deleted accounts (FR-SUSP-04 /
ADR-0030 §D3).

``authenticate`` / ``rotate_refresh`` surface ``auth.account_suspended`` for a
suspended account (``is_active=False AND deleted_at IS NULL``) and
``auth.account_deleted`` for a tombstoned one (``deleted_at IS NOT NULL``),
replacing the generic ``auth.inactive`` / ``auth.invalid_credentials``. Both are
401. The suspended/deleted disclosure happens ONLY after a correct password, so
an attacker without the credential can't enumerate account state.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Role


async def test_suspended_login_returns_suspended_code(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    email = f"susp-login-{uuid.uuid4().hex[:6]}@lumen.test"
    password = "Password!1234"
    user = await make_user(email=email, password=password, role=Role.user)
    user.is_active = False  # suspended (deleted_at stays null)
    await db_session.commit()

    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "auth.account_suspended"


async def test_deleted_login_returns_deleted_code(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    email = f"del-login-{uuid.uuid4().hex[:6]}@lumen.test"
    password = "Password!1234"
    user = await make_user(email=email, password=password, role=Role.user)
    user.is_active = False
    user.deleted_at = datetime.now(UTC)  # tombstone
    await db_session.commit()

    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "auth.account_deleted"


async def test_suspended_wrong_password_does_not_disclose_state(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    # A wrong password against a suspended account returns the generic
    # invalid_credentials — the suspended/deleted state is disclosed ONLY after
    # a correct password (no enumeration oracle).
    email = f"susp-wrong-{uuid.uuid4().hex[:6]}@lumen.test"
    user = await make_user(email=email, password="Password!1234", role=Role.user)
    user.is_active = False
    await db_session.commit()

    r = await client.post("/api/v1/auth/login", json={"email": email, "password": "WrongPass!9999"})
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "auth.invalid_credentials"


async def test_suspended_refresh_returns_suspended_code(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    # Log in to get a live refresh cookie, THEN suspend, THEN refresh → the
    # precise suspended code (the caller proved token possession).
    email = f"susp-ref-{uuid.uuid4().hex[:6]}@lumen.test"
    password = "Password!1234"
    user = await make_user(email=email, password=password, role=Role.user)
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text

    user.is_active = False
    await db_session.commit()

    r = await client.post("/api/v1/auth/refresh")
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "auth.account_suspended"


async def test_deleted_refresh_returns_deleted_code(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    email = f"del-ref-{uuid.uuid4().hex[:6]}@lumen.test"
    password = "Password!1234"
    user = await make_user(email=email, password=password, role=Role.user)
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text

    user.is_active = False
    user.deleted_at = datetime.now(UTC)
    await db_session.commit()

    r = await client.post("/api/v1/auth/refresh")
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "auth.account_deleted"
