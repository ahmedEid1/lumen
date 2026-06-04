"""S6.4 — admin moderation + report endpoints (ADR-0026 §"API changes").

DB-backed (runs under ``make test.api``). Covers the moderation queue
(pending-only, eager-loaded), the admin action endpoints (approve/reject/
delist/relist/remove, admin-gated), the report listing + atomic resolve (single
linked audit trail), the R-S11 approved-course requeue (never auto-delist), and
inert report-content rendering (FR-MOD-13).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.course import Course, CourseStatus, ModerationState, Visibility
from app.models.moderation import CourseReport, ReportStatus
from app.models.user import Role


async def _make_subject(db: AsyncSession):
    from app.models.course import Subject

    s = Subject(title="S", slug=f"s-{uuid.uuid4().hex[:8]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _course(
    db: AsyncSession,
    owner_id: str,
    subject_id: str,
    *,
    status=CourseStatus.published,
    visibility=Visibility.public,
    moderation_state=ModerationState.pending_review,
) -> Course:
    c = Course(
        owner_id=owner_id,
        subject_id=subject_id,
        title=f"C {uuid.uuid4().hex[:6]}",
        slug=f"c-{uuid.uuid4().hex[:8]}",
        overview="o",
        status=status,
        visibility=visibility,
        moderation_state=moderation_state,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def _eligible_reporter(make_user, db: AsyncSession):
    user = await make_user(role=Role.user)
    user.email_verified_at = datetime.now(UTC)
    user.created_at = datetime.now(UTC) - timedelta(days=30)
    await db.commit()
    return user


async def _login(client: AsyncClient, user) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "Password!1234"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_moderation_queue_lists_pending_only(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
):
    admin = await auth_headers(role=Role.admin)
    owner = await make_user()
    subject = await _make_subject(db_session)

    pending = await _course(db_session, owner.id, subject.id)
    await _course(db_session, owner.id, subject.id, moderation_state=ModerationState.approved)
    await _course(db_session, owner.id, subject.id, moderation_state=ModerationState.rejected)

    r = await client.get("/api/v1/admin/courses/moderation-queue", headers=admin)
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()]
    assert pending.id in ids
    # Only pending_review (the approved/rejected courses are excluded).
    assert len(ids) == 1
    # Owner/subject are loaded on the DTO (no N+1 — eager-loaded shape).
    item = r.json()[0]
    assert item["owner"]["id"] == owner.id
    assert item["subject"]["id"] == subject.id


# ---------------------------------------------------------------------------
# Action endpoints — auth gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_actions_require_admin(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
):
    owner = await make_user()
    subject = await _make_subject(db_session)
    course = await _course(db_session, owner.id, subject.id)

    # Non-admin user → 403.
    user_headers = await auth_headers(role=Role.user)
    r = await client.post(
        f"/api/v1/admin/courses/{course.id}/approve", json={}, headers=user_headers
    )
    assert r.status_code == 403

    # Anonymous → 401 (clear the login cookie the prior request set on client).
    client.cookies.clear()
    r2 = await client.post(f"/api/v1/admin/courses/{course.id}/approve", json={})
    assert r2.status_code == 401


@pytest.mark.asyncio
async def test_admin_approve_endpoint_lists(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
):
    admin = await auth_headers(role=Role.admin)
    owner = await make_user()
    subject = await _make_subject(db_session)
    course = await _course(db_session, owner.id, subject.id)

    r = await client.post(f"/api/v1/admin/courses/{course.id}/approve", json={}, headers=admin)
    assert r.status_code == 200, r.text
    await db_session.refresh(course)
    assert str(course.moderation_state) == "approved"


# ---------------------------------------------------------------------------
# Report resolution — atomic single linked audit
# ---------------------------------------------------------------------------


async def _open_report(db, course, reporter) -> CourseReport:
    rep = CourseReport(
        course_id=course.id,
        reporter_id=reporter.id,
        reason="spam",
        note="spammy",
        status=ReportStatus.open,
    )
    db.add(rep)
    await db.commit()
    await db.refresh(rep)
    return rep


@pytest.mark.asyncio
async def test_resolve_delist_is_atomic_single_audit(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
):
    admin = await auth_headers(role=Role.admin)
    owner = await make_user()
    reporter = await _eligible_reporter(make_user, db_session)
    subject = await _make_subject(db_session)
    course = await _course(
        db_session, owner.id, subject.id, moderation_state=ModerationState.approved
    )
    report = await _open_report(db_session, course, reporter)

    r = await client.post(
        f"/api/v1/admin/reports/{report.id}/resolve",
        json={"action": "delist", "reason": "spam"},
        headers=admin,
    )
    assert r.status_code == 200, r.text

    await db_session.refresh(report)
    await db_session.refresh(course)
    assert str(report.status) == "actioned"
    assert report.resolved_by is not None
    assert report.resolved_at is not None
    assert str(course.moderation_state) == "delisted"

    # One report_resolved audit + the delist audit, same transaction.
    resolved_audits = (
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "admin.course.report_resolved",
                    AuditEvent.target_id == report.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(resolved_audits) == 1
    delist_audits = (
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "admin.course.delist",
                    AuditEvent.target_id == course.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(delist_audits) == 1


@pytest.mark.asyncio
async def test_resolve_remove_revokes(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
):
    admin = await auth_headers(role=Role.admin)
    owner = await make_user()
    reporter = await _eligible_reporter(make_user, db_session)
    subject = await _make_subject(db_session)
    course = await _course(
        db_session, owner.id, subject.id, moderation_state=ModerationState.approved
    )
    report = await _open_report(db_session, course, reporter)

    r = await client.post(
        f"/api/v1/admin/reports/{report.id}/resolve",
        json={"action": "remove", "reason": "severe_abuse"},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    await db_session.refresh(course)
    await db_session.refresh(report)
    assert course.deleted_at is not None  # soft-deleted (delegates to remove_course)
    assert str(report.status) == "actioned"


@pytest.mark.asyncio
async def test_resolve_dismiss_no_action(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
):
    admin = await auth_headers(role=Role.admin)
    owner = await make_user()
    reporter = await _eligible_reporter(make_user, db_session)
    subject = await _make_subject(db_session)
    course = await _course(
        db_session, owner.id, subject.id, moderation_state=ModerationState.approved
    )
    report = await _open_report(db_session, course, reporter)

    r = await client.post(
        f"/api/v1/admin/reports/{report.id}/resolve",
        json={"action": "dismiss"},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    await db_session.refresh(report)
    await db_session.refresh(course)
    assert str(report.status) == "dismissed"
    # No moderation action — course unchanged.
    assert str(course.moderation_state) == "approved"
    assert course.deleted_at is None


@pytest.mark.asyncio
async def test_resolve_dismissed_report_cannot_be_re_resolved(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
):
    """F4 (S6 gate): a DISMISSED report cannot be re-resolved with 'remove'.

    Without the status guard the second resolve fires a fresh course removal —
    a destructive replay. The re-resolve is refused 409 report.already_resolved
    and the course is NOT removed."""
    admin = await auth_headers(role=Role.admin)
    owner = await make_user()
    reporter = await _eligible_reporter(make_user, db_session)
    subject = await _make_subject(db_session)
    course = await _course(
        db_session, owner.id, subject.id, moderation_state=ModerationState.approved
    )
    report = await _open_report(db_session, course, reporter)

    # First resolve: dismiss (no course change).
    r1 = await client.post(
        f"/api/v1/admin/reports/{report.id}/resolve",
        json={"action": "dismiss"},
        headers=admin,
    )
    assert r1.status_code == 200, r1.text

    # Second resolve attempt with 'remove' → 409, course untouched.
    r2 = await client.post(
        f"/api/v1/admin/reports/{report.id}/resolve",
        json={"action": "remove", "reason": "severe_abuse"},
        headers=admin,
    )
    assert r2.status_code == 409, r2.text
    assert r2.json()["error"]["code"] == "report.already_resolved"

    await db_session.refresh(report)
    await db_session.refresh(course)
    assert str(report.status) == "dismissed"  # unchanged
    assert course.deleted_at is None  # NOT removed by the replay


@pytest.mark.asyncio
async def test_resolve_actioned_report_cannot_be_re_resolved(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
):
    """F4 (S6 gate): an already-ACTIONED report (resolved via delist) cannot be
    re-resolved with 'remove' — refused 409 report.already_resolved."""
    admin = await auth_headers(role=Role.admin)
    owner = await make_user()
    reporter = await _eligible_reporter(make_user, db_session)
    subject = await _make_subject(db_session)
    course = await _course(
        db_session, owner.id, subject.id, moderation_state=ModerationState.approved
    )
    report = await _open_report(db_session, course, reporter)

    # First resolve: delist → report becomes 'actioned'.
    r1 = await client.post(
        f"/api/v1/admin/reports/{report.id}/resolve",
        json={"action": "delist", "reason": "spam"},
        headers=admin,
    )
    assert r1.status_code == 200, r1.text
    await db_session.refresh(report)
    assert str(report.status) == "actioned"

    # Second resolve attempt with 'remove' → 409, course not soft-deleted.
    r2 = await client.post(
        f"/api/v1/admin/reports/{report.id}/resolve",
        json={"action": "remove", "reason": "illegal"},
        headers=admin,
    )
    assert r2.status_code == 409, r2.text
    assert r2.json()["error"]["code"] == "report.already_resolved"

    await db_session.refresh(course)
    assert course.deleted_at is None  # the replay 'remove' never fired
    assert course.quarantined is False


# ---------------------------------------------------------------------------
# R-S11: approved course accumulating reports requeues, never auto-delists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_action_never_delists_approved(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
):
    """F3 (S6 gate) / R-S11: an APPROVED course accumulating reports past the
    threshold is FLAGGED for admin re-review out-of-band — it STAYS approved,
    STAYS publicly listed, and is NEVER auto-delisted nor auto-requeued to
    pending_review (which would have unlisted it). The flag surfaces in the
    moderation queue with queue_reason='flagged'."""
    from sqlalchemy import select as _select

    from app.core.config import get_settings
    from app.services import visibility as visibility_service

    owner = await make_user()
    subject = await _make_subject(db_session)
    course = await _course(
        db_session, owner.id, subject.id, moderation_state=ModerationState.approved
    )

    threshold = get_settings().report_requeue_threshold
    for _ in range(threshold):
        reporter = await _eligible_reporter(make_user, db_session)
        r = await client.post(
            f"/api/v1/courses/{course.id}/report",
            json={"reason": "spam"},
            headers=await _login(client, reporter),
        )
        assert r.status_code == 201

    await db_session.refresh(course)
    # STAYS approved + public + flagged (NOT requeued, NOT delisted).
    assert str(course.moderation_state) == "approved"
    assert str(course.visibility) == "public"
    assert course.review_flagged_at is not None  # flagged for re-review out-of-band

    # The course STAYS publicly listed — both the pure predicate and the SQL.
    assert visibility_service.is_publicly_listed(course) is True
    listed_ids = (
        (
            await db_session.execute(
                _select(Course.id).where(
                    Course.id == course.id, visibility_service.publicly_listed_sql()
                )
            )
        )
        .scalars()
        .all()
    )
    assert course.id in listed_ids, "a flagged course must REMAIN publicly listed (R-S11)"

    # It appears in the admin moderation queue, marked 'flagged' (not pending).
    admin = await auth_headers(role=Role.admin)
    q = await client.get("/api/v1/admin/courses/moderation-queue", headers=admin)
    assert q.status_code == 200, q.text
    flagged = [row for row in q.json() if row["id"] == course.id]
    assert flagged, "flagged course must appear in the moderation queue"
    assert flagged[0]["queue_reason"] == "flagged"


# ---------------------------------------------------------------------------
# Report listing — inert content + reporter PII admin-only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_content_rendered_inert(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
):
    admin = await auth_headers(role=Role.admin)
    owner = await make_user()
    reporter = await _eligible_reporter(make_user, db_session)
    subject = await _make_subject(db_session)
    course = await _course(
        db_session, owner.id, subject.id, moderation_state=ModerationState.approved
    )

    # File a report with markup in the note via the user endpoint (sanitized).
    rep_resp = await client.post(
        f"/api/v1/courses/{course.id}/report",
        json={"reason": "spam", "note": "<b>bad</b>course"},
        headers=await _login(client, reporter),
    )
    assert rep_resp.status_code == 201

    r = await client.get("/api/v1/admin/reports", headers=admin)
    assert r.status_code == 200
    rows = r.json()
    mine = [x for x in rows if x["course_id"] == course.id]
    assert mine
    # Note is inert (no raw markup) and reporter id is present (admin-only view).
    assert "<b>" not in (mine[0]["note"] or "")
    assert mine[0]["reporter_id"] == reporter.id


@pytest.mark.asyncio
async def test_reports_listing_requires_admin(client: AsyncClient, auth_headers):
    h = await auth_headers(role=Role.user)
    r = await client.get("/api/v1/admin/reports", headers=h)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_reports_listing_orders_by_created_at_and_cursor_pages(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
):
    """F5 (S6 gate): reports list newest-first by created_at (not by random
    nanoid id), and the cursor pages deterministically with a (created_at, id)
    tiebreaker — page 2 picks up exactly where page 1 left off, no overlap, no
    gap."""
    admin = await auth_headers(role=Role.admin)
    owner = await make_user()
    subject = await _make_subject(db_session)
    course = await _course(
        db_session, owner.id, subject.id, moderation_state=ModerationState.approved
    )

    # Three reports with FORCED distinct created_at (oldest → newest), filed by
    # distinct reporters (the open-report coalescing index is per reporter).
    base = datetime.now(UTC) - timedelta(hours=3)
    created = []
    for i in range(3):
        reporter = await _eligible_reporter(make_user, db_session)
        rep = CourseReport(
            course_id=course.id,
            reporter_id=reporter.id,
            reason="spam",
            note=f"r{i}",
            status=ReportStatus.open,
        )
        db_session.add(rep)
        await db_session.commit()
        await db_session.refresh(rep)
        # Force a distinct, strictly increasing created_at.
        rep.created_at = base + timedelta(minutes=i)
        await db_session.commit()
        created.append(rep)

    # Expected newest-first order: r2, r1, r0.
    expected = [created[2].id, created[1].id, created[0].id]

    # Page 1 (limit 2) — newest two.
    p1 = await client.get(
        f"/api/v1/admin/reports?course_id={course.id}&status=open&limit=2", headers=admin
    )
    assert p1.status_code == 200, p1.text
    p1_ids = [x["id"] for x in p1.json()]
    assert p1_ids == expected[:2], f"page 1 must be newest-first, got {p1_ids}"

    # Page 2 — cursor = last id from page 1; must yield exactly the remaining one.
    cursor = p1_ids[-1]
    p2 = await client.get(
        f"/api/v1/admin/reports?course_id={course.id}&status=open&limit=2&cursor={cursor}",
        headers=admin,
    )
    assert p2.status_code == 200, p2.text
    p2_ids = [x["id"] for x in p2.json()]
    assert p2_ids == expected[2:], f"page 2 must continue past the cursor, got {p2_ids}"
    # No overlap between pages, and together they cover all three in order.
    assert p1_ids + p2_ids == expected


@pytest.mark.asyncio
async def test_feature_requires_publicly_listed(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
):
    """S6.4 risk note: set_course_featured must require is_publicly_listed —
    featuring a non-listed (pending) course is a 409 course.not_listed."""
    admin = await auth_headers(role=Role.admin)
    owner = await make_user()
    subject = await _make_subject(db_session)
    pending = await _course(db_session, owner.id, subject.id)  # pending_review, not listed

    r = await client.patch(
        f"/api/v1/admin/courses/{pending.id}/feature",
        json={"is_featured": True},
        headers=admin,
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "course.not_listed"


async def test_approve_reaffirms_flagged_approved_course(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
):
    """Gate-C addendum (F3 follow-up): an admin reviewing a FLAGGED approved
    course and finding it fine re-affirms via approve — the flag clears, the
    state stays approved/listed, and an advisory flag_reaffirmed event is
    written. Approve on an approved-and-UNflagged course still 422s."""
    from datetime import UTC, datetime

    from sqlalchemy import select as _select

    from app.models.moderation import ModerationEvent

    admin_h = await auth_headers(role=Role.admin)
    owner = await make_user(role=Role.user)
    subject = await _make_subject(db_session)
    course = await _course(
        db_session, owner.id, subject.id, moderation_state=ModerationState.approved
    )
    course.review_flagged_at = datetime.now(UTC)
    await db_session.commit()

    r = await client.post(f"/api/v1/admin/courses/{course.id}/approve", headers=admin_h, json={})
    assert r.status_code == 200, r.text

    await db_session.refresh(course)
    assert course.review_flagged_at is None
    assert str(course.moderation_state) == "approved"
    events = (
        (
            await db_session.execute(
                _select(ModerationEvent).where(ModerationEvent.course_id == course.id)
            )
        )
        .scalars()
        .all()
    )
    assert any(e.reason_code is None and e.from_state == e.to_state == "approved" for e in events)

    # Unflagged approved course: approve remains an invalid transition.
    r = await client.post(f"/api/v1/admin/courses/{course.id}/approve", headers=admin_h, json={})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "course.invalid_transition"


async def test_dismissing_last_open_report_clears_flag(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
):
    """Gate-C addendum (F3 follow-up): dismissing the LAST open report removes
    the accumulation signal's basis — the re-review flag clears so the course
    doesn't sit in the moderation queue forever."""
    from datetime import UTC, datetime

    from app.models.moderation import CourseReport, ReportStatus

    admin_h = await auth_headers(role=Role.admin)
    owner = await make_user(role=Role.user)
    reporter = await make_user(role=Role.user)
    subject = await _make_subject(db_session)
    course = await _course(
        db_session, owner.id, subject.id, moderation_state=ModerationState.approved
    )
    course.review_flagged_at = datetime.now(UTC)
    report = CourseReport(
        course_id=course.id,
        reporter_id=reporter.id,
        reason="spam",
        note="addendum probe",
        status=ReportStatus.open.value,
    )
    db_session.add(report)
    await db_session.commit()

    r = await client.post(
        f"/api/v1/admin/reports/{report.id}/resolve",
        headers=admin_h,
        json={"action": "dismiss"},
    )
    assert r.status_code == 200, r.text

    await db_session.refresh(course)
    assert course.review_flagged_at is None  # signal basis gone -> flag cleared
