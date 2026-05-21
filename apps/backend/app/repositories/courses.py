from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.course import (
    Course,
    CourseStatus,
    Enrollment,
    Lesson,
    LessonProgress,
    Module,
    Review,
    Subject,
    Tag,
)


async def get_subject(db: AsyncSession, subject_id: str) -> Subject | None:
    return await db.get(Subject, subject_id)


async def get_subject_by_slug(db: AsyncSession, slug: str) -> Subject | None:
    res = await db.execute(select(Subject).where(Subject.slug == slug))
    return res.scalar_one_or_none()


async def list_subjects(db: AsyncSession) -> list[tuple[Subject, int]]:
    res = await db.execute(
        select(Subject, func.count(Course.id).label("total"))
        .outerjoin(Course, and_(Course.subject_id == Subject.id, Course.status == CourseStatus.published))
        .group_by(Subject.id)
        .order_by(Subject.title.asc())
    )
    return [(row[0], int(row[1] or 0)) for row in res.all()]


async def list_tags(db: AsyncSession) -> list[Tag]:
    res = await db.execute(select(Tag).order_by(Tag.name.asc()))
    return list(res.scalars().all())


def _course_with_relations() -> Select[tuple[Course]]:
    return select(Course).options(
        selectinload(Course.subject),
        selectinload(Course.owner),
        selectinload(Course.tags),
    )


async def get_course(db: AsyncSession, course_id: str, *, with_modules: bool = False) -> Course | None:
    stmt = _course_with_relations().where(Course.id == course_id, Course.deleted_at.is_(None))
    if with_modules:
        stmt = stmt.options(selectinload(Course.modules).selectinload(Module.lessons))
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


async def get_course_by_slug(db: AsyncSession, slug: str, *, with_modules: bool = False) -> Course | None:
    stmt = _course_with_relations().where(Course.slug == slug, Course.deleted_at.is_(None))
    if with_modules:
        stmt = stmt.options(selectinload(Course.modules).selectinload(Module.lessons))
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


