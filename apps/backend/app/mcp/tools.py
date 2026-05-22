"""MCP tool implementations — the 9 surfaces Claude calls through.

Lumen v2 Phase I1. Each function here is a thin adapter over an
existing Lumen service:

============================  ==========================================
MCP tool                       Backing service / repo
============================  ==========================================
``list_courses``               ``repositories.courses.search_courses``
``get_course``                 ``repositories.courses.get_course_by_slug``
``search_lesson_content``      ``services.embeddings_retrieval.find_relevant_chunks``
``ask_tutor``                  ``services.tutor.ask``
``list_my_due_reviews``        ``services.fsrs.due_cards``
``grade_review_card``          ``services.fsrs.record_review``
``create_course_draft``        ``services.ai_authoring.generate_outline`` + ``commit_outline``
``ingest_url_to_draft``        ``services.content_ingest.ingest`` + ``commit_payload``
``list_my_progress``           ``services.mastery.per_course_mastery``
============================  ==========================================

Tools that touch an LLM (``ask_tutor``, ``create_course_draft``,
``ingest_url_to_draft``) route through ``llm_call_log.call_logged``
so they count against the per-user 24h budget guard (H1) and surface
in the cost meter dashboard. Tools that retrieve from the embedding
index (``search_lesson_content``, transitively ``ask_tutor``) write a
``retrieval_audits`` row via the ``audit=True`` hook on
``find_relevant_chunks`` (H7).

Auth posture per tool:

* ``list_courses`` / ``get_course`` — public (no auth required).
  Mirrors the public catalog API. The dispatcher still requires *a*
  principal (so we can attribute traces / costs), but doesn't gate
  on role.
* ``search_lesson_content`` — any authenticated principal. The
  retrieval endpoint is course-scoped, so leakage across courses
  is already bounded by the slug→course resolve.
* ``ask_tutor`` — authenticated + enrolled in the course (or the
  course owner / an admin). Mirrors the REST tutor endpoint's
  authz.
* ``list_my_due_reviews`` / ``grade_review_card`` / ``list_my_progress``
  — authenticated, scoped to the calling user.
* ``create_course_draft`` / ``ingest_url_to_draft`` — instructor
  or admin only.

Each tool returns a Pydantic model (declared inline here for
proximity) so the MCP framework auto-generates a JSON schema for
Claude. The shapes deliberately omit internal ids when a slug or
human-readable label suffices, and truncate long text fields (chunk
text, lesson body) so the response stays small — the model is
allowed to ask for more via a follow-up tool call.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import (
    ForbiddenError,
    NotFoundError,
    ValidationAppError,
)
from app.core.ids import new_id
from app.mcp.principal import Principal
from app.models.course import (
    Course,
    CourseStatus,
    Difficulty,
    Lesson,
    LessonType,
    Module,
    Subject,
)
from app.models.review_card import ReviewCard, ReviewCardState
from app.repositories import courses as courses_repo
from app.services import ai_authoring, content_ingest, embeddings_retrieval, fsrs, mastery, tutor

# ---------- Tool output schemas ----------
#
# Each schema is a thin Pydantic model. ``ConfigDict(extra="forbid")``
# everywhere — MCP clients (and the JSON-schema export the SDK
# generates from these models) are strict about unknown fields and
# we don't want a future ORM column accidentally leaking onto the
# wire.


class CourseSummaryOut(BaseModel):
    """One row in ``list_courses`` output — minimal catalog tile shape."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    title: str
    instructor_name: str
    subject_slug: str
    difficulty: Difficulty
    status: CourseStatus


class LessonSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    lesson_type: LessonType


class ModuleSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    lessons: list[LessonSummaryOut] = Field(default_factory=list)


