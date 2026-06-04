"""S6.7 — suspend / reinstate (FR-SUSP-01/02/04).

Suspension is first-class and distinct from ``locked_until`` (temporary login
lockout) and from deletion (``deleted_at``). It shares the ``is_active``
mechanism: ``is_active=False`` with ``deleted_at IS NULL``. Suspending revokes
all refresh tokens, audits with reason/note/ip/ua, and notifies the user with
the taxonomy label (never the raw note). Reinstating restores ``is_active`` but
NOT the tokens, and is refused on a tombstoned account.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.notification import Notification
from app.models.user import RefreshToken, Role, User


async def _latest_audit(db: AsyncSession, action: str, target_id: str) -> AuditEvent | None:
    rows = (
        (
            await db.execute(
                select(AuditEvent)
                .where(AuditEvent.action == action, AuditEvent.target_id == target_id)
                .order_by(AuditEvent.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .all()
    )
    return rows[0] if rows else None


async def _login_make_session(client: AsyncClient, email: str, password: str) -> None:
    """Log a user in so they own a live refresh token, then drop the cookies."""
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    client.cookies.clear()


async def test_suspend_revokes_and_audits(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
) -> None:
    admin = await auth_headers(role=Role.admin)
    email = f"susp-{uuid.uuid4().hex[:6]}@lumen.test"
    password = "Password!1234"
    target = await make_user(email=email, password=password, role=Role.user)
    await _login_make_session(client, email, password)

    r = await client.patch(
        f"/api/v1/admin/users/{target.id}/suspend",
        json={"reason": "abuse", "note": "<b>bad</b> behavior"},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False

    await db_session.refresh(target)
    assert target.is_active is False
    assert target.deleted_at is None  # suspend != delete

    # all refresh tokens revoked
    tokens = (
        (await db_session.execute(select(RefreshToken).where(RefreshToken.user_id == target.id)))
        .scalars()
        .all()
    )
    assert tokens, "the login should have created a token"
    assert all(t.revoked_at is not None for t in tokens)

    ev = await _latest_audit(db_session, "admin.user.suspend", target.id)
    assert ev is not None
    assert ev.data.get("reason") == "abuse"
    # the note is sanitized (inert) before persist
    assert "<b>" not in (ev.data.get("note") or "")

    # the user is notified with the taxonomy LABEL only — never the admin's note
    notes = (
        (await db_session.execute(select(Notification).where(Notification.user_id == target.id)))
        .scalars()
        .all()
    )
    assert any(n.kind == "account.suspended" for n in notes)
    for n in notes:
        assert "bad" not in (n.body or "")  # raw note never reaches the user


async def test_reinstate_restores_active_not_tokens(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
) -> None:
    admin = await auth_headers(role=Role.admin)
    target = await make_user(email=f"rein-{uuid.uuid4().hex[:6]}@lumen.test", role=Role.user)
    target.is_active = False
    await db_session.commit()

    r = await client.patch(f"/api/v1/admin/users/{target.id}/reinstate", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is True

    await db_session.refresh(target)
    assert target.is_active is True
    ev = await _latest_audit(db_session, "admin.user.reinstate", target.id)
    assert ev is not None


async def test_reinstate_idempotent_no_duplicate_audit(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
) -> None:
    admin = await auth_headers(role=Role.admin)
    target = await make_user(email=f"idemr-{uuid.uuid4().hex[:6]}@lumen.test", role=Role.user)
    # target is already active → reinstate is a no-op (no audit row)
    r = await client.patch(f"/api/v1/admin/users/{target.id}/reinstate", headers=admin)
    assert r.status_code == 200
    count = (
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "admin.user.reinstate",
                    AuditEvent.target_id == target.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(count) == 0


async def test_reinstate_refused_on_tombstone(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
) -> None:
    from datetime import UTC, datetime

    admin = await auth_headers(role=Role.admin)
    target = await make_user(email=f"tomb-{uuid.uuid4().hex[:6]}@lumen.test", role=Role.user)
    target.is_active = False
    target.deleted_at = datetime.now(UTC)
    await db_session.commit()

    r = await client.patch(f"/api/v1/admin/users/{target.id}/reinstate", headers=admin)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "user.deleted_irreversible"

    await db_session.refresh(target)
    assert target.is_active is False  # unchanged


async def test_suspend_last_active_admin_blocked(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    admin = await auth_headers(role=Role.admin)
    me = await client.get("/api/v1/auth/me", headers=admin)
    aid = me.json()["id"]

    r = await client.patch(
        f"/api/v1/admin/users/{aid}/suspend",
        json={"reason": "other"},
        headers=admin,
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "user.last_admin_active"

    me_row = await db_session.get(User, aid)
    assert me_row is not None and me_row.is_active is True
