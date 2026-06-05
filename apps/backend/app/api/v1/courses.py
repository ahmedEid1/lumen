"""Course / module / lesson endpoints."""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime

from fastapi import APIRouter, Header, Request, Response, status
from pydantic import BaseModel, ConfigDict
from starlette.responses import Response as StarletteResponse

from app.api.deps import (
    CurrentUser,
    DBSession,
    OptionalUser,
    RequireAuthor,
    RequireClone,
    client_ip,
    user_agent,
)
from app.api.v1 import _builders
from app.core.errors import ForbiddenError, NotFoundError, UnauthorizedError
from app.core.ratelimit import limiter
from app.models.course import Course
from app.models.user import User
from app.repositories import courses as courses_repo
from app.schemas.common import OkResponse
from app.schemas.course import (
    CourseCreate,
    CourseDetail,
    CourseListItem,
    CourseUpdate,
    LessonCreate,
    LessonOut,
    LessonUpdate,
    ModuleCreate,
    ModuleOut,
    ModuleUpdate,
    OrderUpdateRequest,
    ReportRequest,
)
from app.services import analytics as analytics_service
from app.services import courses as courses_service
from app.services import enrollment as enrollment_service
from app.services import moderation as moderation_service
from app.services import visibility as visibility_service

router = APIRouter()


# Auth-aware Cache-Control values used by the course-detail ETag flow.
# Anonymous reads can be short-cached publicly; authed reads carry
# per-viewer fields and must stay private.
_CACHE_PRIVATE = "private, max-age=0, must-revalidate"
_CACHE_PUBLIC_60 = "public, max-age=60, must-revalidate"
_VARY_AUTH = "Accept-Encoding, Authorization, Cookie"


async def _load_course_with_stats(db: DBSession, course_id: str) -> tuple[Course, dict]:
    """Refresh + 404 + stats — the trio every write-then-render endpoint needs."""
    course = await courses_repo.get_course(db, course_id)
    if course is None:
        raise NotFoundError("Course not found", code="course.not_found")
    stats = (await courses_repo.stats_for_courses(db, [course.id])).get(course.id, {})
    return course, stats


def _course_detail_etag(
    course: Course,
    stats: dict,
    *,
    is_enrolled: bool,
    pct: float,
    done_count: int,
) -> str:
    """Weak ETag covering the per-viewer detail body."""
    fingerprint = "|".join(
        [
            course.id,
            course.updated_at.isoformat() if course.updated_at else "",
            # S2.12: fold the visibility/moderation/status axes into the ETag so
            # a share/approve/delist/unpublish forces a cache revalidation even
            # if updated_at granularity is coarse.
            str(course.status),
            str(course.visibility),
            str(course.moderation_state),
            "q1" if getattr(course, "quarantined", False) else "q0",
            "1" if is_enrolled else "0",
            f"{pct:.1f}",
            str(done_count),
            str(stats.get("modules_count", 0)),
            str(stats.get("enrollments_count", 0)),
            f"{stats.get('avg_rating') or 0:.2f}",
        ]
    )
    return 'W/"' + hashlib.sha256(fingerprint.encode()).hexdigest()[:32] + '"'


# ---------- Course CRUD ----------


@router.post("", response_model=CourseListItem, status_code=status.HTTP_201_CREATED)
async def create_course(
    payload: CourseCreate, user: RequireAuthor, db: DBSession
) -> CourseListItem:
    course = await courses_service.create_course(db, user, payload)
    refreshed, stats = await _load_course_with_stats(db, course.id)
    return _builders.list_item(refreshed, stats)


@router.get("/mine", response_model=list[CourseListItem])
async def my_courses(user: RequireAuthor, db: DBSession) -> list[CourseListItem]:
    courses, _ = await courses_repo.search_courses(
        db, owner_id=user.id, publicly_listed_only=False, page=1, page_size=100
    )
    stats = await courses_repo.stats_for_courses(db, [c.id for c in courses])
    # Owner-scoped listing — pass the viewer so moderation_state is visible.
    return [_builders.list_item(c, stats.get(c.id, {}), viewer=user) for c in courses]


