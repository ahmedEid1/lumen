"""Regression — GET /me/notifications must not 500 on out-of-enum sub-kinds.

The H6 security-alarm path (``services.auth`` → ``notify_admins``) writes a
notification whose ``kind`` is the *sub-kind* string ``security.refresh_reuse``.
That value is intentionally NOT a member of :class:`NotificationKind` — the DB
column is a plain ``String(40)`` precisely so new security sub-kinds can ship
without an enum migration.

Before this fix, ``NotificationOut.kind`` was typed as ``NotificationKind``, so
``model_validate`` raised a Pydantic ``ValidationError`` the moment the endpoint
tried to serialise an admin's ``security.refresh_reuse`` row → unhandled → HTTP
500. Students never receive that row, so the bell worked for them and broke for
every admin. This test pins the contract: the endpoint returns 200 and faithfully
echoes the raw sub-kind string.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.models.user import Role


async def test_notifications_endpoint_serialises_out_of_enum_subkind(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    """An admin with a ``security.refresh_reuse`` row gets 200, not 500."""
    email = f"admin-{uuid.uuid4().hex[:8]}@lumen.test"
    password = "Password!1234"
    admin = await make_user(email=email, password=password, role=Role.admin)

    # Seed the exact row the H6 alarm path writes: a sub-kind string that
    # is NOT in NotificationKind. This is the admin-only data that differs
    # from a student's notifications and triggered the 500.
    db_session.add(
        Notification(
            user_id=admin.id,
            kind="security.refresh_reuse",  # type: ignore[arg-type]
            title="Refresh-token reuse detected for user victim@lumen.test",
            body="Chain revoked.",
            data={"user_email": "victim@lumen.test", "ip": "1.2.3.4"},
        )
    )
    await db_session.commit()

    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.get("/api/v1/me/notifications", headers=headers)
    assert resp.status_code == 200, resp.text

    items = resp.json()
    reuse = [n for n in items if n["kind"] == "security.refresh_reuse"]
    assert len(reuse) == 1, f"expected the sub-kind row to round-trip, got {items}"
    row = reuse[0]
    # Shape contract the bell consumes.
    assert row["title"].startswith("Refresh-token reuse detected")
    assert row["body"] == "Chain revoked."
    assert row["data"]["user_email"] == "victim@lumen.test"
    assert row["read_at"] is None
    assert "id" in row and "created_at" in row


async def test_notifications_endpoint_still_serialises_known_kinds(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    """Widening kind to str must not regress the in-enum happy path."""
    email = f"student-{uuid.uuid4().hex[:8]}@lumen.test"
    password = "Password!1234"
    student = await make_user(email=email, password=password, role=Role.student)

    db_session.add(
        Notification(
            user_id=student.id,
            kind="enrolled",  # type: ignore[arg-type]
            title="Welcome",
            body="You enrolled",
            data={"course_id": "abc"},
        )
    )
    await db_session.commit()

    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.get("/api/v1/me/notifications", headers=headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert any(n["kind"] == "enrolled" for n in items)
