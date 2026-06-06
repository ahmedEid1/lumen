"""Async data access for :class:`~app.models.learning_brief.LearningBrief`.

S3.3. No HTTP concerns, no business rules — just the persistence verbs the
elicitation service composes: create, owner-scoped fetch of an active session,
the per-window session-quota COUNT (R-M10), and the finalize stamp.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.learning_brief import LearningBrief


async def create_brief(db: AsyncSession, *, owner_id: str, source_goal_enc: bytes) -> LearningBrief:
    """Insert a fresh in-progress brief (``finalized_at IS NULL``)."""
    brief = LearningBrief(owner_id=owner_id, source_goal_enc=source_goal_enc)
    db.add(brief)
    await db.flush()
    return brief


async def get_active_session(
    db: AsyncSession, *, session_id: str, owner_id: str
) -> LearningBrief | None:
    """Fetch a brief by id, scoped to its owner (existence-hide for others).

    Returns ``None`` when the id is unknown OR belongs to a different user —
    the API layer renders both as a 404 so a cross-user probe can't tell a
    missing session from someone else's (FR-DEFINE / existence-hide).
    """
    stmt = select(LearningBrief).where(
        LearningBrief.id == session_id, LearningBrief.owner_id == owner_id
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def count_sessions_in_window(db: AsyncSession, *, owner_id: str, window_seconds: int) -> int:
    """COUNT of briefs the owner *started* within the trailing window (R-M10).

    Index-covered by ``ix_learning_briefs_owner_created``. Counts every started
    session (finalized or not) — a started brief is the unit the session quota
    bounds, regardless of whether the user followed through to finalize.
    """
    stmt = select(func.count(LearningBrief.id)).where(
        LearningBrief.owner_id == owner_id,
        LearningBrief.created_at
        > func.now() - func.make_interval(0, 0, 0, 0, 0, 0, window_seconds),
    )
    return int((await db.execute(stmt)).scalar_one() or 0)