@router.get("/{key}", response_model=CourseDetail)
async def get_course(
    key: str,
    viewer: OptionalUser,
    db: DBSession,
    request: Request,
    response: Response,
) -> CourseDetail:
    course = await courses_service.slug_or_id(db, key, with_modules=True)
    if not await courses_service.can_view_course(db, course, viewer):
        raise NotFoundError("Course not found", code="course.not_found")

    stats = (await courses_repo.stats_for_courses(db, [course.id])).get(course.id, {})
    is_enrolled = False
    pct = 0.0
    done: set[str] = set()
    if viewer:
        enrollment = await courses_repo.get_enrollment(db, user_id=viewer.id, course_id=course.id)
        if enrollment:
            is_enrolled = True
            pct = await enrollment_service.progress_pct(db, enrollment=enrollment)
            done = await courses_repo.completed_lesson_ids(db, enrollment.id)

    # Weak ETag covering everything that goes into the response body:
    # the course row's update timestamp + the viewer-derived flags.
    # Re-render-on-mismatch is short (in microseconds), and the
    # If-None-Match shortcut saves a few KB of JSON per repeat hit —
    # huge cumulative win for clients (mobile, returning learner)
    # that poll the detail page.
    etag = _course_detail_etag(
        course,
        stats,
        is_enrolled=is_enrolled,
        pct=pct,
        done_count=len(done),
    )
    if_none_match = request.headers.get("if-none-match", "")
    # Auth-aware caching headers. The body carries per-viewer fields
    # (is_enrolled, completed lessons) so:
    #   * authenticated  → private cache only; no CDN, no shared proxy
    #   * anonymous      → short public cache, must-revalidate against ETag
    # Vary makes the difference explicit so a CDN cannot serve a
    # cached anonymous body to an authenticated request with the same
    # URL (or vice versa).
    cache_control = _CACHE_PRIVATE if viewer is not None else _CACHE_PUBLIC_60
    response.headers["Cache-Control"] = cache_control
    response.headers["Vary"] = _VARY_AUTH
    if if_none_match == etag:
        # Status 304 forbids a body. `HTTPException(304)` would
        # render as a JSON error envelope — non-empty, violating
        # both the cache-revalidation tests and (technically)
        # RFC 9110. Return a bare starlette Response so the body
        # is the empty bytestring. The Cache-Control / Vary headers
        # set on ``response`` above also don't survive a raise,
        # so we re-emit them on the 304 here.
        return StarletteResponse(
            status_code=304,
            headers={
                "ETag": etag,
                "Cache-Control": cache_control,
                "Vary": _VARY_AUTH,
            },
        )
    response.headers["ETag"] = etag

    origin = await courses_service.resolve_origin(db, course)
    return _builders.detail(
        course,
        list(course.modules),
        stats,
        is_enrolled=is_enrolled,
        progress_pct=pct,
        completed_lesson_ids=done,
        viewer=viewer,
        origin=origin,
    )


@router.patch("/{course_id}", response_model=CourseDetail)
async def update_course(
    course_id: str, payload: CourseUpdate, user: RequireAuthor, db: DBSession
) -> CourseDetail:
    await courses_service.update_course(db, course_id=course_id, owner=user, payload=payload)
    course = await courses_repo.get_course(db, course_id, with_modules=True)
    if course is None:
        raise NotFoundError("Course not found", code="course.not_found")
    stats = (await courses_repo.stats_for_courses(db, [course.id])).get(course.id, {})
    pct = 0.0
    is_enrolled = False
    enrollment = await courses_repo.get_enrollment(db, user_id=user.id, course_id=course.id)
    if enrollment:
        is_enrolled = True
        pct = await enrollment_service.progress_pct(db, enrollment=enrollment)
    return _builders.detail(
        course,
        list(course.modules),
        stats,
        is_enrolled=is_enrolled,
        progress_pct=pct,
        viewer=user,
    )


@router.delete("/{course_id}", response_model=OkResponse, status_code=status.HTTP_200_OK)
async def delete_course(course_id: str, user: RequireAuthor, db: DBSession) -> OkResponse:
    await courses_service.delete_course(db, course_id=course_id, owner=user)
    return OkResponse()


# ---------- Lifecycle + share endpoints (S2.11 / ADR-0026) ----------
#
# Replace PATCH-as-publish (FR-VIS-08). The owner check + can_publish_public
# live INSIDE the service (_owned_course), so these are correct regardless of
# the route-level guard — S1 collapsed roles and authoring is now gated by the
# `RequireAuthor` capability (any active user), not by an instructor role.


async def _render_detail(db: DBSession, course_id: str, user: User) -> CourseDetail:
    course = await courses_repo.get_course(db, course_id, with_modules=True)
    if course is None:
        raise NotFoundError("Course not found", code="course.not_found")
    stats = (await courses_repo.stats_for_courses(db, [course.id])).get(course.id, {})
    pct = 0.0
    is_enrolled = False
    enrollment = await courses_repo.get_enrollment(db, user_id=user.id, course_id=course.id)
    if enrollment:
        is_enrolled = True
        pct = await enrollment_service.progress_pct(db, enrollment=enrollment)
    return _builders.detail(
        course,
        list(course.modules),
        stats,
        is_enrolled=is_enrolled,
        progress_pct=pct,
        viewer=user,
    )


