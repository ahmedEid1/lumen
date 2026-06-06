"""Happy-path coverage for the nine MCP tools in :mod:`app.mcp.tools`.

Lumen v2 Phase I1. Each test seeds the minimal fixtures the tool
needs (course, enrolment, review card, …), builds a :class:`Principal`
that mirrors what the dispatcher would resolve, and calls the tool
function directly. We skip the FastMCP wire format here — the tool
functions are the unit of business logic, and ``test_mcp_server_smoke``
covers the protocol layer separately.

All LLM-touching tools run with ``LLM_PROVIDER=noop`` so the suite
stays network-free. The noop provider's deterministic refusal /
prefix sentinels (see ``app/services/llm.py``) are what we assert
against in ``test_ask_tutor``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.mcp import tools as mcp_tools
from app.mcp.principal import Principal
from app.models.course import (
    Course,
    CourseStatus,
    Difficulty,
    Enrollment,
    Lesson,
    LessonType,
    ModerationState,
    Module,
    Subject,
    Visibility,
)
from app.models.review_card import ReviewCard, ReviewCardState
from app.models.user import Role, User

# ---------- Fixtures ----------


@pytest.fixture(autouse=True)
def _force_noop_providers(monkeypatch):
    """Pin both embedding + LLM providers to noop for every MCP tool test.

    Same shape as ``test_tutor.py``'s ``_force_noop_providers`` —
    the noop providers return deterministic canned responses so we
    can assert on shape without burning tokens or depending on
    outbound network.
    """
    monkeypatch.setenv("EMBEDDING_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "noop")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _principal_for(user: User, *, scopes: list[str] | None = None) -> Principal:
    """Build a :class:`Principal` that mirrors what the dispatcher would resolve.

    Tests pass this straight to the tool functions, skipping the
    transport layer. ``scopes=None`` defaults to the wildcard so the
    dispatcher's scope check would pass for any tool — useful when a
    test only cares about the business logic, not the gate.
    """
    return Principal(
        user_id=user.id,
        role=user.role,
        scopes=list(scopes or ["*"]),
        client_id="test_client",
        user=user,
    )


async def _seed_published_course(
    db: AsyncSession,
    *,
    instructor: User,
    lessons: list[tuple[str, str]] | None = None,
    title_suffix: str | None = None,
) -> Course:
    """Persist a Subject + Course + Module + N text lessons, publicly listed.

    ``lessons`` is a list of ``(title, body)`` tuples; defaults to one
    placeholder lesson so the publish-time minimum-content guard
    passes without callers needing to know about it.

    S2 / ADR-0026: ``status==published`` alone keeps a course PRIVATE
    (published-private self-learn). For the course to appear in
    ``list_courses`` / the public catalog it must satisfy the
    ``is_publicly_listed`` predicate — ``visibility==public`` AND
    ``status==published`` AND ``moderation_state==approved``. We seed
    those directly here (the /share + admin /approve endpoints live on
    the HTTP path) so the MCP catalog tools see the course, mirroring
    how S2's own service-level tests seed visibility.
    """
    suffix = title_suffix or uuid.uuid4().hex[:6]
    subject = Subject(title=f"Subj {suffix}", slug=f"subj-{suffix}")
    db.add(subject)
    await db.flush()

    course = Course(
        owner_id=instructor.id,
        subject_id=subject.id,
        title=f"MCP Course {suffix}",
        slug=f"mcp-course-{suffix}",
        overview="MCP test course overview",
        difficulty=Difficulty.beginner,
        status=CourseStatus.published,
        visibility=Visibility.public,
        moderation_state=ModerationState.approved,
        published_at=datetime.now(UTC),
    )
    db.add(course)
    await db.flush()

    module = Module(course_id=course.id, title="Module 1", order=0)
    db.add(module)
    await db.flush()

    lesson_specs = lessons or [("Intro", "Welcome to the course.")]
    for idx, (title, body) in enumerate(lesson_specs):
        lesson = Lesson(
            module_id=module.id,
            title=title,
            type=LessonType.text,
            order=idx,
            data={"type": "text", "body_markdown": body},
        )
        db.add(lesson)
    await db.flush()
    # Re-query with explicit eager loads. Without this, callers that
    # touch ``course.modules[0].lessons[0]`` trigger a sync lazy-load
    # in an async session and hit ``MissingGreenlet`` — async ORM
    # demands every relationship be loaded up front (or via
    # ``awaitable_attrs``). ``db.refresh(course)`` re-reads the row's
    # columns but does not populate relationships.
    loaded = await db.execute(
        select(Course)
        .options(selectinload(Course.modules).selectinload(Module.lessons))
        .where(Course.id == course.id)
    )
    return loaded.scalar_one()


# ---------- list_courses ----------


@pytest.mark.asyncio
async def test_list_courses_returns_published_summaries(
    db_session: AsyncSession, make_user
) -> None:
    instructor = await make_user(role=Role.instructor)
    student = await make_user(role=Role.student)
    course = await _seed_published_course(db_session, instructor=instructor)
    await db_session.commit()

    result = await mcp_tools.list_courses(db_session, principal=_principal_for(student), limit=10)
    assert any(row.slug == course.slug for row in result)
    hit = next(row for row in result if row.slug == course.slug)
    assert hit.title == course.title
    assert hit.status == CourseStatus.published
    assert hit.instructor_name == instructor.full_name


@pytest.mark.asyncio
async def test_list_courses_filter_narrows_results(db_session: AsyncSession, make_user) -> None:
    instructor = await make_user(role=Role.instructor)
    student = await make_user(role=Role.student)
    a = await _seed_published_course(db_session, instructor=instructor, title_suffix="alpha")
    b = await _seed_published_course(db_session, instructor=instructor, title_suffix="omega")
    await db_session.commit()

    # Search for the unique suffix in course A; result must include
    # only A, not B.
    out = await mcp_tools.list_courses(
        db_session, principal=_principal_for(student), filter="alpha"
    )
    slugs = {row.slug for row in out}
    assert a.slug in slugs
    assert b.slug not in slugs


# ---------- get_course ----------


@pytest.mark.asyncio
async def test_get_course_returns_syllabus(db_session: AsyncSession, make_user) -> None:
    instructor = await make_user(role=Role.instructor)
    student = await make_user(role=Role.student)
    course = await _seed_published_course(
        db_session,
        instructor=instructor,
        lessons=[("L1", "first"), ("L2", "second")],
    )
    await db_session.commit()

    detail = await mcp_tools.get_course(
        db_session, principal=_principal_for(student), slug=course.slug
    )
    assert detail.slug == course.slug
    assert detail.title == course.title
    assert len(detail.modules) == 1
    assert [ls.title for ls in detail.modules[0].lessons] == ["L1", "L2"]


@pytest.mark.asyncio
async def test_get_course_unknown_slug_404s(db_session: AsyncSession, make_user) -> None:
    student = await make_user(role=Role.student)
    from app.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await mcp_tools.get_course(
            db_session,
            principal=_principal_for(student),
            slug="does-not-exist",
        )


# ---------- ask_tutor ----------


@pytest.mark.asyncio
async def test_ask_tutor_requires_enrollment(db_session: AsyncSession, make_user) -> None:
    """Non-enrolled student is refused with a clean ForbiddenError."""
    from app.core.errors import ForbiddenError

    instructor = await make_user(role=Role.instructor)
    student = await make_user(role=Role.student)
    course = await _seed_published_course(db_session, instructor=instructor)
    await db_session.commit()

    with pytest.raises(ForbiddenError):
        await mcp_tools.ask_tutor(
            db_session,
            principal=_principal_for(student),
            course_slug=course.slug,
            question="explain something",
        )


@pytest.mark.asyncio
async def test_ask_tutor_enrolled_path(db_session: AsyncSession, make_user) -> None:
    """Enrolled student gets a structured TutorAnswerOut.

    The noop provider returns the refusal sentinel when there are no
    indexed lesson chunks; we don't ingest embeddings here (that
    would pull in the embedding pipeline + pgvector index), so the
    expected path is a refusal — but the shape of the response is
    what we're asserting.
    """
    instructor = await make_user(role=Role.instructor)
    student = await make_user(role=Role.student)
    course = await _seed_published_course(db_session, instructor=instructor)
    db_session.add(Enrollment(user_id=student.id, course_id=course.id))
    await db_session.commit()

    result = await mcp_tools.ask_tutor(
        db_session,
        principal=_principal_for(student),
        course_slug=course.slug,
        question="What is this about?",
    )
    assert isinstance(result.answer, str)
    # No chunks indexed → empty-retrieval guardrail fires → refused.
    assert result.refused is True
    assert result.citations == []


# ---------- list_my_due_reviews ----------


@pytest.mark.asyncio
async def test_list_my_due_reviews_returns_due_only(db_session: AsyncSession, make_user) -> None:
    instructor = await make_user(role=Role.instructor)
    student = await make_user(role=Role.student)
    course = await _seed_published_course(
        db_session,
        instructor=instructor,
        lessons=[("L1", "x"), ("L2", "y")],
    )
    db_session.add(Enrollment(user_id=student.id, course_id=course.id))
    await db_session.flush()

    # Re-fetch lessons since we need their ids.
    from sqlalchemy import select

    res = await db_session.execute(select(Lesson).where(Lesson.module_id == course.modules[0].id))
    lessons = list(res.scalars().all())

    now = datetime.now(UTC)
    # Due card.
    due_card = ReviewCard(
        user_id=student.id,
        lesson_id=lessons[0].id,
        stability=1.0,
        difficulty=5.0,
        state=ReviewCardState.review,
        step=None,
        due_at=now - timedelta(hours=1),
        last_reviewed_at=None,
        total_reviews=0,
    )
    # Future card — must NOT show up.
    future_card = ReviewCard(
        user_id=student.id,
        lesson_id=lessons[1].id,
        stability=1.0,
        difficulty=5.0,
        state=ReviewCardState.review,
        step=None,
        due_at=now + timedelta(days=7),
        last_reviewed_at=None,
        total_reviews=0,
    )
    db_session.add_all([due_card, future_card])
    await db_session.commit()

    queue = await mcp_tools.list_my_due_reviews(db_session, principal=_principal_for(student))
    queue_ids = {row.card_id for row in queue}
    assert due_card.id in queue_ids
    assert future_card.id not in queue_ids


# ---------- grade_review_card ----------


@pytest.mark.asyncio
async def test_grade_review_card_advances_schedule(db_session: AsyncSession, make_user) -> None:
    instructor = await make_user(role=Role.instructor)
    student = await make_user(role=Role.student)
    course = await _seed_published_course(db_session, instructor=instructor)
    lesson = course.modules[0].lessons[0]
    db_session.add(Enrollment(user_id=student.id, course_id=course.id))

    now = datetime.now(UTC)
    card = ReviewCard(
        user_id=student.id,
        lesson_id=lesson.id,
        stability=0.0,
        difficulty=0.0,
        state=ReviewCardState.new,
        step=0,
        due_at=now,
        last_reviewed_at=None,
        total_reviews=0,
    )
    db_session.add(card)
    await db_session.commit()

    result = await mcp_tools.grade_review_card(
        db_session,
        principal=_principal_for(student),
        card_id=card.id,
        rating=3,  # "good"
    )
    assert result.card_id == card.id
    assert result.total_reviews == 1
    # FSRS bumps a "good"-rated new card forward — due_at must move
    # strictly past the original ``now``.
    assert result.next_due_at >= now


@pytest.mark.asyncio
async def test_grade_review_card_rejects_other_users_card(
    db_session: AsyncSession, make_user
) -> None:
    from app.core.errors import NotFoundError

    instructor = await make_user(role=Role.instructor)
    owner = await make_user(role=Role.student)
    intruder = await make_user(role=Role.student)
    course = await _seed_published_course(db_session, instructor=instructor)
    lesson = course.modules[0].lessons[0]
    db_session.add(Enrollment(user_id=owner.id, course_id=course.id))

    card = ReviewCard(
        user_id=owner.id,
        lesson_id=lesson.id,
        stability=0.0,
        difficulty=0.0,
        state=ReviewCardState.new,
        step=0,
        due_at=datetime.now(UTC),
        total_reviews=0,
    )
    db_session.add(card)
    await db_session.commit()

    # Intruder tries to grade owner's card; we collapse to a 404 so
    # the endpoint can't be used to probe other users' card ids.
    with pytest.raises(NotFoundError):
        await mcp_tools.grade_review_card(
            db_session,
            principal=_principal_for(intruder),
            card_id=card.id,
            rating=3,
        )


@pytest.mark.asyncio
async def test_grade_review_card_rejects_bad_rating(db_session: AsyncSession, make_user) -> None:
    from app.core.errors import ValidationAppError

    student = await make_user(role=Role.student)
    with pytest.raises(ValidationAppError):
        await mcp_tools.grade_review_card(
            db_session,
            principal=_principal_for(student),
            card_id="nonexistent",
            rating=99,
        )


# ---------- list_my_progress ----------


@pytest.mark.asyncio
async def test_list_my_progress_returns_enrolled_courses(
    db_session: AsyncSession, make_user
) -> None:
    instructor = await make_user(role=Role.instructor)
    student = await make_user(role=Role.student)
    course = await _seed_published_course(db_session, instructor=instructor)
    db_session.add(Enrollment(user_id=student.id, course_id=course.id))
    await db_session.commit()

    rows = await mcp_tools.list_my_progress(db_session, principal=_principal_for(student))
    assert any(r.course_slug == course.slug for r in rows)
    hit = next(r for r in rows if r.course_slug == course.slug)
    # Fresh enrollment, no completion / quizzes — both rollups are 0.
    assert hit.completion_pct == 0.0
    assert hit.mastery_pct == 0.0


# ---------- create_course_draft ----------


@pytest.mark.asyncio
async def test_create_course_draft_denies_suspended_principal(
    db_session: AsyncSession, make_user
) -> None:
    # S1.6 / ADR-0025 §D5: the MCP write gate is `can_author` (any active
    # user), not the instructor role — so the only denial axis is suspension.
    from app.core.errors import ForbiddenError

    suspended = await make_user(role=Role.user)
    suspended.is_active = False
    db_session.add(Subject(title="Programming", slug="programming"))
    await db_session.commit()

    with pytest.raises(ForbiddenError) as exc:
        await mcp_tools.create_course_draft(
            db_session,
            principal=_principal_for(suspended),
            brief="Teach Python basics",
        )
    assert exc.value.code == "mcp.writes.author_required"


@pytest.mark.asyncio
async def test_create_course_draft_allows_user_role_principal(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    # S1.6: a plain `user`-role principal (formerly denied as non-instructor)
    # can now create a draft. Script a minimal outline so the test is
    # network-free (same pattern as the persist test below).
    import json as _json

    from app.services import llm as _llm_module

    user = await make_user(role=Role.user)
    db_session.add(Subject(title="Programming", slug="programming"))
    await db_session.commit()

    minimal_outline = {
        "title": "Intro to Python",
        "overview": "A friendly intro.",
        "modules": [{"title": "Setup", "lessons": [{"title": "Install", "type": "text"}]}],
    }

    class _OneShotProvider:
        name = "scripted-outline"

        async def chat(self, messages, temperature: float = 0.2) -> str:
            del messages, temperature
            return _json.dumps(minimal_outline)

        async def chat_with_usage(self, messages, temperature: float = 0.2):
            text = await self.chat(messages, temperature=temperature)
            return _llm_module.ChatResponse(
                text=text, prompt_tokens=32, completion_tokens=32, model="scripted-outline"
            )

    monkeypatch.setattr(_llm_module, "get_provider", lambda: _OneShotProvider())

    result = await mcp_tools.create_course_draft(
        db_session,
        principal=_principal_for(user),
        brief="Teach Python basics to absolute beginners",
        subject_slug="programming",
    )
    assert result.course_id
    assert result.modules_created >= 1


@pytest.mark.asyncio
async def test_create_course_draft_persists_draft(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """Instructor mints a draft; we script a minimal outline reply so
    the authoring service's JSON-schema validation is satisfied without
    the test depending on a real LLM. The noop provider returns plain
    prose (citation-prefix sentinel) which the outline parser rejects
    as malformed — mirroring ``test_ai_authoring.py``'s scripted-reply
    pattern.
    """
    import json as _json

    from app.services import llm as _llm_module

    instructor = await make_user(role=Role.instructor)
    db_session.add(Subject(title="Programming", slug="programming"))
    await db_session.commit()

    minimal_outline = {
        "title": "Python Basics for Absolute Beginners",
        "overview": "A friendly introduction to Python 3 for first-timers.",
        "modules": [
            {
                "title": "Getting Set Up",
                "lessons": [
                    {"title": "Install Python", "type": "text"},
                    {"title": "Hello, World", "type": "text"},
                ],
            }
        ],
    }

    class _OneShotProvider:
        name = "scripted-outline"

        async def chat(self, messages, temperature: float = 0.2) -> str:
            del messages, temperature
            return _json.dumps(minimal_outline)

        async def chat_with_usage(self, messages, temperature: float = 0.2):
            # ai_authoring routes through llm_call_log.call_logged which
            # prefers chat_with_usage when available. Provide a minimal
            # ChatResponse-shaped fallback so the metered path works.
            text = await self.chat(messages, temperature=temperature)
            return _llm_module.ChatResponse(
                text=text,
                prompt_tokens=64,
                completion_tokens=64,
                model="scripted-outline",
            )

    # ai_authoring imports ``llm_service.get_provider()`` lazily —
    # patching the function on ``llm_module`` is the only target.
    monkeypatch.setattr(_llm_module, "get_provider", lambda: _OneShotProvider())

    result = await mcp_tools.create_course_draft(
        db_session,
        principal=_principal_for(instructor),
        brief="Teach Python basics to absolute beginners",
        subject_slug="programming",
    )
    assert result.course_id
    assert result.slug
    assert result.modules_created >= 1
    assert result.lessons_created >= 1
    assert result.draft_url.startswith("/studio/courses/")

    # Verify the row really landed in the DB.
    from app.repositories import courses as courses_repo

    persisted = await courses_repo.get_course(db_session, result.course_id, with_modules=True)
    assert persisted is not None
    assert persisted.owner_id == instructor.id
    assert persisted.status == CourseStatus.draft


# ---------- search_lesson_content ----------


@pytest.mark.asyncio
async def test_search_lesson_content_unknown_course_404s(
    db_session: AsyncSession, make_user
) -> None:
    from app.core.errors import NotFoundError

    student = await make_user(role=Role.student)
    with pytest.raises(NotFoundError):
        await mcp_tools.search_lesson_content(
            db_session,
            principal=_principal_for(student),
            course_slug="missing",
            query="anything",
        )


@pytest.mark.asyncio
async def test_search_lesson_content_empty_query_returns_empty(
    db_session: AsyncSession, make_user
) -> None:
    """An empty query short-circuits to ``[]`` without hitting the DB."""
    instructor = await make_user(role=Role.instructor)
    student = await make_user(role=Role.student)
    course = await _seed_published_course(db_session, instructor=instructor)
    await db_session.commit()

    result = await mcp_tools.search_lesson_content(
        db_session,
        principal=_principal_for(student),
        course_slug=course.slug,
        query="   ",
    )
    assert result == []


# ---------- ToolSpec registry ----------


def test_tool_specs_match_dispatch_table() -> None:
    """Every ``TOOL_SPECS`` entry has a matching dispatcher entry and vice versa.

    Catches the most likely drift bug: a tool added to ``tools.py``
    that the server module forgets to wire up (or removed without
    cleaning up the spec list).
    """
    from app.mcp import server as mcp_server

    spec_names = {spec.name for spec in mcp_tools.TOOL_SPECS}
    dispatch_names = set(mcp_server._DISPATCH.keys())
    assert spec_names == dispatch_names, (
        f"TOOL_SPECS / dispatcher drift: "
        f"only in specs={spec_names - dispatch_names}, "
        f"only in dispatch={dispatch_names - spec_names}"
    )
    # And the count is the nine the spec calls for.
    assert len(mcp_tools.TOOL_SPECS) == 9
