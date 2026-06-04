"""Admin-only endpoints: subjects, tags, users, audit log."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from slugify import slugify
from sqlalchemy import desc, func, select
from sqlalchemy.orm import selectinload

from app.api.deps import DBSession, RequireAdmin, client_ip, user_agent
from app.api.v1 import _builders
from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.models.audit import AuditEvent
from app.models.course import Course, CourseStatus, Enrollment, Subject, Tag
from app.models.user import Role, User
from app.repositories import audit as audit_repo
from app.repositories import courses as courses_repo
from app.repositories import moderation as moderation_repo
from app.schemas.common import OkResponse
from app.schemas.course import CourseListItem, SubjectOut, TagOut
from app.services import admin_users as admin_users_service
from app.services import moderation as moderation_service
from app.services import visibility as visibility_service
from app.services.moderation_taxonomy import ReasonCode

router = APIRouter()


async def _scalar_count(db: DBSession, stmt) -> int:
    """Run a `select(func.count(...))` and coerce the scalar to int."""
    return int((await db.execute(stmt)).scalar_one())


async def _slug_taken(db: DBSession, model, slug: str) -> bool:
    return (
        await db.execute(select(model.id).where(model.slug == slug))
    ).scalar_one_or_none() is not None


async def _load_user_or_404(db: DBSession, user_id: str) -> User:
    user = await db.get(User, user_id)
    if not user:
        raise NotFoundError("User not found", code="user.not_found")
    return user


# ---------- Subjects ----------


class SubjectIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=140)


@router.post("/subjects", response_model=SubjectOut, status_code=status.HTTP_201_CREATED)
async def create_subject(payload: SubjectIn, _: RequireAdmin, db: DBSession) -> SubjectOut:
    slug = (payload.slug or slugify(payload.title))[:140]
    if not slug:
        raise ValidationAppError("Slug must be non-empty", code="subject.invalid_slug")
    if await _slug_taken(db, Subject, slug):
        raise ConflictError("Subject slug already exists", code="subject.slug_taken")
    s = Subject(title=payload.title, slug=slug)
    db.add(s)
    await db.flush()
    return SubjectOut(id=s.id, title=s.title, slug=s.slug, total_courses=0)


@router.patch("/subjects/{subject_id}", response_model=SubjectOut)
async def update_subject(
    subject_id: str, payload: SubjectIn, _: RequireAdmin, db: DBSession
) -> SubjectOut:
    s = await db.get(Subject, subject_id)
    if not s:
        raise NotFoundError("Subject not found", code="subject.not_found")
    if payload.title:
        s.title = payload.title
    if payload.slug and payload.slug != s.slug:
        if await _slug_taken(db, Subject, payload.slug):
            raise ConflictError("Slug taken", code="subject.slug_taken")
        s.slug = payload.slug
    return SubjectOut.model_validate(s)


@router.delete("/subjects/{subject_id}", response_model=OkResponse)
async def delete_subject(subject_id: str, _: RequireAdmin, db: DBSession) -> OkResponse:
    s = await db.get(Subject, subject_id)
    if not s:
        raise NotFoundError("Subject not found", code="subject.not_found")
    # Course.subject_id is FK ondelete=RESTRICT — the DB refuses the DELETE
    # if any course row (live OR soft-deleted) still references the subject.
    # Count all rows and refuse with a clear 409 the admin can act on,
    # rather than letting it bubble up as an IntegrityError → 500.
    total = await _scalar_count(db, select(func.count(Course.id)).where(Course.subject_id == s.id))
    if total > 0:
        live = await _scalar_count(
            db,
            select(func.count(Course.id)).where(
                Course.subject_id == s.id, Course.deleted_at.is_(None)
            ),
        )
        raise ConflictError(
            "Subject still has courses attached",
            code="subject.in_use",
            details={"courses": live, "courses_including_deleted": total},
        )
    await db.delete(s)
    return OkResponse()


# ---------- Tags ----------


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    slug: str | None = Field(default=None, max_length=80)


@router.post("/tags", response_model=TagOut, status_code=status.HTTP_201_CREATED)
async def create_tag(payload: TagIn, _: RequireAdmin, db: DBSession) -> TagOut:
    slug = (payload.slug or slugify(payload.name))[:80]
    if not slug:
        raise ValidationAppError("Slug must be non-empty", code="tag.invalid_slug")
    if await _slug_taken(db, Tag, slug):
        raise ConflictError("Tag slug taken", code="tag.slug_taken")
    t = Tag(name=payload.name, slug=slug)
    db.add(t)
    await db.flush()
    return TagOut.model_validate(t)


@router.delete("/tags/{tag_id}", response_model=OkResponse)
async def delete_tag(tag_id: str, _: RequireAdmin, db: DBSession) -> OkResponse:
    t = await db.get(Tag, tag_id)
    if not t:
        raise NotFoundError("Tag not found", code="tag.not_found")
    # course_tags has ON DELETE CASCADE, so a raw DELETE silently strips
    # this tag from every course using it — no warning to the admin and
    # no audit trail of which courses were touched. Mirror the
    # subject-delete contract: refuse with a 409 if any *live* course
    # still references the tag. Soft-deleted courses don't block the
    # admin (their join rows cascade away with no user-visible impact).
    live = await _scalar_count(
        db,
        select(func.count(Course.id))
        .join(Course.tags)
        .where(Tag.id == t.id, Course.deleted_at.is_(None)),
    )
    if live > 0:
        raise ConflictError(
            "Tag is still attached to courses",
            code="tag.in_use",
            details={"courses": live},
        )
    await db.delete(t)
    return OkResponse()


# ---------- Users ----------


class UserAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str
    role: Role
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


#: The only roles an admin may *write* once the collapse lands (FR-RBAC-06,
#: FR-ADMIN-07). Legacy ``student``/``instructor`` are read-tolerant (the wide
#: enum still loads them) but write-forbidden.
SETTABLE_ROLES: frozenset[Role] = frozenset({Role.user, Role.admin})
#: Legacy roles the ``/role`` endpoint *normalizes* to ``user`` during the
#: migration window (S6.6 / FR-ADMIN-02): a stale ``instructor``/``student``
#: write is applied as ``user`` (audited as ``{requested, applied}``) so old
#: clients don't 422 mid-rollout. After Phase D (or under the strict flag) they
#: are rejected with ``user.invalid_role``.
NORMALIZABLE_ROLES: frozenset[Role] = frozenset({Role.student, Role.instructor})


class UserRoleUpdate(BaseModel):
    # S6.6: accept ANY enum value at parse so the legacy ``student``/
    # ``instructor`` write can be *normalized* (not rejected) during the
    # migration window. The settable/normalize/422 policy is applied in the
    # handler, not the validator (FR-ADMIN-02).
    role: Role


class AdminToggleUpdate(BaseModel):
    """S6.6 — the grant/revoke-admin toggle body (FR-ADMIN-01)."""

    model_config = ConfigDict(extra="forbid")

    is_admin: bool


class SuspendUpdate(BaseModel):
    """S6.7 — the suspend body (FR-SUSP-01/03)."""

    model_config = ConfigDict(extra="forbid")

    reason: ReasonCode
    note: str | None = Field(default=None, max_length=5000)


class UserActiveUpdate(BaseModel):
    is_active: bool


@router.get("/users", response_model=list[UserAdminOut])
async def list_users(
    _: RequireAdmin,
    db: DBSession,
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[UserAdminOut]:
    stmt = select(User).order_by(desc(User.created_at)).limit(limit)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((User.email.ilike(like)) | (User.full_name.ilike(like)))
    rows = (await db.execute(stmt)).scalars().all()
    return [UserAdminOut.model_validate(u) for u in rows]


@router.patch("/users/{user_id}/role", response_model=UserAdminOut)
async def set_user_role(
    user_id: str, payload: UserRoleUpdate, admin: RequireAdmin, db: DBSession
) -> UserAdminOut:
    """LEGACY role write (FR-ADMIN-02) — superseded by ``/admin`` (S6.6).

    During the migration window a stale ``student``/``instructor`` value is
    NORMALIZED to ``user`` (applied + audited as ``{requested, applied}``) so
    old clients don't 422 mid-rollout. After Phase D (``strict_legacy_role_
    rejection``) a legacy value is rejected with ``user.invalid_role``. The
    last-admin invariant guards a self/last-admin demote (subsumes the old
    self-demote guard).
    """
    user = await _load_user_or_404(db, user_id)
    requested = payload.role
    applied = requested

    if requested in NORMALIZABLE_ROLES:
        if get_settings().strict_legacy_role_rejection:
            raise ValidationAppError("Role must be 'user' or 'admin'", code="user.invalid_role")
        # Migration-window tolerance: normalize legacy → user.
        applied = Role.user
    elif requested not in SETTABLE_ROLES:
        raise ValidationAppError("Role must be 'user' or 'admin'", code="user.invalid_role")

    # Demoting an admin (self or the last other admin) routes through the
    # authoritative last-admin invariant (subsumes the old self-demote guard).
    if user.role == Role.admin and applied != Role.admin:
        await admin_users_service.assert_active_admin_invariant(
            db, excluding_user_id=user.id, code="user.last_admin"
        )

    user.role = applied
    data: dict = {"role": applied.value}
    if requested != applied:
        data = {"requested": requested.value, "applied": applied.value}
    await audit_repo.record(
        db,
        actor_id=admin.id,
        action="admin.user.role",
        target_type="user",
        target_id=user.id,
        data=data,
    )
    return UserAdminOut.model_validate(user)


@router.patch("/users/{user_id}/admin", response_model=UserAdminOut)
async def set_user_admin(
    user_id: str,
    payload: AdminToggleUpdate,
    admin: RequireAdmin,
    db: DBSession,
    request: Request,
) -> UserAdminOut:
    """Grant or revoke the admin role (S6.6 / FR-ADMIN-01).

    Replaces the role ``<Select>`` write path with a ``{is_admin}`` toggle.
    Revoking is refused with ``422 user.last_admin`` if it would leave zero
    active admins (FR-ADMIN-03) — including self-revoke and revoking the only
    other admin.
    """
    user = await _load_user_or_404(db, user_id)
    user = await admin_users_service.set_admin(
        db,
        target=user,
        is_admin=payload.is_admin,
        actor=admin,
        ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return UserAdminOut.model_validate(user)


@router.patch("/users/{user_id}/active", response_model=UserAdminOut)
async def set_user_active(
    user_id: str, payload: UserActiveUpdate, admin: RequireAdmin, db: DBSession, request: Request
) -> UserAdminOut:
    """DEPRECATED generic active toggle — prefer ``/suspend`` + ``/reinstate``
    (S6.7). Folded onto the same service so the last-admin invariant and the
    refresh-token revocation apply uniformly."""
    user = await _load_user_or_404(db, user_id)
    if payload.is_active:
        user = await admin_users_service.reinstate(
            db,
            target=user,
            actor=admin,
            ip=client_ip(request),
            user_agent=user_agent(request),
        )
    else:
        user = await admin_users_service.suspend(
            db,
            target=user,
            reason=ReasonCode.other,
            actor=admin,
            ip=client_ip(request),
            user_agent=user_agent(request),
        )
    return UserAdminOut.model_validate(user)


@router.patch("/users/{user_id}/suspend", response_model=UserAdminOut)
async def suspend_user(
    user_id: str,
    payload: SuspendUpdate,
    admin: RequireAdmin,
    db: DBSession,
    request: Request,
) -> UserAdminOut:
    """Suspend a user (S6.7 / FR-SUSP-01): ``is_active=False`` + refresh revoke,
    ``deleted_at`` stays null. Refused with ``422 user.last_admin_active`` on the
    last active admin."""
    user = await _load_user_or_404(db, user_id)
    user = await admin_users_service.suspend(
        db,
        target=user,
        reason=payload.reason,
        note=payload.note,
        actor=admin,
        ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return UserAdminOut.model_validate(user)


@router.patch("/users/{user_id}/reinstate", response_model=UserAdminOut)
async def reinstate_user(
    user_id: str, admin: RequireAdmin, db: DBSession, request: Request
) -> UserAdminOut:
    """Reinstate a suspended user (S6.7 / FR-SUSP-02). Refused with
    ``422 user.deleted_irreversible`` on a tombstoned account."""
    user = await _load_user_or_404(db, user_id)
    user = await admin_users_service.reinstate(
        db,
        target=user,
        actor=admin,
        ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return UserAdminOut.model_validate(user)


# ---------- Courses (admin overview) ----------


class FeatureUpdate(BaseModel):
    is_featured: bool


@router.get("/courses", response_model=list[CourseListItem])
async def list_all_courses(
    admin: RequireAdmin,
    db: DBSession,
    q: str | None = Query(default=None, max_length=200),
    only_featured: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[CourseListItem]:
    stmt = (
        select(Course)
        .where(Course.deleted_at.is_(None))
        .order_by(desc(Course.created_at))
        .limit(limit)
        .options(
            selectinload(Course.subject),
            selectinload(Course.owner),
            selectinload(Course.tags),
        )
    )
    if q:
        like = f"%{q}%"
        stmt = stmt.where((Course.title.ilike(like)) | (Course.overview.ilike(like)))
    if only_featured:
        stmt = stmt.where(Course.is_featured.is_(True))
    rows = list((await db.execute(stmt)).scalars().unique().all())
    stats = await courses_repo.stats_for_courses(db, [c.id for c in rows])
    # Pass the admin as viewer so moderation_state is visible on this surface.
    return [_builders.list_item(c, stats.get(c.id, {}), viewer=admin) for c in rows]


@router.get("/courses/moderation-queue", response_model=list[CourseListItem])
async def moderation_queue(
    admin: RequireAdmin,
    db: DBSession,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[CourseListItem]:
    """The pending-review moderation queue (S2.11 minimal API; S6 enriches).

    Lists courses awaiting review that still carry an **active sharing intent**:
    ``moderation_state == pending_review`` AND ``visibility == public`` AND
    ``status == published`` (DR-21: the queue is for courses the owner is
    actually asking to list publicly). The approve/reject ACTIONS are S6's;
    the ``/admin/moderation`` page renders this queue.

    ``moderation_state`` itself is **sticky** — unsharing (public→private) or
    unpublishing (published→draft) does NOT reset it to ``none`` (see
    ``courses.unshare_course``/``unpublish_course``). So a course can sit at
    ``pending_review`` in the DB while being absent from this queue: the
    sticky state is preserved for the eventual re-share (R-M9 reuses any prior
    approval), but the admin only sees it here while the sharing intent is
    live. Re-sharing flips ``visibility`` back to public and the row reappears
    without a fresh owner action.
    """
    from app.models.course import CourseStatus, ModerationState, Visibility

    stmt = (
        select(Course)
        .where(
            Course.deleted_at.is_(None),
            Course.moderation_state == ModerationState.pending_review,
            # Active sharing intent only (DR-21): a course unshared/unpublished
            # back to private/draft keeps its sticky pending_review state but
            # drops out of the live queue.
            Course.visibility == Visibility.public,
            Course.status == CourseStatus.published,  # noqa: published-check — lifecycle stat
        )
        .order_by(Course.updated_at.asc())  # oldest-waiting first
        .limit(limit)
        .options(
            selectinload(Course.subject),
            selectinload(Course.owner),
            selectinload(Course.tags),
        )
    )
    rows = list((await db.execute(stmt)).scalars().unique().all())
    stats = await courses_repo.stats_for_courses(db, [c.id for c in rows])
    return [_builders.list_item(c, stats.get(c.id, {}), viewer=admin) for c in rows]


@router.patch("/courses/{course_id}/feature", response_model=CourseListItem)
async def set_course_featured(
    course_id: str, payload: FeatureUpdate, admin: RequireAdmin, db: DBSession
) -> CourseListItem:
    course = await courses_repo.get_course(db, course_id)
    if not course:
        raise NotFoundError("Course not found", code="course.not_found")
    # FR-MOD (ADR-0026 §"Service changes"): you can only feature a publicly-
    # listed course. Featuring a private/pending/delisted/quarantined course
    # would surface it on the homepage without it being discoverable — a leak.
    # De-featuring (is_featured=False) is always allowed (it only removes).
    if payload.is_featured and not visibility_service.is_publicly_listed(course):
        raise ConflictError(
            "Only a publicly-listed course can be featured", code="course.not_listed"
        )
    if course.is_featured != payload.is_featured:
        course.is_featured = payload.is_featured
        await audit_repo.record(
            db,
            actor_id=admin.id,
            action="admin.course.featured",
            target_type="course",
            target_id=course.id,
            data={"is_featured": payload.is_featured},
        )
    stats = (await courses_repo.stats_for_courses(db, [course.id])).get(course.id, {})
    return _builders.list_item(course, stats)


# ---------- Moderation actions (S6.4 / ADR-0026 §4) ----------


class ModerationActionRequest(BaseModel):
    """Body for the admin moderation action endpoints. ``reason``/``note`` are
    optional for approve/relist, required-by-semantics for remove (the service
    enforces remove's reason)."""

    model_config = ConfigDict(extra="forbid")

    reason: ReasonCode | None = None
    note: str | None = Field(default=None, max_length=5000)


async def _moderated_detail(db: DBSession, admin: User, course: Course) -> CourseListItem:
    """Render a post-transition course (already loaded with relations by the
    service's ``_load_course``) as an admin-viewer list item. Built from the
    returned instance so it works even when the course was just soft-deleted
    (``remove``) — a fresh ``get_course`` would filter it out."""
    stats = (await courses_repo.stats_for_courses(db, [course.id])).get(course.id, {})
    return _builders.list_item(course, stats, viewer=admin)


@router.post("/courses/{course_id}/approve", response_model=CourseListItem)
async def approve_course(
    course_id: str,
    payload: ModerationActionRequest,
    admin: RequireAdmin,
    db: DBSession,
    request: Request,
) -> CourseListItem:
    course = await moderation_service.approve_course(
        db,
        course_id=course_id,
        actor=admin,
        note=payload.note,
        ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return await _moderated_detail(db, admin, course)


@router.post("/courses/{course_id}/reject", response_model=CourseListItem)
async def reject_course(
    course_id: str,
    payload: ModerationActionRequest,
    admin: RequireAdmin,
    db: DBSession,
    request: Request,
) -> CourseListItem:
    course = await moderation_service.reject_course(
        db,
        course_id=course_id,
        actor=admin,
        reason=payload.reason,
        note=payload.note,
        ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return await _moderated_detail(db, admin, course)


@router.post("/courses/{course_id}/delist", response_model=CourseListItem)
async def delist_course(
    course_id: str,
    payload: ModerationActionRequest,
    admin: RequireAdmin,
    db: DBSession,
    request: Request,
) -> CourseListItem:
    course = await moderation_service.delist_course(
        db,
        course_id=course_id,
        actor=admin,
        reason=payload.reason,
        note=payload.note,
        ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return await _moderated_detail(db, admin, course)


@router.post("/courses/{course_id}/relist", response_model=CourseListItem)
async def relist_course(
    course_id: str,
    payload: ModerationActionRequest,
    admin: RequireAdmin,
    db: DBSession,
    request: Request,
) -> CourseListItem:
    course = await moderation_service.relist_course(
        db,
        course_id=course_id,
        actor=admin,
        note=payload.note,
        ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return await _moderated_detail(db, admin, course)


@router.post("/courses/{course_id}/remove", response_model=CourseListItem)
async def remove_course(
    course_id: str,
    payload: ModerationActionRequest,
    admin: RequireAdmin,
    db: DBSession,
    request: Request,
) -> CourseListItem:
    if payload.reason is None:
        raise ValidationAppError(
            "A reason is required to remove a course", code="report.reason_required"
        )
    course = await moderation_service.remove_course(
        db,
        course_id=course_id,
        actor=admin,
        reason=payload.reason,
        note=payload.note,
        ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return await _moderated_detail(db, admin, course)


# ---------- Reports (S6.4) ----------


class ReportOut(BaseModel):
    """Admin report DTO. Carries reporter PII (FR-MOD-12 admin-only); the note
    is the already-sanitized inert text (FR-MOD-13)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
    reporter_id: str
    reason: str
    note: str | None
    status: str
    created_at: datetime
    resolved_at: datetime | None
    resolved_by: str | None


class ReportResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(pattern="^(dismiss|delist|remove)$")
    reason: ReasonCode | None = None
    note: str | None = Field(default=None, max_length=5000)


@router.get("/reports", response_model=list[ReportOut])
async def list_reports(
    _: RequireAdmin,
    db: DBSession,
    status_filter: str | None = Query(default=None, alias="status", max_length=16),
    reason: str | None = Query(default=None, max_length=40),
    course_id: str | None = Query(default=None, max_length=21),
    cursor: str | None = Query(
        default=None,
        max_length=21,
        description="Cursor: the id of the last report from the previous page.",
    ),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ReportOut]:
    rows = await moderation_repo.list_reports(
        db,
        status=status_filter,
        reason=reason,
        course_id=course_id,
        cursor=cursor,
        limit=limit,
    )
    return [ReportOut.model_validate(r) for r in rows]


@router.post("/reports/{report_id}/resolve", response_model=ReportOut)
async def resolve_report(
    report_id: str,
    payload: ReportResolveRequest,
    admin: RequireAdmin,
    db: DBSession,
    request: Request,
) -> ReportOut:
    """Resolve a report, performing the linked moderation action atomically in
    one transaction with a single linked audit trail (FR-MOD-12)."""
    report = await moderation_service.resolve_report(
        db,
        report_id=report_id,
        actor=admin,
        action=payload.action,
        reason=payload.reason,
        note=payload.note,
        ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return ReportOut.model_validate(report)


# ---------- Audit log ----------


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    actor_id: str | None
    action: str
    target_type: str | None
    target_id: str | None
    created_at: datetime
    data: dict


@router.get("/audit", response_model=list[AuditEventOut])
async def list_audit(
    _: RequireAdmin,
    db: DBSession,
    action: str | None = Query(default=None, max_length=80),
    actor_id: str | None = Query(default=None, max_length=64),
    before: str | None = Query(
        default=None,
        max_length=64,
        description=(
            "Cursor: pass the id of the oldest event from the previous page "
            "to fetch events strictly older than that anchor. Returns events "
            "in created_at DESC order, same as the no-cursor call."
        ),
    ),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AuditEventOut]:
    stmt = select(AuditEvent).order_by(desc(AuditEvent.created_at)).limit(limit)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if actor_id:
        stmt = stmt.where(AuditEvent.actor_id == actor_id)
    if before:
        anchor = await db.get(AuditEvent, before)
        if anchor is not None:
            # Strict less-than on created_at — same pattern as
            # chat.history. Duplicate timestamps at the boundary are
            # a known minor edge case across the codebase and not
            # worth a tiebreaker complication here either.
            stmt = stmt.where(AuditEvent.created_at < anchor.created_at)
    rows = (await db.execute(stmt)).scalars().all()
    return [AuditEventOut.model_validate(r) for r in rows]


# ---------- Search ----------


@router.post("/search/reindex", response_model=OkResponse, status_code=status.HTTP_202_ACCEPTED)
async def reindex_search(admin: RequireAdmin, db: DBSession) -> OkResponse:
    """Reindex acknowledgement — fans out per-course embedding rebuilds.

    The Postgres full-text ``search_vector`` column is a STORED
    generated column maintained by Postgres on every write (rebuild
    Cut A9), so the *FTS* side of search has nothing to rebuild here.
    What this endpoint now drives is the *embedding* side: one
    ``index_course_embeddings`` Celery task per live published course,
    refreshing every lesson's chunks against the currently-configured
    embedding provider. Useful when:

    * we change ``EMBEDDING_PROVIDER`` and want existing catalogues
      re-embedded against the new model;
    * a chunker bug-fix shipped and we want to backfill;
    * a fresh deploy has empty ``lesson_chunks`` rows and we want to
      backfill the historical catalogue without re-publishing
      every course by hand.

    Enqueue is best-effort per course — broker failures are logged
    by the task itself. The endpoint stays 202 (accepted, not done)
    because the actual work runs on the worker.
    """
    await audit_repo.record(db, actor_id=admin.id, action="admin.search.reindex")
    # Deferred import — see service-layer ``_schedule_embedding_index``
    # for the same reasoning.
    try:
        from app.workers.tasks.embeddings import index_course_embeddings
    except Exception:  # pragma: no cover — Celery not importable
        return OkResponse()

    res = await db.execute(
        select(Course.id).where(
            Course.deleted_at.is_(None),
            # Reindex fan-out is a LIFECYCLE selection, not an access read: it
            # must cover ALL published courses (incl. published-private) so an
            # owner's private-course RAG stays fresh. Allowlisted (DR-3-R2).
            Course.status == CourseStatus.published,  # noqa: published-check — lifecycle stat
        )
    )
    for (course_id,) in res.all():
        try:
            index_course_embeddings.delay(course_id)
        except Exception:  # pragma: no cover — broker may be down
            # We swallow per-course so one stuck enqueue doesn't
            # truncate the fan-out; the operator can re-run.
            continue
    return OkResponse()


# ---------- Platform stats ----------


class PlatformStatsOut(BaseModel):
    users: int
    active_users: int
    # S1.8 / FR-ADMIN-05: with the role collapse there is no "instructor" stat.
    # `admins` = users with the admin role; `authors` = distinct owners of at
    # least one live (non-deleted) course (the closest meaningful "creators"
    # signal in the two-role model). The `instructors` field is removed; the
    # admin dashboard reads `admins`/`authors` (S1.11, same PR — DR-5).
    admins: int
    authors: int
    courses_total: int
    # Lifecycle count: courses whose ``status == published`` (incl.
    # published-private). NOT a discoverability measure — see ``courses_listed``.
    courses_published: int
    # Publicly-listed count (S2.8): public AND published AND approved AND live.
    courses_listed: int
    courses_draft: int
    enrollments: int


@router.get("/stats", response_model=PlatformStatsOut)
async def platform_stats(_: RequireAdmin, db: DBSession) -> PlatformStatsOut:
    live = Course.deleted_at.is_(None)
    return PlatformStatsOut(
        users=await _scalar_count(db, select(func.count(User.id))),
        active_users=await _scalar_count(
            db, select(func.count(User.id)).where(User.is_active.is_(True))
        ),
        admins=await _scalar_count(
            db,
            select(func.count(User.id)).where(User.role == Role.admin),
        ),
        authors=await _scalar_count(
            db,
            select(func.count(func.distinct(Course.owner_id))).where(live),
        ),
        courses_total=await _scalar_count(db, select(func.count(Course.id)).where(live)),
        courses_published=await _scalar_count(
            db,
            # Lifecycle count, NOT an access read — allowlisted (DR-3-R2: the
            # grep-guard is the source of truth; a lifecycle stat is not a
            # discoverability read). The publicly-listed measure is below.
            select(func.count(Course.id)).where(live, Course.status == CourseStatus.published),  # noqa: published-check — lifecycle stat
        ),
        courses_listed=await _scalar_count(
            db,
            select(func.count(Course.id)).where(visibility_service.publicly_listed_sql()),
        ),
        courses_draft=await _scalar_count(
            db,
            select(func.count(Course.id)).where(live, Course.status == CourseStatus.draft),
        ),
        enrollments=await _scalar_count(db, select(func.count(Enrollment.id))),
    )
