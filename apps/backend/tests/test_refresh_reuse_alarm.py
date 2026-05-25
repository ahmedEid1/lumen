"""H6 — refresh-token reuse fires an admin notification.

The existing `test_refresh_rotates_and_reuse_detection` in `test_auth.py`
covers the chain-revocation half of the contract. This file covers the
H6 addition: every reuse event also creates an in-app notification
(kind `security.refresh_reuse`) for every active admin user.

Why the alarm matters:

* Refresh-reuse is the single best signal that an account is compromised
  — only stolen credentials trigger it under normal use. Audit logs
  capture it, but an admin won't see the audit row until they go
  looking. A notification lands in the bell next to whatever they
  were doing.
* The alarm is best-effort: a Postgres / dispatch hiccup must not poison
  the auth path. We don't directly test that fail-soft contract here
  (covered by `test_notify_admins_fail_soft` further down) but we do
  test that both effects (chain revocation + notification) happen on
  the green path.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select

from app.models.notification import Notification
from app.models.user import Role


async def test_refresh_reuse_notifies_admins(
    client: AsyncClient, make_user, db_session
) -> None:
    """When a refresh token is replayed, every admin sees a security.refresh_reuse row."""
    # An admin must exist before the reuse fires — otherwise the
    # alarm has nowhere to land. Two admins ensure we exercise the
    # fan-out, not just a singleton case.
    await make_user(email="admin1@lumen.test", password="Password!1234", role=Role.admin)
    await make_user(email="admin2@lumen.test", password="Password!1234", role=Role.admin)

    # The victim — an ordinary student whose refresh chain we'll reuse.
    victim_email = "victim@lumen.test"
    pwd = "Password!1234"
    await make_user(email=victim_email, password=pwd)

    # Log in to mint the first refresh token.
    r = await client.post("/api/v1/auth/login", json={"email": victim_email, "password": pwd})
    assert r.status_code == 200, r.text
    first_refresh = r.cookies.get("refresh") or r.cookies.get("__Host-refresh")
    assert first_refresh

    # Rotate it once — this is the legitimate refresh that revokes the
    # original (sets ``revoked_at``) and issues a new one.
    r2 = await client.post("/api/v1/auth/refresh", cookies={"refresh": first_refresh})
    assert r2.status_code == 200

    # Replay the original refresh — this is the "reuse" event.
    r3 = await client.post("/api/v1/auth/refresh", cookies={"refresh": first_refresh})
    assert r3.status_code == 401
    assert r3.json()["error"]["code"] in {"auth.refresh_reuse", "auth.refresh_invalid"}

    # Notifications are written from the same session as the auth
    # service. ``db_session`` is a fresh session bound to the same
    # engine, so the rows must be visible by now.
    rows = (
        await db_session.execute(
            select(Notification).where(Notification.kind == "security.refresh_reuse")
        )
    ).scalars().all()
    assert len(rows) == 2, f"expected one notification per admin, got {len(rows)}"

    # The two admins must each have exactly one row — no duplicates
    # and no extras for the victim.
    admin_targets = {n.user_id for n in rows}
    assert len(admin_targets) == 2

    # Body / data contract — the dashboard reads these.
    sample = rows[0]
    assert "Refresh-token reuse detected" in sample.title
    assert victim_email in sample.title or victim_email in sample.body
    assert "Chain revoked" in sample.body
    assert isinstance(sample.data, dict)
    assert sample.data.get("user_email") == victim_email
    assert "refresh_token_id" in sample.data
    assert "ip" in sample.data


async def test_refresh_reuse_does_not_notify_non_admins(
    client: AsyncClient, make_user, db_session
) -> None:
    """Only admins receive the alarm; instructors / students must not."""
    await make_user(email="alarm-admin@lumen.test", password="Password!1234", role=Role.admin)
    await make_user(email="alarm-teacher@lumen.test", password="Password!1234", role=Role.instructor)
    await make_user(email="alarm-other@lumen.test", password="Password!1234")  # student

    victim = "alarm-victim@lumen.test"
    pwd = "Password!1234"
    await make_user(email=victim, password=pwd)

    r = await client.post("/api/v1/auth/login", json={"email": victim, "password": pwd})
    first = r.cookies.get("refresh") or r.cookies.get("__Host-refresh")
    await client.post("/api/v1/auth/refresh", cookies={"refresh": first})
    await client.post("/api/v1/auth/refresh", cookies={"refresh": first})

    rows = (
        await db_session.execute(
            select(Notification).where(Notification.kind == "security.refresh_reuse")
        )
    ).scalars().all()
    assert len(rows) == 1, "only the single admin should be notified"


async def test_refresh_reuse_alarm_no_admin_still_revokes(
    client: AsyncClient, make_user, db_session
) -> None:
    """No admin in the DB → alarm is a no-op but chain revocation still fires.

    A first-boot deploy with no admin user yet is a legitimate state
    (the seed task may not have run). The auth path must keep working.
    """
    victim = "no-admin-victim@lumen.test"
    pwd = "Password!1234"
    await make_user(email=victim, password=pwd)

    r = await client.post("/api/v1/auth/login", json={"email": victim, "password": pwd})
    first = r.cookies.get("refresh") or r.cookies.get("__Host-refresh")
    assert first
    await client.post("/api/v1/auth/refresh", cookies={"refresh": first})
    r3 = await client.post("/api/v1/auth/refresh", cookies={"refresh": first})
    # The reuse still gets a 401 — the alarm is observability, not
    # business logic.
    assert r3.status_code == 401

    # And no security.refresh_reuse notification rows exist (no admins
    # to fan out to).
    rows = (
        await db_session.execute(
            select(Notification).where(Notification.kind == "security.refresh_reuse")
        )
    ).scalars().all()
    assert rows == []


async def test_notify_admins_fail_soft(db_session, make_user, monkeypatch) -> None:
    """A broken notifications_repo.create call must not raise upstream.

    Exercises the per-admin try/except in ``services.notifications.notify_admins``
    directly so the auth path's broad-except is the second layer of
    defense rather than the only one.
    """
    from app.repositories import notifications as notifications_repo
    from app.services import notifications as notifications_service

    await make_user(email="fail-soft-admin@lumen.test", password="Password!1234", role=Role.admin)

    async def _boom(*args, **kwargs):  # noqa: ARG001  pytest monkeypatch shim
        raise RuntimeError("simulated dispatch failure")

    monkeypatch.setattr(notifications_repo, "create", _boom)
    # Should not raise even though every per-admin write fails.
    sent = await notifications_service.notify_admins(
        db_session,
        kind="security.refresh_reuse",
        title="t",
        body="b",
        data={},
    )
    assert sent == 0
