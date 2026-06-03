"""S6.3 — course_reports + POST /courses/{id}/report (DR-20 account-age gating).

DB-backed (runs under ``make test.api``). Covers reportable-only-when-publicly-
listed (existence-hide 404), self-report forbidden (422), DR-20 reporter
eligibility (email-verified AND account-age ≥ threshold → 403 otherwise),
open-report coalescing (partial-unique), per-course brigading rate limit (429),
and the ``course.report`` audit.

The per-user ≤10/h ``@limiter`` cap is exercised separately by the limiter
suite; here we drive the per-course cap and the eligibility gate directly.
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


async def _login(client: AsyncClient, user) -> dict[str, str]:
    """Auth headers for a specific user (make_user default password)."""
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "Password!1234"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _make_subject(db: AsyncSession):
    from app.models.course import Subject

    s = Subject(title="S", slug=f"s-{uuid.uuid4().hex[:8]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _listed_course(db: AsyncSession, owner_id: str, subject_id: str) -> Course:
    """A publicly-listed (public+published+approved+live) reportable course."""
    c = Course(
        owner_id=owner_id,
        subject_id=subject_id,
        title=f"C {uuid.uuid4().hex[:6]}",
        slug=f"c-{uuid.uuid4().hex[:8]}",
        overview="o",
        status=CourseStatus.published,
        visibility=Visibility.public,
        moderation_state=ModerationState.approved,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def _eligible_reporter(make_user, db: AsyncSession):
    """A verified, sufficiently-aged reporter (DR-20 passes)."""
    from app.models.user import Role

    user = await make_user(role=Role.user)
    user.email_verified_at = datetime.now(UTC)
    user.created_at = datetime.now(UTC) - timedelta(days=30)
    await db.commit()
    return user


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_requires_publicly_listed(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
):
    """A private/own/nonexistent course → 404 (existence-hide, FR-MOD-11)."""
    reporter = await _eligible_reporter(make_user, db_session)
    headers = await _login(client, reporter)
    owner = await make_user()
    subject = await _make_subject(db_session)

    # Private (not listed) course → 404.
    private = Course(
        owner_id=owner.id,
        subject_id=subject.id,
        title="priv",
        slug=f"priv-{uuid.uuid4().hex[:8]}",
        overview="o",
        status=CourseStatus.draft,
        visibility=Visibility.private,
        moderation_state=ModerationState.none,
    )
    db_session.add(private)
    await db_session.commit()

    r = await client.post(
        f"/api/v1/courses/{private.id}/report",
        json={"reason": "spam"},
        headers=headers,
    )
    assert r.status_code == 404

    # Nonexistent course → 404.
    r2 = await client.post(
        "/api/v1/courses/does-not-exist/report",
        json={"reason": "spam"},
        headers=headers,
    )
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_report_self_forbidden(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
):
    """Owner reports own listed course → 422 report.own_course."""
    owner = await _eligible_reporter(make_user, db_session)
    headers = await _login(client, owner)
    subject = await _make_subject(db_session)
    course = await _listed_course(db_session, owner.id, subject.id)

    r = await client.post(
        f"/api/v1/courses/{course.id}/report",
        json={"reason": "spam"},
        headers=headers,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "report.own_course"


@pytest.mark.asyncio
async def test_report_account_age_gate(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
):
    """DR-20: unverified OR too-young reporter → 403 report.ineligible; an
    eligible (verified + ≥3d old) reporter → 201."""
    from app.models.user import Role

    owner = await make_user()
    subject = await _make_subject(db_session)
    course = await _listed_course(db_session, owner.id, subject.id)

    # Too-young account (created just now) → 403.
    young = await make_user(role=Role.user)
    young.email_verified_at = datetime.now(UTC)
    young.created_at = datetime.now(UTC)
    await db_session.commit()
    r = await client.post(
        f"/api/v1/courses/{course.id}/report",
        json={"reason": "spam"},
        headers=await _login(client, young),
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "report.ineligible"

    # Unverified email (old enough) → 403.
    unverified = await make_user(role=Role.user)
    unverified.email_verified_at = None
    unverified.created_at = datetime.now(UTC) - timedelta(days=30)
    await db_session.commit()
    r2 = await client.post(
        f"/api/v1/courses/{course.id}/report",
        json={"reason": "spam"},
        headers=await _login(client, unverified),
    )
    assert r2.status_code == 403
    assert r2.json()["error"]["code"] == "report.ineligible"

    # Eligible reporter → 201.
    good = await _eligible_reporter(make_user, db_session)
    r3 = await client.post(
        f"/api/v1/courses/{course.id}/report",
        json={"reason": "spam", "note": "looks like spam"},
        headers=await _login(client, good),
    )
    assert r3.status_code == 201


@pytest.mark.asyncio
async def test_report_coalesces_open(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
):
    """Same user reports same course twice → one open row; second updates note."""
    owner = await make_user()
    subject = await _make_subject(db_session)
    course = await _listed_course(db_session, owner.id, subject.id)
    reporter = await _eligible_reporter(make_user, db_session)
    headers = await _login(client, reporter)

    r1 = await client.post(
        f"/api/v1/courses/{course.id}/report",
        json={"reason": "spam", "note": "first note"},
        headers=headers,
    )
    assert r1.status_code == 201
    r2 = await client.post(
        f"/api/v1/courses/{course.id}/report",
        json={"reason": "abuse", "note": "second note"},
        headers=headers,
    )
    assert r2.status_code == 201

    rows = (
        (
            await db_session.execute(
                select(CourseReport).where(
                    CourseReport.course_id == course.id,
                    CourseReport.reporter_id == reporter.id,
                    CourseReport.status == ReportStatus.open,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].note == "second note"


@pytest.mark.asyncio
async def test_report_rate_limited_per_course(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
):
    """More than report_per_course_window_max distinct reports on a single
    course in the window → 429 course.report_rate_limited (brigading cap)."""
    from app.core.config import get_settings

    owner = await make_user()
    subject = await _make_subject(db_session)
    course = await _listed_course(db_session, owner.id, subject.id)
    cap = get_settings().report_per_course_window_max

    # File `cap` distinct reports from distinct eligible reporters.
    for _ in range(cap):
        reporter = await _eligible_reporter(make_user, db_session)
        r = await client.post(
            f"/api/v1/courses/{course.id}/report",
            json={"reason": "spam"},
            headers=await _login(client, reporter),
        )
        assert r.status_code == 201

    # The (cap+1)-th distinct reporter trips the per-course cap.
    over = await _eligible_reporter(make_user, db_session)
    r_over = await client.post(
        f"/api/v1/courses/{course.id}/report",
        json={"reason": "spam"},
        headers=await _login(client, over),
    )
    assert r_over.status_code == 429
    assert r_over.json()["error"]["code"] == "course.report_rate_limited"


@pytest.mark.asyncio
async def test_report_writes_audit_and_sanitizes(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
):
    """A successful report writes a course.report audit (actor=reporter) and the
    note is sanitized before persist (FR-MOD-13)."""
    owner = await make_user()
    subject = await _make_subject(db_session)
    course = await _listed_course(db_session, owner.id, subject.id)
    reporter = await _eligible_reporter(make_user, db_session)

    r = await client.post(
        f"/api/v1/courses/{course.id}/report",
        json={"reason": "spam", "note": "<script>x</script>nasty"},
        headers=await _login(client, reporter),
    )
    assert r.status_code == 201

    audits = (
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "course.report",
                    AuditEvent.target_id == course.id,
                    AuditEvent.actor_id == reporter.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert audits

    row = (
        (
            await db_session.execute(
                select(CourseReport).where(
                    CourseReport.course_id == course.id,
                    CourseReport.reporter_id == reporter.id,
                )
            )
        )
        .scalars()
        .one()
    )
    assert "<script>" not in (row.note or "")
