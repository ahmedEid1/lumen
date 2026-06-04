"""S6.8 — cooperative cancellation (ADR-0030 §D4 / R-S10).

A shared helper ``account.assert_account_active(db, user_id)`` re-loads
``is_active`` and raises ``ForbiddenError(code="account.access_revoked")`` (403)
when an account flips to inactive (suspend or delete) mid-flight. It is wired at
the streaming-tutor heartbeat and at build/clone phase fences so an in-flight
LLM job aborts instead of running to completion (bounded otherwise only by the
15-min token TTL).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError
from app.services import account as account_service


async def test_assert_account_active_passes_for_live_user(
    db_session: AsyncSession, make_user
) -> None:
    user = await make_user(email=f"live-{uuid.uuid4().hex[:6]}@lumen.test")
    # No raise for a live, active account.
    await account_service.assert_account_active(db_session, user.id)


async def test_assert_account_active_raises_on_suspend(db_session: AsyncSession, make_user) -> None:
    user = await make_user(email=f"susp-{uuid.uuid4().hex[:6]}@lumen.test")
    user.is_active = False
    await db_session.commit()

    with pytest.raises(ForbiddenError) as exc:
        await account_service.assert_account_active(db_session, user.id)
    assert exc.value.code == "account.access_revoked"
    assert exc.value.status_code == 403


async def test_assert_account_active_raises_on_delete(db_session: AsyncSession, make_user) -> None:
    from datetime import UTC, datetime

    user = await make_user(email=f"del-{uuid.uuid4().hex[:6]}@lumen.test")
    user.is_active = False
    user.deleted_at = datetime.now(UTC)
    await db_session.commit()

    with pytest.raises(ForbiddenError) as exc:
        await account_service.assert_account_active(db_session, user.id)
    assert exc.value.code == "account.access_revoked"


async def test_assert_account_active_raises_on_missing_user(
    db_session: AsyncSession,
) -> None:
    # A vanished user (id not present) is treated as revoked — fail closed.
    with pytest.raises(ForbiddenError) as exc:
        await account_service.assert_account_active(db_session, "nonexistent-id-000000")
    assert exc.value.code == "account.access_revoked"


async def test_assert_account_active_sees_fresh_state_not_stale_identity(
    db_session: AsyncSession, make_user
) -> None:
    # The helper must observe the CURRENT DB state even if the session's
    # identity map holds an older copy — it re-reads is_active (the whole point
    # of cooperative cancellation is catching a flip that happened elsewhere).
    user = await make_user(email=f"fresh-{uuid.uuid4().hex[:6]}@lumen.test")
    # flip via a separate UPDATE so the in-session object is stale
    from sqlalchemy import update

    from app.models.user import User

    await db_session.execute(update(User).where(User.id == user.id).values(is_active=False))
    await db_session.commit()

    with pytest.raises(ForbiddenError):
        await account_service.assert_account_active(db_session, user.id)


def test_build_fence_wired_in_orchestrator() -> None:
    # Defense-in-depth structural check: the authoring orchestrator imports and
    # calls assert_account_active at its phase fences (R-S10 checklist primitive).
    import inspect

    from app.services import authoring_orchestrator

    src = inspect.getsource(authoring_orchestrator)
    assert "assert_account_active" in src, "build fence must call assert_account_active"


def test_streaming_heartbeat_wired() -> None:
    import inspect

    from app.workers.tasks import tutor_streaming

    src = inspect.getsource(tutor_streaming)
    assert "assert_account_active" in src, "streaming heartbeat must call assert_account_active"
