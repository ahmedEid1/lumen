from __future__ import annotations

from datetime import datetime, UTC

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

# Allow-list for `?sort=` on the catalog. Restricted to columns whose
# ``desc()`` / ``asc()`` is meaningful and that don't leak internal state.
_SORTABLE_COLUMNS = {
    "created_at": Course.created_at,
    "published_at": Course.published_at,
    "title": Course.title,
    "is_featured": Course.is_featured,
}


async def get_subject(db: AsyncSession, subject_id: str) -> Subject | None:
    return await db.get(Subject, subject_id)


async def get_subject_by_slug(db: AsyncSession, slug: str) -> Subject | None:
    res = await db.execute(select(Subject).where(Subject.slug == slug))
    return res.scalar_one_or_none()


async def list_subjects(db: AsyncSession) -> list[tuple[Subject, int]]:
    res = await db.execute(
        select(Subject, func.count(Course.id).label("total"))
        .outerjoin(
            Course,
            and_(
                Course.subject_id == Subject.id,
                Course.status == CourseStatus.published,
                # A soft-deleted course retains its published status until
                # the row is reaped, so we must filter it out explicitly
                # — otherwise the catalog tile claims more courses than it
                # actually shows.
                Course.deleted_at.is_(None),
            ),
        )
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


async def get_courses_by_ids(db: AsyncSession, ids: list[str]) -> list[Course]:
    if not ids:
        return []
    res = await db.execute(
        _course_with_relations().where(Course.id.in_(ids), Course.deleted_at.is_(None))
    )
    return list(res.scalars().unique().all())


async def get_course_by_slug(db: AsyncSession, slug: str, *, with_modules: bool = False) -> Course | None:
    stmt = _course_with_relations().where(Course.slug == slug, Course.deleted_at.is_(None))
    if with_modules:
        stmt = stmt.options(selectinload(Course.modules).selectinload(Module.lessons))
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


async def slug_is_taken(db: AsyncSession, slug: str, *, exclude_id: str | None = None) -> bool:
    """Has any row (alive or soft-deleted) claimed this slug?

    The DB enforces ``UNIQUE(courses.slug)`` regardless of ``deleted_at``,
    so callers minting new slugs must check against the raw table — not
    via ``get_course_by_slug`` which already hides deleted rows.
    """
    stmt = select(Course.id).where(Course.slug == slug).limit(1)
    if exclude_id is not None:
        stmt = stmt.where(Course.id != exclude_id)
    return (await db.execute(stmt)).first() is not None


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
    # Search ranking: when ``q`` is set we use Postgres' full-text
    # ``websearch_to_tsquery`` for relevance (handles quoted phrases,
    # operators, stop-word stripping) and fall back to ILIKE for
    # partial-word matches the FTS would miss (e.g. "java" finding
    # "javascript"). Hits matching the full-text path get a ts_rank;
    # ILIKE-only hits get a small floor so they still appear under
    # exact matches. We don't add a tsvector column / GIN index here
    # — at the courses-table size we're operating at, an inline
    # ``to_tsvector('english', title || ' ' || overview)`` is cheap.
    # Promote to materialised column if the table grows past ~1M rows.
    rank_col: object | None = None
    if q:
        ts_query = func.websearch_to_tsquery("english", q)
        title_overview = func.coalesce(Course.title, "") + " " + func.coalesce(Course.overview, "")
        ts_doc = func.to_tsvector("english", title_overview)
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                ts_doc.op("@@")(ts_query),
                Course.title.ilike(like),
                Course.overview.ilike(like),
            )
        )
        # ts_rank when the FTS matched; 0.0 floor for the ILIKE-only
        # fallback. ``case`` keeps rank-aware ORDER BY working even
        # when the FTS expression evaluates to false on a row.
        from sqlalchemy import case

        rank_col = case(
            (ts_doc.op("@@")(ts_query), func.ts_rank(ts_doc, ts_query)),
            else_=0.0,
        )

    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = int((await db.execute(count_stmt)).scalar_one())

    direction = "desc" if sort.startswith("-") else "asc"
    field_name = sort.lstrip("-")
    # ``getattr(Course, ...)`` happily returns relationships and dunder
    # attributes whose ``.desc()`` blows up with AttributeError → 500.
    # Constrain to columns we know are safe + useful to order on.
    col = _SORTABLE_COLUMNS.get(field_name, Course.created_at)
    if q and rank_col is not None:
        # When the caller didn't override sort, push rank to the front
        # so the most relevant match shows first; otherwise honour
        # their explicit sort (e.g. ``-published_at``) and use rank
        # only as a tiebreaker.
        if sort == "-created_at":  # the implicit default
            stmt = stmt.order_by(rank_col.desc(), Course.created_at.desc())
        else:
            stmt = stmt.order_by(
                col.desc() if direction == "desc" else col.asc(),
                rank_col.desc(),
            )
    else:
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
    """Active enrollments for the dashboard.

    Filters out enrollments whose course has been soft-deleted — otherwise
    the dashboard would render a row whose "Continue learning" link
    immediately 404s, since :func:`get_course` hides deleted rows.
    """
    res = await db.execute(
        select(Enrollment)
        .join(Course, Course.id == Enrollment.course_id)
        .options(selectinload(Enrollment.course).selectinload(Course.subject))
        .options(selectinload(Enrollment.course).selectinload(Course.owner))
        .options(selectinload(Enrollment.course).selectinload(Course.tags))
        .where(Enrollment.user_id == user_id, Course.deleted_at.is_(None))
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


async def completed_lesson_ids(db: AsyncSession, enrollment_id: str) -> set[str]:
    """Set of lesson ids the learner has completed in an enrollment.

    Filters out completions for soft-deleted lessons so the syllabus
    check-marks line up with what's actually still in the course.
    """
    res = await db.execute(
        select(LessonProgress.lesson_id)
        .join(Lesson, Lesson.id == LessonProgress.lesson_id)
        .where(
            LessonProgress.enrollment_id == enrollment_id,
            LessonProgress.completed_at.is_not(None),
            Lesson.deleted_at.is_(None),
        )
    )
    return {row[0] for row in res.all()}


async def count_completed_lessons(db: AsyncSession, enrollment_id: str) -> int:
    """Count completions for lessons that still exist.

    A naive ``COUNT(LessonProgress)`` over-reports when lessons are
    soft-deleted after the learner completed them, which can push
    ``progress_pct`` past 100% and trigger spurious certificates.
    """
    res = await db.execute(
        select(func.count(LessonProgress.id))
        .join(Lesson, Lesson.id == LessonProgress.lesson_id)
        .where(
            LessonProgress.enrollment_id == enrollment_id,
            LessonProgress.completed_at.is_not(None),
            Lesson.deleted_at.is_(None),
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
        lp.completed_at = datetime.now(UTC)
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
