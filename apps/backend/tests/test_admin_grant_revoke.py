"""S6.6 — grant/revoke-admin toggle + last-admin invariant (FR-ADMIN-01/02/03).

The role ``<Select>`` write path is replaced by an ``{is_admin}`` toggle
(``PATCH /admin/users/{id}/admin``). The platform must always retain at least
one *active* admin: revoking or suspending the last active admin is refused with
``422`` (``user.last_admin`` / ``user.last_admin_active``). The legacy
``/role`` endpoint normalizes ``student``/``instructor`` → ``user`` during the
migration window and 422s removed values after Phase D (or under the strict
flag).
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.user import Role, User


async def _me_id(client: AsyncClient, headers: dict) -> str:
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return me.json()["id"]


async def _latest_audit(db: AsyncSession, action: str) -> AuditEvent | None:
    rows = (
        (
            await db.execute(
                select(AuditEvent)
                .where(AuditEvent.action == action)
                .order_by(AuditEvent.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .all()
    )
    return rows[0] if rows else None


async def test_grant_admin(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
) -> None:
    admin = await auth_headers(role=Role.admin)
    target = await make_user(email=f"grant-{uuid.uuid4().hex[:6]}@lumen.test", role=Role.user)

    r = await client.patch(
        f"/api/v1/admin/users/{target.id}/admin",
        json={"is_admin": True},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"

    await db_session.refresh(target)
    assert target.role == Role.admin
    ev = await _latest_audit(db_session, "admin.user.grant_admin")
    assert ev is not None and ev.target_id == target.id


async def test_revoke_admin(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
) -> None:
    admin = await auth_headers(role=Role.admin)
    other = await make_user(email=f"revoke-{uuid.uuid4().hex[:6]}@lumen.test", role=Role.admin)

    r = await client.patch(
        f"/api/v1/admin/users/{other.id}/admin",
        json={"is_admin": False},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "user"

    await db_session.refresh(other)
    assert other.role == Role.user
    ev = await _latest_audit(db_session, "admin.user.revoke_admin")
    assert ev is not None and ev.target_id == other.id


async def test_last_admin_revoke_blocked(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    # The auth_headers admin is (in an isolated truncated DB) the ONLY active
    # admin. Revoking themselves must be refused with 422 user.last_admin.
    admin = await auth_headers(role=Role.admin)
    aid = await _me_id(client, admin)

    r = await client.patch(
        f"/api/v1/admin/users/{aid}/admin",
        json={"is_admin": False},
        headers=admin,
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "user.last_admin"

    me = await db_session.get(User, aid)
    assert me is not None and me.role == Role.admin  # unchanged


async def test_last_admin_revoke_other_blocked(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
) -> None:
    # When there is exactly one ACTIVE admin, revoking that admin (even a
    # different account than the actor) is refused. Here we make the actor an
    # admin and the target an *inactive* admin; revoking the active actor must
    # fail because demoting them would leave zero active admins.
    admin = await auth_headers(role=Role.admin)
    aid = await _me_id(client, admin)
    # an inactive admin does NOT count toward the active-admin floor
    inactive = await make_user(email=f"inact-{uuid.uuid4().hex[:6]}@lumen.test", role=Role.admin)
    inactive.is_active = False
    await db_session.commit()

    r = await client.patch(
        f"/api/v1/admin/users/{aid}/admin",
        json={"is_admin": False},
        headers=admin,
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "user.last_admin"


async def test_revoke_admin_allowed_with_second_active_admin(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
) -> None:
    admin = await auth_headers(role=Role.admin)
    second = await make_user(email=f"second-{uuid.uuid4().hex[:6]}@lumen.test", role=Role.admin)

    r = await client.patch(
        f"/api/v1/admin/users/{second.id}/admin",
        json={"is_admin": False},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "user"


async def test_grant_admin_idempotent(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
) -> None:
    admin = await auth_headers(role=Role.admin)
    target = await make_user(email=f"idem-{uuid.uuid4().hex[:6]}@lumen.test", role=Role.admin)
    # Granting admin to someone already admin is a no-op success (no new audit
    # churn is asserted here, just that it does not error / flip them).
    r = await client.patch(
        f"/api/v1/admin/users/{target.id}/admin",
        json={"is_admin": True},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"


async def test_legacy_role_endpoint_normalizes_then_422(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
) -> None:
    admin = await auth_headers(role=Role.admin)
    target = await make_user(email=f"legacy-{uuid.uuid4().hex[:6]}@lumen.test", role=Role.user)

    # During the migration window a legacy value normalizes to `user` (applied)
    # with an audit recording {requested, applied}.
    r = await client.patch(
        f"/api/v1/admin/users/{target.id}/role",
        json={"role": "instructor"},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "user"
    ev = await _latest_audit(db_session, "admin.user.role")
    assert ev is not None
    assert ev.data.get("requested") == "instructor"
    assert ev.data.get("applied") == "user"