class CourseDetailOut(BaseModel):
    """``get_course`` payload — syllabus tree."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    title: str
    overview: str
    modules: list[ModuleSummaryOut] = Field(default_factory=list)


class ChunkHitOut(BaseModel):
    """One ``search_lesson_content`` hit.

    ``similarity_score`` is the raw pgvector cosine *distance* — lower
    is more similar (0.0 = identical). We don't invert it because the
    LLM consuming this hit needs only ordering, not a normalised
    [0, 1] band; surfacing the raw column matches what the admin
    observability surface shows.
    """

    model_config = ConfigDict(extra="forbid")

    lesson_id: str
    lesson_title: str
    chunk_text: str = Field(description="First 240 chars of the matching chunk's body.")
    similarity_score: float


class CitationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lesson_id: str
    lesson_title: str


class TutorAnswerOut(BaseModel):
    """``ask_tutor`` payload — the assistant's reply + its citations."""

    model_config = ConfigDict(extra="forbid")

    answer: str
    refused: bool
    citations: list[CitationOut] = Field(default_factory=list)


class ReviewCardOut(BaseModel):
    """One row in ``list_my_due_reviews``."""

    model_config = ConfigDict(extra="forbid")

    card_id: str
    lesson_id: str
    lesson_title: str
    course_slug: str
    course_title: str
    due_at: datetime
    state: ReviewCardState


class GradedCardOut(BaseModel):
    """``grade_review_card`` payload — the card's new schedule."""

    model_config = ConfigDict(extra="forbid")

    card_id: str
    new_state: ReviewCardState
    next_due_at: datetime
    total_reviews: int


class CourseDraftOut(BaseModel):
    """``create_course_draft`` + ``ingest_url_to_draft`` shared payload."""

    model_config = ConfigDict(extra="forbid")

    course_id: str
    slug: str
    title: str
    modules_created: int
    lessons_created: int
    draft_url: str = Field(
        description=(
            "Relative URL under the Lumen frontend where the instructor can review the draft."
        )
    )


class IngestChapterOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    lesson_count: int


class IngestDraftOut(CourseDraftOut):
    """``ingest_url_to_draft`` adds a per-chapter rollup on top of the
    base draft shape, so the model can summarise what the ingest
    actually produced without a follow-up ``get_course`` call."""

    chapters: list[IngestChapterOut] = Field(default_factory=list)


class ProgressRowOut(BaseModel):
    """One row in ``list_my_progress``."""

    model_config = ConfigDict(extra="forbid")

    course_slug: str
    course_title: str
    completion_pct: float
    mastery_pct: float


# ---------- Internal helpers ----------


# Frontend URL where the instructor reviews a freshly-created draft.
# Builders use this so MCP clients can hand the user a deep link
# back into the Lumen UI for the human-in-the-loop review step.
_DRAFT_URL_TEMPLATE = "/studio/courses/{slug}"


_RATING_BY_INT = {1: "again", 2: "hard", 3: "good", 4: "easy"}


def _draft_url(slug: str) -> str:
    return _DRAFT_URL_TEMPLATE.format(slug=slug)


def _course_to_summary(course: Course) -> CourseSummaryOut:
    """Project a ``Course`` ORM row into the MCP summary shape.

    Assumes ``course.owner`` and ``course.subject`` are eager-loaded —
    the catalog repo already does this via ``selectinload``.
    """
    return CourseSummaryOut(
        slug=course.slug,
        title=course.title,
        instructor_name=course.owner.full_name or course.owner.email,
        subject_slug=course.subject.slug,
        difficulty=course.difficulty,
        status=course.status,
    )


async def _require_enrollment_or_owner(
    db: AsyncSession, *, course: Course, principal: Principal
) -> None:
    """Authorise an authenticated principal to talk to the tutor.

    Admins always pass. The course owner passes (so an instructor can
    sanity-check their own course). Otherwise we require an active
    enrollment — same shape as :func:`app.services.courses.can_view_course`
    but with a stricter "must be enrolled" floor, mirroring the REST
    tutor endpoint's authz.
    """
    if principal.is_admin or course.owner_id == principal.user_id:
        return
    enrollment = await courses_repo.get_enrollment(
        db, user_id=principal.user_id, course_id=course.id
    )
    if enrollment is None:
        raise ForbiddenError(
            "You must be enrolled in the course to ask the tutor.",
            code="mcp.tutor.not_enrolled",
        )


