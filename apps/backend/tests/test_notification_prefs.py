"""Per-kind notification preferences (Phase D4).

Covers:
- ``GET /me/notifications/prefs`` materialises every NotificationKind
  with the ``in_app`` default for users who never set a pref.
- ``PUT /me/notifications/prefs`` merges partial updates without
  clobbering unspecified kinds.
- Invalid kind or dispatch values are rejected by Pydantic.
- The notifications-repo ``create`` honours ``off`` (skip), ``in_app``
  (write row, no email), and ``email_immediate`` (write row + enqueue).
"""

from __future__ import annotations

from unittest.mock import patch

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationKind
from app.models.user import Role
from app.repositories import notifications as notifications_repo
from app.schemas.notification_prefs import NotificationDispatch


async def test_get_prefs_returns_all_kinds_with_defaults(client: AsyncClient, auth_headers) -> None:
    headers = await auth_headers(role=Role.student)
    r = await client.get("/api/v1/me/notifications/prefs", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "prefs" in body
    prefs = body["prefs"]
    # Every NotificationKind is present.
    expected = {k.value for k in NotificationKind}
    assert set(prefs.keys()) == expected
    # All default to in_app.
    assert set(prefs.values()) == {"in_app"}


async def test_update_prefs_partial_merge(client: AsyncClient, auth_headers) -> None:
    headers = await auth_headers(role=Role.student)
    # First update: opt one kind into digest_daily.
    payload = {"prefs": {"enrolled": "digest_daily"}}
    r = await client.put("/api/v1/me/notifications/prefs", headers=headers, json=payload)
    assert r.status_code == 200, r.text
    prefs = r.json()["prefs"]
    assert prefs["enrolled"] == "digest_daily"
    # Untouched kinds keep the default.
    assert prefs["review_received"] == "in_app"
    assert prefs["certificate_ready"] == "in_app"

    # Second update only touches a different kind — the first one must persist.
    payload2 = {"prefs": {"review_received": "email_immediate"}}
    r2 = await client.put("/api/v1/me/notifications/prefs", headers=headers, json=payload2)
    assert r2.status_code == 200
    prefs2 = r2.json()["prefs"]
    assert prefs2["enrolled"] == "digest_daily"  # preserved
    assert prefs2["review_received"] == "email_immediate"


async def test_update_prefs_rejects_invalid_kind(client: AsyncClient, auth_headers) -> None:
    headers = await auth_headers(role=Role.student)
    payload = {"prefs": {"not_a_kind": "in_app"}}
    r = await client.put("/api/v1/me/notifications/prefs", headers=headers, json=payload)
    assert r.status_code == 422, r.text


async def test_update_prefs_rejects_invalid_dispatch(client: AsyncClient, auth_headers) -> None:
    headers = await auth_headers(role=Role.student)
    payload = {"prefs": {"enrolled": "carrier_pigeon"}}
    r = await client.put("/api/v1/me/notifications/prefs", headers=headers, json=payload)
    assert r.status_code == 422


async def test_update_prefs_requires_auth(client: AsyncClient) -> None:
    r = await client.put("/api/v1/me/notifications/prefs", json={"prefs": {}})
    assert r.status_code == 401


async def test_notifications_repo_create_off_skips_row(db_session: AsyncSession, make_user) -> None:
    """``off`` prefs must drop the notification entirely."""
    user = await make_user()
    user.notification_prefs = {"enrolled": NotificationDispatch.off.value}
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    result = await notifications_repo.create(
        db_session,
        user_id=user.id,
        kind=NotificationKind.enrolled,
        title="Welcome!",
        body="",
    )
    assert result is None

    rows = (
        (await db_session.execute(select(Notification).where(Notification.user_id == user.id)))
        .scalars()
        .all()
    )
    assert rows == []


async def test_notifications_repo_create_in_app_default(
    db_session: AsyncSession, make_user
) -> None:
    """Default (no stored pref) writes the row with no email enqueue."""
    user = await make_user()

    with patch("app.repositories.notifications._enqueue_immediate_email") as enqueue_mock:
        n = await notifications_repo.create(
            db_session,
            user_id=user.id,
            kind=NotificationKind.enrolled,
            title="Welcome!",
        )
    assert n is not None
    assert n.user_id == user.id
    enqueue_mock.assert_not_called()


async def test_notifications_repo_create_email_immediate_enqueues(
    db_session: AsyncSession, make_user
) -> None:
    """``email_immediate`` writes the row and fires off the email task."""
    user = await make_user()
    user.notification_prefs = {"review_received": NotificationDispatch.email_immediate.value}
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    with patch("app.repositories.notifications._enqueue_immediate_email") as enqueue_mock:
        n = await notifications_repo.create(
            db_session,
            user_id=user.id,
            kind=NotificationKind.review_received,
            title="New review",
        )
    assert n is not None
    enqueue_mock.assert_called_once()
    # The notification row must exist regardless of enqueue outcome.
    rows = (
        (await db_session.execute(select(Notification).where(Notification.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_notifications_repo_create_digest_daily_writes_but_no_email(
    db_session: AsyncSession, make_user
) -> None:
    """``digest_daily`` writes the row; the digest worker handles email later."""
    user = await make_user()
    user.notification_prefs = {"discussion_reply": NotificationDispatch.digest_daily.value}
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    with patch("app.repositories.notifications._enqueue_immediate_email") as enqueue_mock:
        n = await notifications_repo.create(
            db_session,
            user_id=user.id,
            kind=NotificationKind.discussion_reply,
            title="Reply",
        )
    assert n is not None
    enqueue_mock.assert_not_called()
    assert n.digested_at is None
