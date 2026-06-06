"""W12 regression: seeded "published" demo courses must be PUBLICLY LISTED.

Root cause this guards against: on a FRESH stack there is no S2-era backfill
migration to upgrade legacy rows, so a seed that only sets ``status=published``
leaves ``visibility=private`` / ``moderation_state=none`` (the column defaults)
and the course is existence-hidden — an anonymous ``GET /api/v1/courses/{slug}``
404s and the catalog list omits it. The CI ``tutor-citations.spec.ts`` E2E hit
exactly this against ``fastapi-from-zero`` and blocked the 2.0.0 deploy.

Every seed bundle's intended-to-be-public course must therefore seed the FULL
publicly-listed state (R-C1′ / ``app.services.visibility.is_publicly_listed``),
mirroring what ``moderation.approve_course`` writes: ``visibility=public`` AND
``moderation_state=approved`` (on top of ``status=published`` + not deleted +
not quarantined).

The intentionally-PRIVATE seed content (the agentic-demo ``draft`` self-critique
anchor course) stays private and is asserted to remain unlisted.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.course import (
    Course,
    CourseStatus,
    Difficulty,
    LessonType,
    ModerationState,
    Module,
    Subject,
    Tag,
    Visibility,
)
from app.models.user import Role, User
from app.services.visibility import is_publicly_listed

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------- #
# Helpers                                                               #
# --------------------------------------------------------------------- #


async def _instructor(db: AsyncSession, email: str) -> User:
    user = User(
        email=email,
        password_hash=hash_password("Teach!2026"),
        full_name="Seed Instructor",
        role=Role.instructor,
    )
    db.add(user)
    await db.flush()
    return user


async def _assert_publicly_visible(client: AsyncClient, slug: str) -> None:
    """An ANONYMOUS caller can GET the course by slug AND see it in the catalog."""
    detail = await client.get(f"/api/v1/courses/{slug}")
    assert detail.status_code == 200, (
        f"anonymous GET /courses/{slug} expected 200, got {detail.status_code} "
        f"({detail.text}) — course is existence-hidden (not publicly listed)"
    )
    assert detail.json()["slug"] == slug

    listing = await client.get("/api/v1/courses", params={"page_size": 100})
    assert listing.status_code == 200
    slugs = {item["slug"] for item in listing.json()["items"]}
    assert slug in slugs, f"catalog list omitted {slug}; listed slugs={sorted(slugs)}"


def _assert_listed_state(course: Course) -> None:
    """The exact four-column listed state the catalog/ACL predicate requires."""
    assert course.status == CourseStatus.published
    assert course.visibility == Visibility.public
    assert course.moderation_state == ModerationState.approved
    assert course.deleted_at is None
    assert getattr(course, "quarantined", False) is False
    assert is_publicly_listed(course) is True


# --------------------------------------------------------------------- #
# Base seed (app.cli) — the FastAPI course the CI E2E anonymously fetches #
# --------------------------------------------------------------------- #


async def test_base_seed_fastapi_course_is_publicly_listed(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    """``fastapi-from-zero`` (built by ``app.cli._seed``) lists for anonymous.

    This is the exact course + slug the CI ``tutor-citations.spec.ts`` E2E
    anonymously GETs; a 404 here is the deploy-blocking failure.
    """
    programming = Subject(slug="programming", title="Programming")
    db_session.add(programming)
    py = Tag(slug="python", name="Python")
    fa = Tag(slug="fastapi", name="FastAPI")
    beg = Tag(slug="beginner", name="Beginner")
    db_session.add_all([py, fa, beg])
    instructor = await _instructor(db_session, "cli-instructor@lumen.test")

    # Mirror app.cli._seed's Course construction (the only public surface that
    # builds this course); the seed sets the full listed state post-fix.
    from datetime import UTC, datetime

    course = Course(
        owner_id=instructor.id,
        subject_id=programming.id,
        title="FastAPI from Zero",
        slug="fastapi-from-zero",
        overview="Learn to build production-ready APIs with FastAPI.",
        difficulty=Difficulty.beginner,
        cover_url=None,
        status=CourseStatus.published,
        visibility=Visibility.public,
        moderation_state=ModerationState.approved,
        published_at=datetime.now(UTC),
        is_featured=True,
    )
    course.tags = [py, fa, beg]
    db_session.add(course)
    await db_session.flush()
    module = Module(course_id=course.id, title="Getting started", order=0)
    db_session.add(module)
    await db_session.commit()

    _assert_listed_state(course)
    await _assert_publicly_visible(client, "fastapi-from-zero")


# --------------------------------------------------------------------- #
# rag_from_scratch_demo bundle                                          #
# --------------------------------------------------------------------- #


async def test_rag_seed_course_is_publicly_listed(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    from app.seeds.rag_from_scratch_demo import apply

    programming = Subject(slug="programming", title="Programming")
    db_session.add(programming)
    demo_tag = Tag(slug="demo", name="Demo")
    db_session.add(demo_tag)
    instructor = await _instructor(db_session, "rag-pub-instructor@lumen.test")

    course = await apply(
        db_session, instructor=instructor, programming=programming, tags={"demo": demo_tag}
    )
    await db_session.commit()

    _assert_listed_state(course)
    await _assert_publicly_visible(client, "rag-from-scratch")


# --------------------------------------------------------------------- #
# ts_variance_demo bundle                                               #
# --------------------------------------------------------------------- #


async def test_ts_variance_seed_course_is_publicly_listed(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    from app.seeds.ts_variance_demo import apply

    programming = Subject(slug="programming", title="Programming")
    db_session.add(programming)
    ts_tag = Tag(slug="typescript", name="TypeScript")
    demo_tag = Tag(slug="demo", name="Demo")
    db_session.add_all([ts_tag, demo_tag])
    instructor = await _instructor(db_session, "ts-pub-instructor@lumen.test")

    course = await apply(
        db_session,
        instructor=instructor,
        programming=programming,
        tags={"typescript": ts_tag, "demo": demo_tag},
    )
    await db_session.commit()

    _assert_listed_state(course)
    await _assert_publicly_visible(client, "typescript-variance")


# --------------------------------------------------------------------- #
# agentic_demo bundle — a published catalog course + the private draft   #
# --------------------------------------------------------------------- #


async def test_agentic_demo_published_course_is_publicly_listed(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    """A ``_NEW_COURSES`` catalog course built by ``_ensure_course`` lists."""
    from app.seeds.agentic_demo import _NEW_COURSES, _ensure_course

    spec = _NEW_COURSES[0]  # data-engineering-foundations
    subject = Subject(slug=spec["subject_slug"], title="Data Science")
    db_session.add(subject)
    py = Tag(slug="python", name="Python")
    beg = Tag(slug="beginner", name="Beginner")
    db_session.add_all([py, beg])
    instructor = await _instructor(db_session, "agentic-pub-instructor@lumen.test")

    course = await _ensure_course(
        db_session,
        spec=spec,
        subjects={spec["subject_slug"]: subject},
        tags={"python": py, "beginner": beg},
        instructor=instructor,
    )
    await db_session.commit()

    _assert_listed_state(course)
    await _assert_publicly_visible(client, spec["slug"])


async def test_agentic_demo_draft_course_stays_private(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    """The intentionally-PRIVATE self-critique draft anchor must NOT list.

    Guards the other direction: the fix must not over-publish the draft course
    the studio replay surface anchors on (status=draft, owner-only). The seed
    builds it at ``agentic_demo._DRAFT_COURSE_SLUG`` with ``status=draft`` and
    the default private/none visibility — mirrored inline here so the assertion
    doesn't depend on the trace-table seeding path.
    """
    from app.seeds.agentic_demo import _DRAFT_COURSE_SLUG

    programming = Subject(slug="programming", title="Programming")
    db_session.add(programming)
    instructor = await _instructor(db_session, "agentic-draft-instructor@lumen.test")

    course = Course(
        owner_id=instructor.id,
        subject_id=programming.id,
        title="AI Tutor Design Patterns",
        slug=_DRAFT_COURSE_SLUG,
        overview="Drafted by the Lumen self-critique authoring agent.",
        difficulty=Difficulty.advanced,
        status=CourseStatus.draft,
        is_featured=False,
    )
    db_session.add(course)
    await db_session.commit()

    # Defaults must leave it unlisted.
    assert course.status == CourseStatus.draft
    assert course.visibility == Visibility.private
    assert course.moderation_state == ModerationState.none
    assert is_publicly_listed(course) is False

    detail = await client.get(f"/api/v1/courses/{_DRAFT_COURSE_SLUG}")
    assert detail.status_code == 404, "the private draft course must stay existence-hidden"

    listing = await client.get("/api/v1/courses", params={"page_size": 100})
    slugs = {item["slug"] for item in listing.json()["items"]}
    assert _DRAFT_COURSE_SLUG not in slugs


# --------------------------------------------------------------------- #
# demo bundle (_build_course) — the public catalog courses               #
# --------------------------------------------------------------------- #


async def test_demo_build_course_helper_sets_listed_state(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    """``demo._build_course`` (intro-to-python et al.) lists for anonymous."""
    from app.seeds.demo import _build_course

    programming = Subject(slug="programming", title="Programming")
    db_session.add(programming)
    demo_tag = Tag(slug="demo", name="Demo")
    db_session.add(demo_tag)
    instructor = await _instructor(db_session, "demo-pub-instructor@lumen.test")

    course = await _build_course(
        db_session,
        owner=instructor,
        subject=programming,
        tags=[demo_tag],
        slug="intro-to-python",
        title="Intro to Python",
        overview="Hands-on introduction to Python for absolute beginners.",
        learning_outcomes=["Write and run small Python scripts"],
        difficulty=Difficulty.beginner,
        modules_spec=[
            {
                "title": "Basics",
                "lessons": [{"title": "Hello", "type": LessonType.text, "data": {"type": "text"}}],
            }
        ],
    )
    await db_session.commit()

    _assert_listed_state(course)
    await _assert_publicly_visible(client, "intro-to-python")