def _require_private_publish_enabled() -> None:
    """R-S8′ step-4 gate: the sharing axis is OFF until the flag flips."""
    from app.core.config import get_settings

    if not get_settings().feature_private_publish_enabled:
        # Existence-hide the sharing surface while disabled (no leak window).
        raise NotFoundError("Not found", code="course.not_found")


@router.post("/{course_id}/publish", response_model=CourseDetail)
async def publish_course(course_id: str, user: RequireAuthor, db: DBSession) -> CourseDetail:
    await courses_service.publish_course(db, course_id=course_id, owner=user)
    return await _render_detail(db, course_id, user)


@router.post("/{course_id}/unpublish", response_model=CourseDetail)
async def unpublish_course(course_id: str, user: RequireAuthor, db: DBSession) -> CourseDetail:
    await courses_service.unpublish_course(db, course_id=course_id, owner=user)
    return await _render_detail(db, course_id, user)


@router.post("/{course_id}/archive", response_model=CourseDetail)
async def archive_course(course_id: str, user: RequireAuthor, db: DBSession) -> CourseDetail:
    # Lifecycle, not sharing — NO feature flag (archive force-privates +
    # unfeatures regardless of the sharing-axis rollout state, ADR-0026 §4).
    await courses_service.archive_course(db, course_id=course_id, owner=user)
    return await _render_detail(db, course_id, user)


@router.post("/{course_id}/restore", response_model=CourseDetail)
async def restore_course(course_id: str, user: RequireAuthor, db: DBSession) -> CourseDetail:
    await courses_service.restore_course(db, course_id=course_id, owner=user)
    return await _render_detail(db, course_id, user)


@router.post("/{course_id}/share", response_model=CourseDetail)
async def share_course(course_id: str, user: RequireAuthor, db: DBSession) -> CourseDetail:
    _require_private_publish_enabled()
    await courses_service.share_course(db, course_id=course_id, owner=user)
    return await _render_detail(db, course_id, user)


@router.post("/{course_id}/unshare", response_model=CourseDetail)
async def unshare_course(course_id: str, user: RequireAuthor, db: DBSession) -> CourseDetail:
    _require_private_publish_enabled()
    await courses_service.unshare_course(db, course_id=course_id, owner=user)
    return await _render_detail(db, course_id, user)


@router.post("/{course_id}/resubmit", response_model=CourseDetail)
async def resubmit_course(course_id: str, user: RequireAuthor, db: DBSession) -> CourseDetail:
    _require_private_publish_enabled()
    await courses_service.resubmit_course(db, course_id=course_id, owner=user)
    return await _render_detail(db, course_id, user)


