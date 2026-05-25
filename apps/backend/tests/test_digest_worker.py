"""Daily digest worker (Phase D4).

Seed a user with ``digest_daily`` prefs, write three notifications,
run the digest task in-process, and assert:
- exactly one email enqueue happens for that user,
- the email body references all three notification titles,
- every digested row has ``digested_at`` stamped,
- a second run produces zero further emails (idempotent).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationKind
from app.schemas.notification_prefs import NotificationDispatch
from app.workers.tasks import digest as digest_task


async def test_digest_bundles_unread_into_one_email(db_session: AsyncSession, make_user) -> None:
    user = await make_user()
    user.notification_prefs = {
        "discussion_reply": NotificationDispatch.digest_daily.value,
        "enrolled": NotificationDispatch.digest_daily.value,
    }
    db_session.add(user)

    titles = ["Reply on thread A", "Reply on thread B", "Welcome to Course X"]
    db_session.add_all(
        [
            Notification(
                user_id=user.id,
                kind=NotificationKind.discussion_reply,
                title=titles[0],
                body="alice replied",
                data={},
            ),
            Notification(
                user_id=user.id,
                kind=NotificationKind.discussion_reply,
                title=titles[1],
                body="bob replied",
                data={},
            ),
            Notification(
                user_id=user.id,
                kind=NotificationKind.enrolled,
                title=titles[2],
                body="You're enrolled.",
                data={},
            ),
        ]
    )
    await db_session.commit()

    email_mock = MagicMock()
    email_mock.delay = MagicMock()

    # Patch the email task lookup inside the worker module — the
    # import is deferred (function-local) so we monkey-patch at the
    # import-time module-level binding.
    with patch.dict(
        "sys.modules",
        {"app.workers.tasks.email": MagicMock(send=email_mock)},
    ):
        sent = await digest_task._run_digests(db_session)

    assert sent == 1
    email_mock.delay.assert_called_once()
    call_args = email_mock.delay.call_args
    # positional args: (to, subject, text, html)
    to_addr, subject, text_body, html_body = call_args.args
    assert to_addr == user.email
    assert "daily digest" in subject.lower()
    for title in titles:
        assert title in text_body
        assert title in html_body

    # Every row stamped with digested_at.
    rows = (
        (await db_session.execute(select(Notification).where(Notification.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 3
    assert all(n.digested_at is not None for n in rows)

    # Second run is a no-op (idempotency via digested_at).
    email_mock.delay.reset_mock()
    with patch.dict(
        "sys.modules",
        {"app.workers.tasks.email": MagicMock(send=email_mock)},
    ):
        sent_again = await digest_task._run_digests(db_session)
    assert sent_again == 0
    email_mock.delay.assert_not_called()


async def test_digest_skips_users_with_no_digest_kinds(db_session: AsyncSession, make_user) -> None:
    """Users with prefs but no ``digest_daily`` selection get no email."""
    user = await make_user()
    user.notification_prefs = {
        "enrolled": NotificationDispatch.email_immediate.value,
    }
    db_session.add(user)
    db_session.add(
        Notification(
            user_id=user.id,
            kind=NotificationKind.enrolled,
            title="hi",
            body="",
            data={},
        )
    )
    await db_session.commit()

    email_mock = MagicMock()
    email_mock.delay = MagicMock()
    with patch.dict(
        "sys.modules",
        {"app.workers.tasks.email": MagicMock(send=email_mock)},
    ):
        sent = await digest_task._run_digests(db_session)
    assert sent == 0
    email_mock.delay.assert_not_called()


async def test_digest_skips_read_notifications(db_session: AsyncSession, make_user) -> None:
    """Read rows never enter the bundle even if their kind is digest_daily."""
    from datetime import UTC, datetime

    user = await make_user()
    user.notification_prefs = {"discussion_reply": NotificationDispatch.digest_daily.value}
    db_session.add(user)
    n = Notification(
        user_id=user.id,
        kind=NotificationKind.discussion_reply,
        title="already read",
        body="",
        data={},
        read_at=datetime.now(UTC),
    )
    db_session.add(n)
    await db_session.commit()

    email_mock = MagicMock()
    email_mock.delay = MagicMock()
    with patch.dict(
        "sys.modules",
        {"app.workers.tasks.email": MagicMock(send=email_mock)},
    ):
        sent = await digest_task._run_digests(db_session)
    assert sent == 0