async def search_courses(
    db: AsyncSession,
    *,
    q: str | None = None,
    subject_slug: str | None = None,
    tag_slug: str | None = None,
    difficulty: str | None = None,
    only_published: bool = True,
    owner_id: str | None = None,
    sort: str = "-created_at",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Course], int]:
    stmt = _course_with_relations().where(Course.deleted_at.is_(None))

    if only_published:
        stmt = stmt.where(Course.status == CourseStatus.published)
    if owner_id:
        stmt = stmt.where(Course.owner_id == owner_id)
    if subject_slug:
        stmt = stmt.join(Subject).where(Subject.slug == subject_slug)
    if tag_slug:
        stmt = stmt.join(Course.tags).where(Tag.slug == tag_slug)
    if difficulty:
        stmt = stmt.where(Course.difficulty == difficulty)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Course.title.ilike(like), Course.overview.ilike(like)))

    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = int((await db.execute(count_stmt)).scalar_one())

    direction = "desc" if sort.startswith("-") else "asc"
    field_name = sort.lstrip("-")
    col = getattr(Course, field_name, Course.created_at)
    stmt = stmt.order_by(col.desc() if direction == "desc" else col.asc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    res = await db.execute(stmt)
    return list(res.scalars().unique().all()), total


async def list_tags_by_ids(db: AsyncSession, tag_ids: list[str]) -> list[Tag]:
    if not tag_ids:
        return []
    res = await db.execute(select(Tag).where(Tag.id.in_(tag_ids)))
    return list(res.scalars().all())


async def stats_for_courses(db: AsyncSession, course_ids: list[str]) -> dict[str, dict[str, float | int]]:
    if not course_ids:
        return {}

    res_mods = await db.execute(
        select(Module.course_id, func.count(Module.id))
        .where(Module.course_id.in_(course_ids))
        .group_by(Module.course_id)
    )
    modules_count = {cid: int(n) for cid, n in res_mods.all()}

    res_enr = await db.execute(
        select(Enrollment.course_id, func.count(Enrollment.id))
        .where(Enrollment.course_id.in_(course_ids))
        .group_by(Enrollment.course_id)
    )
    enrollments_count = {cid: int(n) for cid, n in res_enr.all()}

    res_avg = await db.execute(
        select(Review.course_id, func.avg(Review.rating))
        .where(Review.course_id.in_(course_ids), Review.deleted_at.is_(None))
        .group_by(Review.course_id)
    )
    avg_rating = {cid: float(r) for cid, r in res_avg.all() if r is not None}

    return {
        cid: {
            "modules_count": modules_count.get(cid, 0),
            "enrollments_count": enrollments_count.get(cid, 0),
            "avg_rating": avg_rating.get(cid),
        }
        for cid in course_ids
    }


# ----- Modules -----


async def get_module(db: AsyncSession, module_id: str) -> Module | None:
    res = await db.execute(select(Module).options(selectinload(Module.lessons)).where(Module.id == module_id))
    return res.scalar_one_or_none()


async def list_modules_for_course(db: AsyncSession, course_id: str) -> list[Module]:
    res = await db.execute(
        select(Module).options(selectinload(Module.lessons)).where(Module.course_id == course_id).order_by(Module.order)
    )
    return list(res.scalars().all())


async def next_module_order(db: AsyncSession, course_id: str) -> int:
    res = await db.execute(select(func.coalesce(func.max(Module.order), -1)).where(Module.course_id == course_id))
    return int(res.scalar_one()) + 1


# ----- Lessons -----


async def get_lesson(db: AsyncSession, lesson_id: str) -> Lesson | None:
    return await db.get(Lesson, lesson_id)


async def next_lesson_order(db: AsyncSession, module_id: str) -> int:
    res = await db.execute(select(func.coalesce(func.max(Lesson.order), -1)).where(Lesson.module_id == module_id))
    return int(res.scalar_one()) + 1


# ----- Enrollments / Progress -----


async def get_enrollment(db: AsyncSession, *, user_id: str, course_id: str) -> Enrollment | None:
    res = await db.execute(
        select(Enrollment).where(Enrollment.user_id == user_id, Enrollment.course_id == course_id)
    )
    return res.scalar_one_or_none()


async def list_enrollments_for_user(db: AsyncSession, user_id: str) -> list[Enrollment]:
    res = await db.execute(
        select(Enrollment)
        .options(selectinload(Enrollment.course).selectinload(Course.subject))
        .options(selectinload(Enrollment.course).selectinload(Course.owner))
        .options(selectinload(Enrollment.course).selectinload(Course.tags))
        .where(Enrollment.user_id == user_id)
        .order_by(Enrollment.created_at.desc())
    )
    return list(res.scalars().unique().all())


async def count_lessons_in_course(db: AsyncSession, course_id: str) -> int:
    res = await db.execute(
        select(func.count(Lesson.id))
        .join(Module, Module.id == Lesson.module_id)
        .where(Module.course_id == course_id, Lesson.deleted_at.is_(None))
    )
    return int(res.scalar_one())


async def count_completed_lessons(db: AsyncSession, enrollment_id: str) -> int:
    res = await db.execute(
        select(func.count(LessonProgress.id)).where(
            LessonProgress.enrollment_id == enrollment_id, LessonProgress.completed_at.is_not(None)
        )
    )
    return int(res.scalar_one())


async def get_or_create_progress(
    db: AsyncSession, *, enrollment_id: str, lesson_id: str
) -> LessonProgress:
    res = await db.execute(
        select(LessonProgress).where(
            LessonProgress.enrollment_id == enrollment_id, LessonProgress.lesson_id == lesson_id
        )
    )
    lp = res.scalar_one_or_none()
    if lp:
        return lp
    lp = LessonProgress(enrollment_id=enrollment_id, lesson_id=lesson_id)
    db.add(lp)
    await db.flush()
    return lp


async def mark_completed(db: AsyncSession, lp: LessonProgress, *, payload: dict[str, object] | None = None) -> None:
    if not lp.completed_at:
        lp.completed_at = datetime.now(timezone.utc)
    if payload:
        lp.payload = {**(lp.payload or {}), **payload}


# ----- Reviews -----


async def get_review(db: AsyncSession, *, author_id: str, course_id: str) -> Review | None:
    res = await db.execute(
        select(Review).where(
            Review.author_id == author_id, Review.course_id == course_id, Review.deleted_at.is_(None)
        )
    )
    return res.scalar_one_or_none()


async def list_reviews_for_course(db: AsyncSession, course_id: str, *, limit: int = 20, offset: int = 0) -> list[Review]:
    res = await db.execute(
        select(Review)
        .options(selectinload(Review.author))
        .where(Review.course_id == course_id, Review.deleted_at.is_(None))
        .order_by(Review.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(res.scalars().all())