@router.post("/{course_id}/report", response_model=OkResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/hour")
async def report_course(
    course_id: str,
    payload: ReportRequest,
    user: CurrentUser,
    db: DBSession,
    request: Request,
    response: Response,
) -> OkResponse:
    """File a report against a publicly-listed course (FR-MOD-11 / S6.3).

    Any authenticated user may report (not just authors). The ≤10/h per-user
    cap is the ``@limiter`` decorator; DR-20 reporter eligibility (verified +
    aged) and the per-course brigading cap live in the service. A non-listed /
    own / nonexistent course returns 404/422 with no row written (existence-hide
    FR-MOD-11). ``request``/``response`` are required by slowapi's
    ``@limiter.limit`` (Request for keying, Response for the rate-limit headers).
    """
    course = await courses_repo.get_course(db, course_id)
    if not course:
        # Existence-hide: indistinguishable from a non-listed course (the
        # service raises the same 404 for a loaded-but-not-listed course).
        raise NotFoundError("Course not found", code="course.not_found")
    await moderation_service.report_course(
        db,
        course=course,
        reporter=user,
        reason=payload.reason,
        note=payload.note,
        ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return OkResponse()


# ---------- Clone / remix (ADR-0028 §API; S4.6/S4.7) ----------


def _require_clone_enabled() -> None:
    """Flag gate: the clone surface is OFF until ``CLONE_ENABLED`` flips.

    Existence-hide while disabled (404 ``clone.disabled``, no feature-probe) —
    same lesson as the sharing-axis gate and the BYOK gate (ADR-0028 §Migrations).
    """
    from app.core.config import get_settings

    if not get_settings().clone_enabled:
        raise NotFoundError("Not found", code="clone.disabled")


@router.post(
    "/{key}/clone",
    response_model=CourseListItem,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("20/hour")
async def clone_course(
    key: str,
    user: RequireClone,
    db: DBSession,
    request: Request,
    response: Response,
    source_updated_at: datetime | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> CourseListItem:
    """Clone a publicly-listed course into a fresh private draft (FR-CLONE-01).

    Resolve + authorize (``is_publicly_listed`` with the 403-vs-404 existence-hide
    split), idempotency replay (``Idempotency-Key``), optional ``source_updated_at``
    precondition, non-dollar quotas, projection + atomic materialization with
    server-written immutable provenance, owner self-enroll, audit + origin
    notification. Returns 201 + a ``Location`` header pointing at the new course;
    the body is a ``CourseListItem`` with structured ``origin``. The slowapi cap
    is the fast first line; the durable DB-COUNT window backstop lives in the
    service. ``request``/``response`` are required by slowapi's ``@limiter.limit``.
    """
    _require_clone_enabled()
    # ``clone_course`` returns ``(course, replayed)`` and itself registers the
    # lazy asset-rehoming enqueue on the request session's ``after_commit`` hook
    # ONLY for a fresh materialization (S4 gate Codex-C1 / Gate-B B1 — the
    # ADR-0019 gotcha: enqueuing inline here would fire BEFORE get_db()'s commit
    # and race the worker against an uncommitted row; an Idempotency-Key replay
    # must not re-fire it either, or the worker re-homes already-owned assets →
    # duplicate Asset rows + S3 objects).
    new_course, _replayed = await courses_service.clone_course(
        db,
        caller=user,
        source_key=key,
        ip=client_ip(request),
        user_agent=user_agent(request),
        source_updated_at=source_updated_at,
        idempotency_key=idempotency_key,
    )
    refreshed, stats = await _load_course_with_stats(db, new_course.id)
    origin = await courses_service.resolve_origin(db, refreshed)
    response.headers["Location"] = f"/api/v1/courses/{new_course.id}"
    return _builders.list_item(refreshed, stats, viewer=user, origin=origin)


# ---------- Modules ----------


@router.post("/{course_id}/modules", response_model=ModuleOut, status_code=status.HTTP_201_CREATED)
async def create_module(
    course_id: str, payload: ModuleCreate, user: RequireAuthor, db: DBSession
) -> ModuleOut:
    mod = await courses_service.create_module(db, course_id=course_id, owner=user, payload=payload)
    return ModuleOut(
        id=mod.id, title=mod.title, description=mod.description, order=mod.order, lessons=[]
    )


@router.patch("/modules/{module_id}", response_model=ModuleOut)
async def update_module(
    module_id: str, payload: ModuleUpdate, user: RequireAuthor, db: DBSession
) -> ModuleOut:
    mod = await courses_service.update_module(db, module_id=module_id, owner=user, payload=payload)
    return ModuleOut(
        id=mod.id,
        title=mod.title,
        description=mod.description,
        order=mod.order,
        lessons=[
            LessonOut.model_validate(lesson) for lesson in mod.lessons if lesson.deleted_at is None
        ],
    )


@router.delete("/modules/{module_id}", response_model=OkResponse)
async def delete_module(module_id: str, user: RequireAuthor, db: DBSession) -> OkResponse:
    await courses_service.delete_module(db, module_id=module_id, owner=user)
    return OkResponse()


@router.post("/{course_id}/modules/order", response_model=OkResponse)
async def reorder_modules(
    course_id: str, payload: OrderUpdateRequest, user: RequireAuthor, db: DBSession
) -> OkResponse:
    await courses_service.reorder_modules(
        db, course_id=course_id, owner=user, mapping=payload.order
    )
    return OkResponse()


# ---------- Lessons ----------


@router.post(
    "/modules/{module_id}/lessons", response_model=LessonOut, status_code=status.HTTP_201_CREATED
)
async def create_lesson(
    module_id: str, payload: LessonCreate, user: RequireAuthor, db: DBSession
) -> LessonOut:
    lesson = await courses_service.create_lesson(
        db, module_id=module_id, owner=user, payload=payload
    )
    return LessonOut.model_validate(lesson)


@router.patch("/lessons/{lesson_id}", response_model=LessonOut)
async def update_lesson(
    lesson_id: str, payload: LessonUpdate, user: RequireAuthor, db: DBSession
) -> LessonOut:
    lesson = await courses_service.update_lesson(
        db, lesson_id=lesson_id, owner=user, payload=payload
    )
    return LessonOut.model_validate(lesson)


@router.delete("/lessons/{lesson_id}", response_model=OkResponse)
async def delete_lesson(lesson_id: str, user: RequireAuthor, db: DBSession) -> OkResponse:
    await courses_service.delete_lesson(db, lesson_id=lesson_id, owner=user)
    return OkResponse()


@router.post("/modules/{module_id}/lessons/order", response_model=OkResponse)
async def reorder_lessons(
    module_id: str, payload: OrderUpdateRequest, user: RequireAuthor, db: DBSession
) -> OkResponse:
    await courses_service.reorder_lessons(
        db, module_id=module_id, owner=user, mapping=payload.order
    )
    return OkResponse()


@router.get("/lessons/{lesson_id}", response_model=LessonOut)
async def get_lesson(lesson_id: str, viewer: OptionalUser, db: DBSession) -> LessonOut:
    """Fetch a lesson for playback.

    Allowed when the viewer is enrolled, the course owner, an admin, or when
    the lesson is flagged ``is_preview`` (free preview) and the course is
    published.
    """
    lesson = await courses_repo.get_lesson(db, lesson_id)
    if lesson is None or lesson.deleted_at is not None:
        raise NotFoundError("Lesson not found", code="lesson.not_found")
    mod = await courses_repo.get_module(db, lesson.module_id)
    course = await courses_repo.get_course(db, mod.course_id) if mod else None
    if course is None:
        raise NotFoundError("Course not found", code="course.not_found")

    # A free-preview lesson is anonymously readable only when the course is
    # publicly LISTED (not merely published) — a published-private course's
    # preview must not leak to strangers (S2.4 / ADR-0026 §3). Route through
    # the central authorizer instead of the raw status string.
    if lesson.is_preview and visibility_service.is_publicly_listed(course):
        return LessonOut.model_validate(lesson)
    if viewer is None:
        raise UnauthorizedError("Authentication required", code="auth.required")
    if viewer.is_admin() or course.owner_id == viewer.id:
        return LessonOut.model_validate(lesson)
    enrollment = await courses_repo.get_enrollment(db, user_id=viewer.id, course_id=course.id)
    if not enrollment:
        raise ForbiddenError("Enroll first", code="lesson.enroll_first")
    return LessonOut.model_validate(lesson)


# ---------- Analytics ----------


class CourseAnalyticsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    course_id: str
    enrollments: int
    completions: int
    completion_rate: float
    avg_rating: float | None = None
    rating_count: int
    avg_progress_pct: float
    enrollments_last_7d: int
    enrollments_last_30d: int


@router.get("/{course_id}/analytics", response_model=CourseAnalyticsOut)
async def course_analytics(
    course_id: str, user: RequireAuthor, db: DBSession
) -> CourseAnalyticsOut:
    data = await analytics_service.for_course(db, course_id=course_id, viewer=user)
    return CourseAnalyticsOut.model_validate(data)


# ---------- Cohort ----------


class CohortRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    full_name: str
    avatar_url: str | None = None
    enrolled_at: datetime
    completed_at: datetime | None = None
    progress_pct: float
    certificate_id: str | None = None


@router.get("/{course_id}/students", response_model=list[CohortRowOut])
async def course_cohort(course_id: str, user: RequireAuthor, db: DBSession) -> list[CohortRowOut]:
    rows = await analytics_service.cohort_for_course(db, course_id=course_id, viewer=user)
    return [CohortRowOut.model_validate(r) for r in rows]


@router.get("/{course_id}/students.csv")
async def course_cohort_csv(course_id: str, user: RequireAuthor, db: DBSession) -> Response:
    """Same data the cohort UI shows, dumped as CSV so instructors can
    import into a gradebook / spreadsheet. Reuses the cohort service
    (same authz, same soft-delete handling, same 500-row cap).

    We hand-format CSV rather than pull in a dependency — it's six
    columns of scalars, escaping handled by Python's stdlib ``csv``.
    """
    rows = await analytics_service.cohort_for_course(db, course_id=course_id, viewer=user)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(
        ["user_id", "full_name", "enrolled_at", "completed_at", "progress_pct", "certificate_id"]
    )
    for r in rows:
        writer.writerow(
            [
                r.user_id,
                r.full_name,
                r.enrolled_at.isoformat(),
                r.completed_at.isoformat() if r.completed_at else "",
                f"{r.progress_pct:.1f}",
                r.certificate_id or "",
            ]
        )
    body = buf.getvalue()
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="cohort-{course_id}.csv"',
            # Cohort data changes on every enrollment / completion — no
            # caching downstream.
            "Cache-Control": "private, max-age=0, no-store",
        },
    )
