"""Moderation data access — events + reports (S6).

``moderation_events`` is the append-only durable history every transition
appends to (ADR-0026 §"Data model changes"); ``course_reports`` is the
user-filed report queue (S6.3 / DR-20). No HTTP concerns here — the service
layer (``app/services/moderation.py``) owns the invariants.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.models.moderation import ModerationEvent

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def record_event(
    db: AsyncSession,
    *,
    course_id: str,
    actor_id: str | None,
    from_state: str | None,
    to_state: str,
    reason_code: str | None = None,
    note: str | None = None,
    classifier_signal: dict[str, Any] | None = None,
) -> ModerationEvent:
    """Append one immutable moderation event (the durable transition history)."""
    event = ModerationEvent(
        course_id=course_id,
        actor_id=actor_id,
        from_state=from_state,
        to_state=to_state,
        reason_code=reason_code,
        note=note,
        classifier_signal=classifier_signal,
    )
    db.add(event)
    await db.flush()
    return event


async def latest_event(db: AsyncSession, course_id: str) -> ModerationEvent | None:
    """Most recent moderation event for a course (latest reason_code / R-M9)."""
    res = await db.execute(
        select(ModerationEvent)
        .where(ModerationEvent.course_id == course_id)
        .order_by(ModerationEvent.created_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Reports (S6.3)
# ---------------------------------------------------------------------------


async def get_open_report(db: AsyncSession, *, course_id: str, reporter_id: str):
    """The reporter's currently-open report on a course, if any (coalescing)."""
    from app.models.moderation import CourseReport, ReportStatus

    res = await db.execute(
        select(CourseReport).where(
            CourseReport.course_id == course_id,
            CourseReport.reporter_id == reporter_id,
            CourseReport.status == ReportStatus.open,
        )
    )
    return res.scalar_one_or_none()


async def count_reports_in_window(db: AsyncSession, *, course_id: str, since) -> int:
    """Count reports filed on a course since ``since`` (per-course brigading cap)."""
    from app.models.moderation import CourseReport

    res = await db.execute(
        select(func.count(CourseReport.id)).where(
            CourseReport.course_id == course_id,
            CourseReport.created_at >= since,
        )
    )
    return int(res.scalar_one())


async def count_open_reports(db: AsyncSession, *, course_id: str) -> int:
    """Count currently-open reports on a course (R-S11 accumulation threshold)."""
    from app.models.moderation import CourseReport, ReportStatus

    res = await db.execute(
        select(func.count(CourseReport.id)).where(
            CourseReport.course_id == course_id,
            CourseReport.status == ReportStatus.open,
        )
    )
    return int(res.scalar_one())


async def create_report(
    db: AsyncSession,
    *,
    course_id: str,
    reporter_id: str,
    reason: str,
    note: str | None,
):
    """Insert a new open report row."""
    from app.models.moderation import CourseReport, ReportStatus

    report = CourseReport(
        course_id=course_id,
        reporter_id=reporter_id,
        reason=reason,
        note=note,
        status=ReportStatus.open,
    )
    db.add(report)
    await db.flush()
    return report


async def get_report(db: AsyncSession, report_id: str):
    from app.models.moderation import CourseReport

    return await db.get(CourseReport, report_id)


async def list_reports(
    db: AsyncSession,
    *,
    status: str | None = None,
    reason: str | None = None,
    course_id: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
):
    """Cursor-paginated report listing (newest first), with optional filters.

    F5 (S6 gate): rows are genuinely ordered ``(created_at DESC, id DESC)``.
    The previous implementation ordered (and cursored) on ``id`` alone — but
    ``id`` is a random nanoid, so "newest first" was actually random order and
    the cursor walked an arbitrary sequence. The cursor is the ``id`` of the last
    row from the previous page; we load that anchor row and page strictly past it
    with a ``(created_at, id)`` row-value comparison (the audit-log cursor
    reference at ``admin.list_audit`` resolves its anchor by id the same way, but
    here we add ``id`` as a true tiebreaker so duplicate ``created_at`` instants
    page deterministically — ``ix_course_reports_status_created (status,
    created_at)`` serves the status-filtered scan).
    """
    from sqlalchemy import and_, or_
    from sqlalchemy.orm import selectinload

    from app.models.moderation import CourseReport

    stmt = select(CourseReport).options(
        selectinload(CourseReport.reporter),
        selectinload(CourseReport.course),
    )
    if status is not None:
        stmt = stmt.where(CourseReport.status == status)
    if reason is not None:
        stmt = stmt.where(CourseReport.reason == reason)
    if course_id is not None:
        stmt = stmt.where(CourseReport.course_id == course_id)
    if cursor is not None:
        anchor = await db.get(CourseReport, cursor)
        if anchor is not None:
            # Page strictly past the anchor in (created_at DESC, id DESC) order:
            # an older instant, OR the same instant with a smaller id tiebreaker.
            stmt = stmt.where(
                or_(
                    CourseReport.created_at < anchor.created_at,
                    and_(
                        CourseReport.created_at == anchor.created_at,
                        CourseReport.id < anchor.id,
                    ),
                )
            )
    stmt = stmt.order_by(CourseReport.created_at.desc(), CourseReport.id.desc()).limit(limit)
    res = await db.execute(stmt)
    return list(res.scalars().unique().all())
