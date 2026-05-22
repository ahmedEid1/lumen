"""Admin-only endpoints: subjects, tags, users, audit log."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field
from slugify import slugify
from sqlalchemy import desc, func, select
from sqlalchemy.orm import selectinload

from app.api.deps import DBSession, RequireAdmin
from app.api.v1 import _builders
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.models.audit import AuditEvent
from app.models.course import Course, CourseStatus, Enrollment, Subject, Tag
from app.models.user import Role, User
from app.repositories import audit as audit_repo
from app.repositories import courses as courses_repo
from app.schemas.common import OkResponse
from app.schemas.course import CourseListItem, SubjectOut, TagOut

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
async def update_subject(subject_id: str, payload: SubjectIn, _: RequireAdmin, db: DBSession) -> SubjectOut:
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
    total = await _scalar_count(
        db, select(func.count(Course.id)).where(Course.subject_id == s.id)
    )
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


class UserRoleUpdate(BaseModel):
    role: Role


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
    user = await _load_user_or_404(db, user_id)
    if user.id == admin.id and payload.role != Role.admin:
        raise ValidationAppError("Cannot demote yourself", code="user.self_demote")
    user.role = payload.role
    await audit_repo.record(
        db, actor_id=admin.id, action="admin.user.role", target_type="user", target_id=user.id, data={"role": payload.role.value}
    )
    return UserAdminOut.model_validate(user)


@router.patch("/users/{user_id}/active", response_model=UserAdminOut)
async def set_user_active(
    user_id: str, payload: UserActiveUpdate, admin: RequireAdmin, db: DBSession
) -> UserAdminOut:
    user = await _load_user_or_404(db, user_id)
    if user.id == admin.id and not payload.is_active:
        raise ValidationAppError("Cannot deactivate yourself", code="user.self_deactivate")
    user.is_active = payload.is_active
    await audit_repo.record(
        db,
        actor_id=admin.id,
        action="admin.user.active",
        target_type="user",
        target_id=user.id,
        data={"is_active": payload.is_active},
    )
    return UserAdminOut.model_validate(user)


# ---------- Courses (admin overview) ----------


class FeatureUpdate(BaseModel):
    is_featured: bool


@router.get("/courses", response_model=list[CourseListItem])
async def list_all_courses(
    _: RequireAdmin,
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
    return [_builders.list_item(c, stats.get(c.id, {})) for c in rows]


@router.patch("/courses/{course_id}/feature", response_model=CourseListItem)
async def set_course_featured(
    course_id: str, payload: FeatureUpdate, admin: RequireAdmin, db: DBSession
) -> CourseListItem:
    course = await courses_repo.get_course(db, course_id)
    if not course:
        raise NotFoundError("Course not found", code="course.not_found")
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
    """Reindex acknowledgement (no-op under Postgres FTS).

    Since rebuild Cut A9 the search index is a GENERATED ALWAYS AS
    STORED tsvector column maintained by Postgres on every write — no
    out-of-band worker reindex can put it ahead of the table. The
    endpoint is kept (with the original 202 contract + audit row) so
    existing operator tooling continues to work; the audit row is
    still a useful "an admin asked for a reindex" signal.
    """
    await audit_repo.record(db, actor_id=admin.id, action="admin.search.reindex")
    return OkResponse()


# ---------- Platform stats ----------


class PlatformStatsOut(BaseModel):
    users: int
    active_users: int
    instructors: int
    courses_total: int
    courses_published: int
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
        instructors=await _scalar_count(
            db,
            select(func.count(User.id)).where(
                User.role.in_([Role.instructor, Role.admin])
            ),
        ),
        courses_total=await _scalar_count(db, select(func.count(Course.id)).where(live)),
        courses_published=await _scalar_count(
            db,
            select(func.count(Course.id)).where(
                live, Course.status == CourseStatus.published
            ),
        ),
        courses_draft=await _scalar_count(
            db,
            select(func.count(Course.id)).where(
                live, Course.status == CourseStatus.draft
            ),
        ),
        enrollments=await _scalar_count(db, select(func.count(Enrollment.id))),
    )