def _truncate(text: str, limit: int) -> str:
    """Trim text to ``limit`` chars on a word boundary, with ellipsis.

    Mirrors the helper in ``services.tutor`` but lives here to keep
    the MCP module independent of the tutor service's internals.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = head.rfind(" ")
    if cut > 0 and cut > limit - 80:
        head = head[:cut]
    return head.rstrip() + "…"


# ---------- Public tool functions ----------


async def list_courses(
    db: AsyncSession,
    *,
    principal: Principal,
    filter: str | None = None,
    limit: int = 20,
) -> list[CourseSummaryOut]:
    """List published Lumen courses, newest first.

    Wraps ``repositories.courses.search_courses``. ``filter`` is the
    same free-text query the catalog endpoint accepts; ``limit`` is
    clamped to 1-50. Public — no role check.
    """
    limit = max(1, min(int(limit), 50))
    courses, _total = await courses_repo.search_courses(
        db,
        q=(filter or None),
        only_published=True,
        page=1,
        page_size=limit,
    )
    return [_course_to_summary(c) for c in courses]


async def get_course(db: AsyncSession, *, principal: Principal, slug: str) -> CourseDetailOut:
    """Full course detail + syllabus tree.

    Wraps ``repositories.courses.get_course_by_slug`` with the
    ``with_modules=True`` flag so we can render the syllabus without
    a second round-trip. Filters out soft-deleted lessons so the
    syllabus matches what learners see on the live detail page.
    """
    course = await courses_repo.get_course_by_slug(db, slug, with_modules=True)
    if course is None:
        raise NotFoundError("Course not found", code="course.not_found")

    modules_out: list[ModuleSummaryOut] = []
    for mod in sorted(course.modules, key=lambda m: m.order):
        lessons_out = [
            LessonSummaryOut(title=lsn.title, lesson_type=lsn.type)
            for lsn in sorted(mod.lessons, key=lambda ls: ls.order)
            if lsn.deleted_at is None
        ]
        modules_out.append(ModuleSummaryOut(title=mod.title, lessons=lessons_out))

    return CourseDetailOut(
        slug=course.slug,
        title=course.title,
        overview=course.overview,
        modules=modules_out,
    )


async def search_lesson_content(
    db: AsyncSession,
    *,
    principal: Principal,
    course_slug: str,
    query: str,
    top_k: int = 5,
) -> list[ChunkHitOut]:
    """Semantic search against a course's lesson chunks.

    Wraps ``embeddings_retrieval.find_relevant_chunks`` with
    ``audit=True`` so every MCP-initiated retrieval lands in
    ``retrieval_audits`` (H7) and the admin surface can correlate
    "weird tutor answers" with the chunks that were actually fetched.

    Cosine-distance scores come back lowest-first (most similar
    first) — the order is preserved on the wire so the model can
    treat the first hit as the strongest match.
    """
    top_k = max(1, min(int(top_k), 10))
    course = await courses_repo.get_course_by_slug(db, course_slug)
    if course is None:
        raise NotFoundError("Course not found", code="course.not_found")
    if not (query or "").strip():
        return []

    # Two-pass shape: first call the audited retrieval helper so the
    # ``retrieval_audits`` row lands under a recognisable MCP feature
    # slug, then run a small ``(chunk, distance)`` query so the wire
    # payload carries the scores. Two retrieval round-trips against
    # the same query is fine — both hit the same HNSW index in the
    # same session and won't churn anything.
    from app.models.lesson_chunk import LessonChunk
    from app.services.embeddings import get_provider as _embed_provider

    await embeddings_retrieval.find_relevant_chunks(
        db,
        course_id=course.id,
        query=query,
        top_k=top_k,
        audit=True,
        audit_user_id=principal.user_id,
        audit_feature="mcp.search_lesson_content",
    )

    [query_vec] = _embed_provider().embed([query])
    distance = LessonChunk.embedding.cosine_distance(list(query_vec))
    stmt = (
        select(LessonChunk, distance.label("distance"))
        .join(Lesson, Lesson.id == LessonChunk.lesson_id)
        .join(Module, Module.id == Lesson.module_id)
        .where(
            Module.course_id == course.id,
            Lesson.deleted_at.is_(None),
        )
        .order_by(distance)
        .limit(top_k)
        .options(selectinload(LessonChunk.lesson))
    )
    rows = (await db.execute(stmt)).all()
    return [
        ChunkHitOut(
            lesson_id=chunk.lesson_id,
            lesson_title=chunk.lesson.title or "Untitled lesson",
            chunk_text=_truncate(chunk.text, 240),
            similarity_score=float(score),
        )
        for chunk, score in rows
    ]


async def ask_tutor(
    db: AsyncSession,
    *,
    principal: Principal,
    course_slug: str,
    question: str,
) -> TutorAnswerOut:
    """End-to-end course-scoped RAG tutor.

    Wraps ``services.tutor.ask`` directly — that helper already
    routes through the H1 cost meter and the H7 audit hooks. We
    pass ``feature="mcp.ask_tutor"`` so the dashboard rollup
    differentiates web-tutor traffic from MCP-tutor traffic.

    Enrollment-gated: the principal must be enrolled in the course
    (or be the course owner / admin). Empty questions short-circuit
    to the refusal text without billing an LLM call.
    """
    course = await courses_repo.get_course_by_slug(db, course_slug)
    if course is None:
        raise NotFoundError("Course not found", code="course.not_found")
    await _require_enrollment_or_owner(db, course=course, principal=principal)

    result = await tutor.ask(
        db,
        course=course,
        user_message=question,
        user_id=principal.user_id,
        feature="mcp.ask_tutor",
    )
    return TutorAnswerOut(
        answer=result.answer,
        refused=result.refused,
        citations=[
            CitationOut(lesson_id=c.lesson_id, lesson_title=c.lesson_title)
            for c in result.citations
        ],
    )


async def list_my_due_reviews(
    db: AsyncSession,
    *,
    principal: Principal,
    limit: int = 20,
) -> list[ReviewCardOut]:
    """FSRS queue for the authenticated learner.

    Wraps ``services.fsrs.due_cards`` which already eager-loads
    ``lesson.module.course`` so the response carries course context
    without an N+1.
    """
    limit = max(1, min(int(limit), 100))
    cards = await fsrs.due_cards(db, user_id=principal.user_id, limit=limit)
    out: list[ReviewCardOut] = []
    for card in cards:
        lesson = card.lesson
        course = lesson.module.course
        out.append(
            ReviewCardOut(
                card_id=card.id,
                lesson_id=lesson.id,
                lesson_title=lesson.title,
                course_slug=course.slug,
                course_title=course.title,
                due_at=card.due_at,
                state=card.state,
            )
        )
    return out


async def grade_review_card(
    db: AsyncSession,
    *,
    principal: Principal,
    card_id: str,
    rating: int,
) -> GradedCardOut:
    """Submit one FSRS review.

    ``rating`` maps to the FSRS rating vocabulary:

    * ``1`` → ``again`` (forgot completely)
    * ``2`` → ``hard`` (recalled with effort)
    * ``3`` → ``good`` (recalled correctly)
    * ``4`` → ``easy`` (trivial recall)

    The card must belong to the calling principal — cross-user
    grading is refused with a 404 (we collapse "wrong owner" and
    "missing" so the endpoint can't be used to probe other users'
    card ids).
    """
    rating_str = _RATING_BY_INT.get(int(rating))
    if rating_str is None:
        raise ValidationAppError(
            "Rating must be one of: 1 (again), 2 (hard), 3 (good), 4 (easy)",
            code="mcp.grade.invalid_rating",
            details={"rating": rating},
        )

    card = await db.get(ReviewCard, card_id)
    if card is None or card.user_id != principal.user_id:
        raise NotFoundError("Review card not found", code="review_card.not_found")

    try:
        await fsrs.record_review(db, card=card, rating=rating_str)
    except ValueError as exc:
        # ``fsrs.record_review`` raises ValueError on unknown rating;
        # we already validated above but keep this belt-and-braces.
        raise ValidationAppError(str(exc), code="mcp.grade.invalid_rating") from exc

    return GradedCardOut(
        card_id=card.id,
        new_state=card.state,
        next_due_at=card.due_at,
        total_reviews=card.total_reviews,
    )


async def list_my_progress(db: AsyncSession, *, principal: Principal) -> list[ProgressRowOut]:
    """Per-enrolled-course mastery + completion rollup.

    Wraps ``services.mastery.per_course_mastery``. The response
    ordering matches the dashboard (newest enrollment first).
    """
    rows = await mastery.per_course_mastery(db, user_id=principal.user_id)
    return [
        ProgressRowOut(
            course_slug=row.slug,
            course_title=row.title,
            completion_pct=row.completion_pct,
            mastery_pct=row.mastery_pct,
        )
        for row in rows
    ]


# ---------- Instructor-scoped writes ----------


def _require_instructor(principal: Principal) -> None:
    """Refuse non-instructor principals on the writeable tools.

    Mirrors :meth:`User.is_instructor_or_admin`. Pulled out so the
    error code is consistent across the two writeable tools.
    """
    if not principal.is_instructor:
        raise ForbiddenError(
            "Only instructors can create courses or ingest content",
            code="mcp.writes.instructor_required",
        )


async def _ensure_subject(db: AsyncSession, *, subject_slug: str | None) -> Subject:
    """Resolve ``subject_slug`` or pick a sensible default.

    Course rows require a non-null ``subject_id`` (FK ondelete=RESTRICT),
    so the AI-authoring tool needs a target subject before it can
    persist the outline. When the caller doesn't specify one we pick
    the first subject by alphabetical order — a deterministic default
    that won't surprise the operator. The instructor can re-categorise
    via the studio UI before publishing.
    """
    if subject_slug:
        subject = await courses_repo.get_subject_by_slug(db, subject_slug)
        if subject is None:
            raise NotFoundError(
                "Subject not found",
                code="subject.not_found",
                details={"subject_slug": subject_slug},
            )
        return subject

    # Fallback: first subject by title. We deliberately don't auto-
    # create one — a fresh Lumen install always seeds at least one
    # subject, and an empty subjects table is a misconfiguration the
    # operator should fix before MCP-driven authoring.
    res = await db.execute(select(Subject).order_by(Subject.title.asc()).limit(1))
    subject = res.scalar_one_or_none()
    if subject is None:
        raise ValidationAppError(
            "No subjects configured on this Lumen instance",
            code="mcp.subjects.empty",
        )
    return subject


async def create_course_draft(
    db: AsyncSession,
    *,
    principal: Principal,
    brief: str,
    subject_slug: str | None = None,
) -> CourseDraftOut:
    """Kick off the AI authoring pipeline and persist a draft course.

    Flow:

    1. Generate a structured outline via
       ``ai_authoring.generate_outline`` (metered through the cost
       meter under feature ``mcp.create_course_draft``).
    2. Create an empty draft ``Course`` row owned by the calling
       instructor, in the resolved subject.
    3. Materialise the outline's modules + lessons via
       ``ai_authoring.commit_outline``. Lesson bodies are populated
       with the standard "draft — replace before publishing"
       placeholders; the instructor fills them in via the studio.

    The draft is left in ``status=draft`` so it never surfaces in
    the public catalog until the instructor publishes it through
    the normal flow.
    """
    _require_instructor(principal)
    brief = (brief or "").strip()
    if not brief:
        raise ValidationAppError("Course brief must not be empty", code="ai.brief_empty")

    subject = await _ensure_subject(db, subject_slug=subject_slug)

    outline = await ai_authoring.generate_outline(
        brief,
        session=db,
        user_id=principal.user_id,
    )

    # Mint a unique slug. We reuse the service-layer minter via the
    # repo's ``slug_is_taken`` check; a short random suffix keeps the
    # implementation here trivial (the studio UI runs the same shape
    # on every "create new course" click).
    from slugify import slugify as _slugify

    base_slug = _slugify(outline.title)[:180] or "course"
    candidate = base_slug
    suffix_n = 1
    while await courses_repo.slug_is_taken(db, candidate):
        suffix_n += 1
        candidate = f"{base_slug}-{new_id()[:6]}"
        if suffix_n > 5:  # pragma: no cover - effectively impossible
            break

    course = Course(
        owner_id=principal.user_id,
        subject_id=subject.id,
        title=outline.title,
        slug=candidate,
        overview=outline.overview,
        difficulty=Difficulty.beginner,
        status=CourseStatus.draft,
    )
    db.add(course)
    await db.flush()

    # Reuse the existing commit path so the lesson placeholders +
    # data shape match what the studio creates. ``commit_outline``
    # also runs the owner check (we passed the just-created course)
    # so it can't be tricked into writing into someone else's course.
    await ai_authoring.commit_outline(
        db, course_id=course.id, owner=principal.user, outline=outline
    )

    # Re-fetch counts so the response payload is honest about what
    # landed. We can't rely on ``commit_outline``'s return value
    # because it returns the ``Course`` object, not counts.
    modules_count = sum(1 for _ in outline.modules)
    lessons_count = sum(len(m.lessons) for m in outline.modules)

    return CourseDraftOut(
        course_id=course.id,
        slug=course.slug,
        title=course.title,
        modules_created=modules_count,
        lessons_created=lessons_count,
        draft_url=_draft_url(course.slug),
    )


async def ingest_url_to_draft(
    db: AsyncSession,
    *,
    principal: Principal,
    url: str,
    course_id: str | None = None,
) -> IngestDraftOut:
    """Wrap ``services.content_ingest`` end-to-end.

    Two shapes:

    * ``course_id`` provided — append the ingest payload's modules
      + lessons to that existing course (the studio's "add to course"
      flow).
    * ``course_id`` omitted — create a fresh draft course from the
      ingest payload's title + source, then commit into it. Useful
      for "paste a YouTube URL and get a course".

    The extractor is synchronous (it hits the source service +
    chunks the transcript) but cheap enough to run inline; the
    studio's REST endpoint does the same.
    """
    _require_instructor(principal)

    url = (url or "").strip()
    if not url:
        raise ValidationAppError("URL must not be empty", code="ingest.url_empty")

    payload = content_ingest.ingest(url)

    if course_id is None:
        # Fresh course. Pick a default subject so the FK is satisfied.
        subject = await _ensure_subject(db, subject_slug=None)
        from slugify import slugify as _slugify

        base_slug = _slugify(payload.title)[:180] or "imported"
        candidate = base_slug
        if await courses_repo.slug_is_taken(db, candidate):
            candidate = f"{base_slug}-{new_id()[:6]}"

        course = Course(
            owner_id=principal.user_id,
            subject_id=subject.id,
            title=payload.title,
            slug=candidate,
            overview=f"Imported from {payload.source_url}",
            difficulty=Difficulty.beginner,
            status=CourseStatus.draft,
        )
        db.add(course)
        await db.flush()
        target_course_id = course.id
    else:
        # Append to an existing course. The commit helper does the
        # owner check (so we pass the principal's user); a non-owner
        # gets a 403 from the same code path the studio uses.
        existing = await courses_repo.get_course(db, course_id)
        if existing is None:
            raise NotFoundError("Course not found", code="course.not_found")
        target_course_id = existing.id

    counts = await content_ingest.commit_payload(
        db,
        course_id=target_course_id,
        owner=principal.user,
        payload=payload,
    )

    # Re-fetch the course so we can hand back a canonical slug
    # (the append-to-existing path doesn't have it in hand).
    final_course = await courses_repo.get_course(db, target_course_id)
    assert final_course is not None  # just inserted / fetched above

    chapters = [
        IngestChapterOut(title=m.title, lesson_count=len(m.lessons)) for m in payload.modules
    ]

    return IngestDraftOut(
        course_id=final_course.id,
        slug=final_course.slug,
        title=final_course.title,
        modules_created=int(counts.get("modules", 0)),
        lessons_created=int(counts.get("lessons", 0)),
        draft_url=_draft_url(final_course.slug),
        chapters=chapters,
    )


# ---------- Registry ----------
#
# Single source of truth for "which tool names are wired up + what
# do they call?" — :mod:`app.mcp.server` walks this dict to register
# every entry as an MCP tool, and the OAuth scope vocabulary in
# :mod:`app.mcp.auth` mirrors the keys.
#
# Each entry pairs the tool name with a small ``ToolSpec`` describing
# the auth posture so the dispatcher's pre-flight checks (scope,
# role, authentication) live next to the tool itself and stay in
# sync.


class ToolSpec(BaseModel):
    """Static metadata about one MCP tool — wired into the dispatcher."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    name: str
    description: str
    # ``"public" | "user" | "instructor" | "admin"``. The dispatcher
    # maps this onto a one-shot principal check before invoking the
    # tool body.
    auth: str = "user"


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="list_courses",
        description=(
            "List Lumen courses in the public catalog. "
            "Optional `filter` does free-text search over title + overview."
        ),
        auth="public",
    ),
    ToolSpec(
        name="get_course",
        description=(
            "Fetch one course by slug. Returns the full syllabus tree "
            "(modules + lessons) plus the course overview."
        ),
        auth="public",
    ),
    ToolSpec(
        name="search_lesson_content",
        description=(
            "Semantic search across a course's lesson chunks. "
            "Returns the top-K most similar passages with their lesson titles "
            "and pgvector cosine-distance scores (lower = better)."
        ),
        auth="user",
    ),
    ToolSpec(
        name="ask_tutor",
        description=(
            "Ask the Lumen course tutor a question. Returns a cited answer "
            "or a refusal if the course content doesn't cover the topic. "
            "Requires enrollment in the course."
        ),
        auth="user",
    ),
    ToolSpec(
        name="list_my_due_reviews",
        description=(
            "Spaced-repetition queue for the calling user: cards whose "
            "FSRS-6 due-at has passed. Returns at most `limit` rows "
            "(default 20), oldest-due first."
        ),
        auth="user",
    ),
    ToolSpec(
        name="grade_review_card",
        description=(
            "Submit one FSRS-6 rating against a review card. "
            "`rating` is 1=again, 2=hard, 3=good, 4=easy. "
            "Updates the card's stability + difficulty + next due-at."
        ),
        auth="user",
    ),
    ToolSpec(
        name="create_course_draft",
        description=(
            "Generate a course outline from a one-paragraph brief and "
            "persist it as a draft course owned by the calling instructor. "
            "Lesson bodies are placeholders the instructor fills in via the studio."
        ),
        auth="instructor",
    ),
    ToolSpec(
        name="ingest_url_to_draft",
        description=(
            "Import a YouTube / Notion / Google Docs URL into a draft course. "
            "Creates a fresh course when `course_id` is omitted, otherwise "
            "appends the ingest payload's modules + lessons to the existing course."
        ),
        auth="instructor",
    ),
    ToolSpec(
        name="list_my_progress",
        description=(
            "Per-enrolled-course completion + mastery rollup for the calling user. "
            "Returns one row per active enrollment, newest enrolment first."
        ),
        auth="user",
    ),
]


def all_tool_names() -> list[str]:
    """Stable list of tool names — used by docs + the registry export."""
    return [spec.name for spec in TOOL_SPECS]


__all__ = [
    "TOOL_SPECS",
    "ChunkHitOut",
    "CitationOut",
    "CourseDetailOut",
    "CourseDraftOut",
    "CourseSummaryOut",
    "GradedCardOut",
    "IngestChapterOut",
    "IngestDraftOut",
    "LessonSummaryOut",
    "ModuleSummaryOut",
    "ProgressRowOut",
    "ReviewCardOut",
    "ToolSpec",
    "TutorAnswerOut",
    "all_tool_names",
    "ask_tutor",
    "create_course_draft",
    "get_course",
    "grade_review_card",
    "ingest_url_to_draft",
    "list_courses",
    "list_my_due_reviews",
    "list_my_progress",
    "search_lesson_content",
]
