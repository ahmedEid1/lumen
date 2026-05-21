"""Mark-all-read endpoint for notifications.

A learner with N unread notifications used to need N
``POST /me/notifications/{id}/read`` round trips to clear the
badge. ``POST /me/notifications/read-all`` does it in one
UPDATE, returns the count touched so the UI can update without
a follow-up GET, and is scoped strictly to the calling user.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationKind
from app.repositories import notifications as notifications_repo


async def _seed(db: AsyncSession, *, user_id: str, n: int) -> list[Notification]:
    items: list[Notification] = []
    for i in range(n):
        nf = await notifications_repo.create(
            db,
            user_id=user_id,
            kind=NotificationKind.enrolled,
            title=f"Welcome {i}",
            body="",
        )
        items.append(nf)
    await db.commit()
    return items


async def test_read_all_clears_only_callers_unread(
    client: AsyncClient, auth_headers, db_session: AsyncSession, make_user
) -> None:
    me = await make_user(email=f"me-{uuid.uuid4().hex[:6]}@lumen.test")
    other = await make_user(email=f"o-{uuid.uuid4().hex[:6]}@lumen.test")
    await _seed(db_session, user_id=me.id, n=3)
    await _seed(db_session, user_id=other.id, n=2)

    # Log in as `me` via the auth_headers fixture pattern — but
    # auth_headers always creates a fresh user. Login manually instead.
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": me.email, "password": "Password!1234"},
    )
    assert login.status_code == 200, login.text
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}

    r = await client.post("/api/v1/me/notifications/read-all", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["marked_read"] == 3

    # All of my notifications now have read_at set.
    mine = await client.get("/api/v1/me/notifications", headers=h)
    assert all(n["read_at"] is not None for n in mine.json())

    # The other user's notifications are untouched.
    others = (
        await db_session.execute(
            select(Notification).where(Notification.user_id == other.id)
        )
    ).scalars().all()
    assert others and all(n.read_at is None for n in others)


async def test_read_all_is_idempotent(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    h = await auth_headers()
    # auth_headers seeded a user; their welcome notification (if any)
    # is irrelevant — first call clears whatever's unread, second
    # call must return marked_read=0 without erroring.
    first = await client.post("/api/v1/me/notifications/read-all", headers=h)
    assert first.status_code == 200
    second = await client.post("/api/v1/me/notifications/read-all", headers=h)
    assert second.status_code == 200
    assert second.json()["marked_read"] == 0


async def test_read_all_requires_auth(client: AsyncClient) -> None:
    r = await client.post("/api/v1/me/notifications/read-all")
    assert r.status_code == 401
