"""S4.6/S4.7/S4.8/S4.10 — clone_course service + POST /courses/{key}/clone.

Covers the orchestrator end-to-end: resolve+authorize (403/404 existence-hide
split), idempotency, atomic materialization with server-written immutable
provenance, owner self-enroll, audit ×2 + origin notification, the forbidden-
state isolation invariant (FR-CLONE-07), quotas (429/409/413/disabled), read-time
provenance anonymization + ``origin_available`` (DR-19), and the zero-chunk /
publish-schedules-index embedding contract (FR-CLONE-08).

Tests run against the real Postgres stack. ``clone_enabled`` ships OFF, so every
API-path test flips it on via a Settings override (conftest force-clears the
cache); the disabled-flag test asserts the 404 with it off.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.ids import new_id
from app.core.security import hash_password
from app.models.audit import AuditEvent
from app.models.course import (
    Course,
    CourseStatus,
    Enrollment,
    Lesson,
    LessonProgress,
    ModerationState,
    Module,
    Review,
    Subject,
    Visibility,
)
from app.models.notification import Notification, NotificationKind
from app.models.user import Role, User

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Settings override helpers (conftest force-clears the cache on env change).
# ---------------------------------------------------------------------------


@pytest.fixture
def clone_on(monkeypatch):
    """Enable the clone feature flag for the test (default OFF)."""
    monkeypatch.setenv("CLONE_ENABLED", "true")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Source-tree builders (direct DB so we can plant forbidden state precisely).
# ---------------------------------------------------------------------------


async def _user(db: AsyncSession, *, full_name: str = "Origin Owner") -> User:
    u = User(
        email=f"u-{new_id()[:10]}@lumen.test",
        password_hash=hash_password("Password!1234"),
        full_name=full_name,
        role=Role.user,
    )
    db.add(u)
    await db.flush()
    return u


async def _subject(db: AsyncSession) -> Subject:
    s = Subject(title="Subj", slug=f"subj-{uuid.uuid4().hex[:8]}")
    db.add(s)
    await db.flush()
    return s


async def _source_course(
    db: AsyncSession,
    owner: User,
    *,
    listed: bool = True,
    with_tree: bool = True,
) -> Course:
    """A publicly-listed (by default) source course with a 2-module tree.

    ``with_tree`` adds a module with a live text lesson + a quiz lesson, a second
    module whose only lesson is soft-deleted (so it drops on clone), and a
    preview lesson (forced non-preview on clone).
    """
    subject = await _subject(db)
    course = Course(
        owner_id=owner.id,
        subject_id=subject.id,
        title=f"Source {uuid.uuid4().hex[:6]}",
        slug=f"src-{uuid.uuid4().hex[:10]}",
        overview="A great course",
        learning_outcomes=["Learn X", "Learn Y"],
        cover_url="http://localhost:9000/lumen-assets/cover/abc/x.png",
        difficulty="beginner",
        status=CourseStatus.published if listed else CourseStatus.draft,
        visibility=Visibility.public if listed else Visibility.private,
        moderation_state=ModerationState.approved if listed else ModerationState.none,
        is_featured=True,  # never copied
        published_at=func.now(),  # never copied
    )
    db.add(course)
    await db.flush()

    if with_tree:
        m1 = Module(course_id=course.id, title="Module 1", description="d1", order=0)
        db.add(m1)
        await db.flush()
        db.add(
            Lesson(
                module_id=m1.id,
                title="Intro",
                order=0,
                type="text",
                is_preview=True,  # forced False on clone
                data={"type": "text", "body_markdown": "hello"},
            )
        )
        db.add(
            Lesson(
                module_id=m1.id,
                title="Quiz",
                order=1,
                type="quiz",
                data={
                    "type": "quiz",
                    "pass_score": 70,
                    "questions": [
                        {
                            "id": "q1",
                            "prompt": "2+2?",
                            "kind": "single",
                            "choices": [
                                {"id": "a", "text": "4"},
                                {"id": "b", "text": "5"},
                            ],
                            "answer_keys": ["a"],
                        }
                    ],
                },
            )
        )
        # Module 2 — its only lesson is soft-deleted → module drops entirely.
        m2 = Module(course_id=course.id, title="Empty after delete", description="", order=1)
        db.add(m2)
        await db.flush()
        db.add(
            Lesson(
                module_id=m2.id,
                title="Gone",
                order=0,
                type="text",
                deleted_at=func.now(),
                data={"type": "text", "body_markdown": "gone"},
            )
        )
    await db.flush()
    return course


async def _login(client, user: User) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "Password!1234"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------------------------------------------------------------------------
# S4.6 — create / authorize / idempotency / audit / rollback
# ---------------------------------------------------------------------------


async def test_clone_public_course_creates_independent_copy(client, db_session, clone_on):
    owner = await _user(db_session, full_name="Ada Lovelace")
    source = await _source_course(db_session, owner)
    cloner = await _user(db_session)
    await db_session.commit()

    headers = await _login(client, cloner)
    r = await client.post(f"/api/v1/courses/{source.slug}/clone", headers=headers)
    assert r.status_code == 201, r.text
    assert r.headers.get("Location", "").startswith("/api/v1/courses/")
    body = r.json()

    assert body["is_clone"] is True
    assert body["origin"]["origin_course_id"] == source.id
    assert body["origin"]["origin_owner_name"] == "Ada Lovelace"
    assert body["status"] == "draft"
    assert body["visibility"] == "private"
    assert body["slug"] != source.slug
    assert body["is_featured"] is False
    assert body["published_at"] is None

    # The clone is a real, owned, independent course.
    clone = await db_session.get(Course, body["id"])
    assert clone is not None
    assert clone.owner_id == cloner.id
    assert clone.moderation_state == ModerationState.none
    # Module 2 dropped (soft-deleted-only); Module 1 with 2 lessons survived.
    mods = (
        (await db_session.execute(select(Module).where(Module.course_id == clone.id)))
        .scalars()
        .all()
    )
    assert len(mods) == 1
    lessons = (
        (
            await db_session.execute(
                select(Lesson)
                .join(Module, Module.id == Lesson.module_id)
                .where(Module.course_id == clone.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(lessons) == 2
    assert all(le.is_preview is False for le in lessons)  # FR-CLONE-04
    # Dense 0-based orders.
    assert sorted(le.order for le in lessons) == [0, 1]


async def test_clone_private_source_403_for_viewer_who_can_see(client, db_session, clone_on):
    """Caller clones their OWN private draft → 403 (can see, not clonable)."""
    owner = await _user(db_session)
    source = await _source_course(db_session, owner, listed=False)
    await db_session.commit()

    headers = await _login(client, owner)
    r = await client.post(f"/api/v1/courses/{source.slug}/clone", headers=headers)
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "clone.source_not_clonable"


async def test_clone_private_source_404_for_stranger(client, db_session, clone_on):
    """A stranger cloning a private course → 404 (no existence leak)."""
    owner = await _user(db_session)
    source = await _source_course(db_session, owner, listed=False)
    stranger = await _user(db_session)
    await db_session.commit()

    headers = await _login(client, stranger)
    r = await client.post(f"/api/v1/courses/{source.slug}/clone", headers=headers)
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "course.not_found"


async def test_clone_anonymous_401(client, db_session, clone_on):
    owner = await _user(db_session)
    source = await _source_course(db_session, owner)
    await db_session.commit()

    r = await client.post(f"/api/v1/courses/{source.slug}/clone")
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "auth.required"


async def test_clone_quarantined_source_404(client, db_session, clone_on):
    """A quarantined source is never publicly listed → existence-hide 404."""
    owner = await _user(db_session)
    source = await _source_course(db_session, owner)
    source.quarantined = True
    cloner = await _user(db_session)
    await db_session.commit()

    headers = await _login(client, cloner)
    r = await client.post(f"/api/v1/courses/{source.slug}/clone", headers=headers)
    assert r.status_code == 404, r.text


async def test_clone_never_copies_forbidden_state(client, db_session, clone_on):
    """FR-CLONE-07 — enrollments/reviews/progress/soft-deleted lessons/
    is_featured/published_at never cross the boundary."""
    owner = await _user(db_session)
    source = await _source_course(db_session, owner)
    # Plant forbidden state on the source.
    learner = await _user(db_session)
    enr = Enrollment(user_id=learner.id, course_id=source.id)
    db_session.add(enr)
    await db_session.flush()
    db_session.add(Review(author_id=learner.id, course_id=source.id, rating=5, body="great"))
    a_lesson = (
        (
            await db_session.execute(
                select(Lesson)
                .join(Module, Module.id == Lesson.module_id)
                .where(Module.course_id == source.id, Lesson.deleted_at.is_(None))
            )
        )
        .scalars()
        .first()
    )
    db_session.add(LessonProgress(enrollment_id=enr.id, lesson_id=a_lesson.id))
    cloner = await _user(db_session)
    await db_session.commit()

    headers = await _login(client, cloner)
    r = await client.post(f"/api/v1/courses/{source.slug}/clone", headers=headers)
    assert r.status_code == 201, r.text
    clone_id = r.json()["id"]

    clone = await db_session.get(Course, clone_id)
    assert clone.is_featured is False
    assert clone.published_at is None
    # Only the cloner's self-enrollment exists on the clone.
    enrollments = (
        (await db_session.execute(select(Enrollment).where(Enrollment.course_id == clone_id)))
        .scalars()
        .all()
    )
    assert len(enrollments) == 1
    assert enrollments[0].user_id == cloner.id
    assert enrollments[0].is_self is True
    # No reviews, no lesson_progress on the clone.
    reviews = (
        (await db_session.execute(select(Review).where(Review.course_id == clone_id)))
        .scalars()
        .all()
    )
    assert reviews == []
    clone_lessons = (
        (
            await db_session.execute(
                select(Lesson)
                .join(Module, Module.id == Lesson.module_id)
                .where(Module.course_id == clone_id)
            )
        )
        .scalars()
        .all()
    )
    clone_lesson_ids = {le.id for le in clone_lessons}
    progress = (
        (
            await db_session.execute(
                select(LessonProgress).where(LessonProgress.lesson_id.in_(clone_lesson_ids))
            )
        )
        .scalars()
        .all()
    )
    assert progress == []
    # No soft-deleted lesson copied (2 live lessons only).
    assert all(le.deleted_at is None for le in clone_lessons)
    assert len(clone_lessons) == 2


async def test_clone_auto_enrolls_caller_is_self(client, db_session, clone_on):
    owner = await _user(db_session)
    source = await _source_course(db_session, owner)
    cloner = await _user(db_session)
    await db_session.commit()

    headers = await _login(client, cloner)
    r = await client.post(f"/api/v1/courses/{source.slug}/clone", headers=headers)
    assert r.status_code == 201
    enr = (
        await db_session.execute(
            select(Enrollment).where(
                Enrollment.course_id == r.json()["id"], Enrollment.user_id == cloner.id
            )
        )
    ).scalar_one()
    assert enr.is_self is True


async def test_self_clone_allowed(client, db_session, clone_on):
    """FR-CLONE-15 — owner clones their own PUBLIC course; provenance points back."""
    owner = await _user(db_session, full_name="Self Owner")
    source = await _source_course(db_session, owner)
    await db_session.commit()

    headers = await _login(client, owner)
    r = await client.post(f"/api/v1/courses/{source.slug}/clone", headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["origin"]["origin_course_id"] == source.id
    clone = await db_session.get(Course, body["id"])
    assert clone.origin_owner_id == owner.id
    # No course_cloned notification on a self-clone.
    notes = (
        (
            await db_session.execute(
                select(Notification).where(Notification.kind == NotificationKind.course_cloned)
            )
        )
        .scalars()
        .all()
    )
    assert notes == []


async def test_clone_idempotency_key_returns_same_course(client, db_session, clone_on):
    owner = await _user(db_session)
    source = await _source_course(db_session, owner)
    cloner = await _user(db_session)
    await db_session.commit()

    headers = await _login(client, cloner)
    key = {"Idempotency-Key": "fixed-key-123", **headers}
    r1 = await client.post(f"/api/v1/courses/{source.slug}/clone", headers=key)
    r2 = await client.post(f"/api/v1/courses/{source.slug}/clone", headers=key)
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]
    # Exactly one clone created.
    count = (
        await db_session.execute(
            select(func.count(Course.id)).where(Course.origin_course_id == source.id)
        )
    ).scalar_one()
    assert count == 1


async def test_clone_writes_audit_events(client, db_session, clone_on):
    owner = await _user(db_session)
    source = await _source_course(db_session, owner)
    cloner = await _user(db_session)
    await db_session.commit()

    headers = await _login(client, cloner)
    r = await client.post(f"/api/v1/courses/{source.slug}/clone", headers=headers)
    assert r.status_code == 201
    clone_id = r.json()["id"]

    cloned = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.action == "course.cloned", AuditEvent.target_id == clone_id
            )
        )
    ).scalar_one()
    assert cloned.actor_id == cloner.id
    assert cloned.data["origin_course_id"] == source.id
    assert cloned.data["lessons_copied"] == 2
    assert cloned.data["modules_copied"] == 1
    assert cloned.data["modules_dropped"] == 1
    # Second event targets the origin.
    by_other = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.action == "course.cloned_by_other", AuditEvent.target_id == source.id
            )
        )
    ).scalar_one()
    assert by_other.data["clone_course_id"] == clone_id
    # Notification to the origin owner.
    note = (
        await db_session.execute(
            select(Notification).where(
                Notification.user_id == owner.id,
                Notification.kind == NotificationKind.course_cloned,
            )
        )
    ).scalar_one()
    assert note.data["clone_course_id"] == clone_id


async def test_clone_provenance_not_client_writable(client, db_session, clone_on):
    """End-to-end immutability: PATCH the clone with a provenance field → 422."""
    owner = await _user(db_session)
    source = await _source_course(db_session, owner)
    cloner = await _user(db_session)
    await db_session.commit()

    headers = await _login(client, cloner)
    r = await client.post(f"/api/v1/courses/{source.slug}/clone", headers=headers)
    clone_id = r.json()["id"]
    patch = await client.patch(
        f"/api/v1/courses/{clone_id}",
        json={"origin_owner_name_snapshot": "Forged Author"},
        headers=headers,
    )
    assert patch.status_code == 422, patch.text


async def test_clone_rolls_back_on_failure(db_session, clone_on, monkeypatch):
    """FR-CLONE-22 — a materialization failure leaves no orphan course.

    Driven at the service layer (the faithful unit for the atomicity claim): a
    failure injected AFTER the first course flush propagates out of
    ``clone_course``; the caller's transaction rollback leaves no orphan.
    """
    owner = await _user(db_session)
    source = await _source_course(db_session, owner)
    cloner = await _user(db_session)
    await db_session.commit()

    from app.services import courses as courses_service

    async def _boom(*args, **kwargs):
        raise RuntimeError("inject failure after partial insert")

    # Fail on the per-module flush AFTER the course row was added — proves the
    # whole tree rolls back, not just that we never started.
    monkeypatch.setattr(courses_service, "Module", _RaisingModule)

    source_id = source.id
    with pytest.raises(RuntimeError):
        await courses_service.clone_course(db_session, caller=cloner, source_key=source.slug)
    await db_session.rollback()
    db_session.expunge_all()

    count = (
        await db_session.execute(
            select(func.count(Course.id)).where(Course.origin_course_id == source_id)
        )
    ).scalar_one()
    assert count == 0


class _RaisingModule:
    """A Module stand-in whose construction raises — injected to fail the clone
    materialization after the course row was already added (rollback proof)."""

    def __init__(self, *args, **kwargs):
        raise RuntimeError("inject failure after partial insert")


# ---------------------------------------------------------------------------
# S4.7 — quotas
# ---------------------------------------------------------------------------


async def test_clone_disabled_flag(client, db_session):
    """clone_enabled OFF → 404 clone.disabled (no feature-probe). No override."""
    owner = await _user(db_session)
    source = await _source_course(db_session, owner)
    cloner = await _user(db_session)
    await db_session.commit()

    get_settings.cache_clear()  # type: ignore[attr-defined]
    headers = await _login(client, cloner)
    r = await client.post(f"/api/v1/courses/{source.slug}/clone", headers=headers)
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "clone.disabled"


async def test_clone_owned_cap(client, db_session, clone_on, monkeypatch):
    monkeypatch.setenv("CLONE_OWNED_CAP", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    owner = await _user(db_session)
    source = await _source_course(db_session, owner)
    cloner = await _user(db_session)
    # Cloner already owns one live course → at the cap.
    existing_subj = await _subject(db_session)
    db_session.add(
        Course(
            owner_id=cloner.id,
            subject_id=existing_subj.id,
            title="Already owned",
            slug=f"owned-{uuid.uuid4().hex[:8]}",
            overview="",
        )
    )
    await db_session.commit()

    headers = await _login(client, cloner)
    r = await client.post(f"/api/v1/courses/{source.slug}/clone", headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "clone.course_limit"
    get_settings.cache_clear()  # type: ignore[attr-defined]


async def test_clone_source_too_large(client, db_session, clone_on, monkeypatch):
    monkeypatch.setenv("CLONE_MAX_LESSONS", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    owner = await _user(db_session)
    source = await _source_course(db_session, owner)  # has 2 live lessons
    cloner = await _user(db_session)
    await db_session.commit()

    headers = await _login(client, cloner)
    r = await client.post(f"/api/v1/courses/{source.slug}/clone", headers=headers)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "clone.source_too_large"
    get_settings.cache_clear()  # type: ignore[attr-defined]


async def test_clone_rate_limited(client, db_session, clone_on, monkeypatch):
    """DB-COUNT window backstop: prior course.cloned audit rows trip 429."""
    monkeypatch.setenv("CLONE_PER_HOUR", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    owner = await _user(db_session)
    source = await _source_course(db_session, owner)
    cloner = await _user(db_session)
    # Seed one prior clone audit row for this actor within the window.
    db_session.add(AuditEvent(actor_id=cloner.id, action="course.cloned", target_type="course"))
    await db_session.commit()

    headers = await _login(client, cloner)
    r = await client.post(f"/api/v1/courses/{source.slug}/clone", headers=headers)
    assert r.status_code == 429, r.text
    assert r.json()["error"]["code"] == "clone.rate_limited"
    get_settings.cache_clear()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# S4.8 — read-time provenance anonymization + origin_available (DR-19)
# ---------------------------------------------------------------------------


async def test_origin_available_true_when_source_listed(client, db_session, clone_on):
    owner = await _user(db_session)
    source = await _source_course(db_session, owner)
    cloner = await _user(db_session)
    await db_session.commit()

    headers = await _login(client, cloner)
    r = await client.post(f"/api/v1/courses/{source.slug}/clone", headers=headers)
    clone_id = r.json()["id"]
    detail = await client.get(f"/api/v1/courses/{clone_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["origin"]["origin_available"] is True


async def test_origin_available_false_when_source_unlisted(client, db_session, clone_on):
    owner = await _user(db_session)
    source = await _source_course(db_session, owner)
    cloner = await _user(db_session)
    await db_session.commit()

    headers = await _login(client, cloner)
    r = await client.post(f"/api/v1/courses/{source.slug}/clone", headers=headers)
    clone_id = r.json()["id"]
    # Delist the source.
    source.visibility = Visibility.private
    await db_session.commit()

    detail = await client.get(f"/api/v1/courses/{clone_id}", headers=headers)
    assert detail.json()["origin"]["origin_available"] is False
    # Snapshot title still renders.
    assert detail.json()["origin"]["origin_title"] == source.title


async def test_origin_owner_anonymized_when_deleted(client, db_session, clone_on):
    """DR-19 read-time: a tombstoned origin owner renders the deleted-user label
    even with the raw snapshot still stored (no scrub ran)."""
    owner = await _user(db_session, full_name="Real Name")
    source = await _source_course(db_session, owner)
    cloner = await _user(db_session)
    await db_session.commit()

    headers = await _login(client, cloner)
    r = await client.post(f"/api/v1/courses/{source.slug}/clone", headers=headers)
    clone_id = r.json()["id"]
    # Tombstone the origin owner WITHOUT touching the snapshot column.
    from datetime import UTC, datetime

    owner.deleted_at = datetime.now(UTC)
    owner.is_active = False
    await db_session.commit()

    detail = await client.get(f"/api/v1/courses/{clone_id}", headers=headers)
    assert detail.json()["origin"]["origin_owner_name"] == "common.deletedUser"


async def test_origin_owner_anonymized_when_id_null(client, db_session, clone_on):
    """origin_owner_id IS NULL (hard purge) → deleted-user label."""
    owner = await _user(db_session)
    source = await _source_course(db_session, owner)
    cloner = await _user(db_session)
    await db_session.commit()

    headers = await _login(client, cloner)
    r = await client.post(f"/api/v1/courses/{source.slug}/clone", headers=headers)
    clone_id = r.json()["id"]
    clone = await db_session.get(Course, clone_id)
    clone.origin_owner_id = None
    await db_session.commit()

    detail = await client.get(f"/api/v1/courses/{clone_id}", headers=headers)
    assert detail.json()["origin"]["origin_owner_name"] == "common.deletedUser"


# ---------------------------------------------------------------------------
# S4.10 — embeddings never copied; regenerate on publish
# ---------------------------------------------------------------------------


async def test_clone_copies_zero_chunks(client, db_session, clone_on):
    """FR-CLONE-08 — a fresh clone has zero LessonChunk rows even when the
    source had embeddings."""
    from app.models.lesson_chunk import LessonChunk

    owner = await _user(db_session)
    source = await _source_course(db_session, owner)
    src_lesson = (
        (
            await db_session.execute(
                select(Lesson)
                .join(Module, Module.id == Lesson.module_id)
                .where(Module.course_id == source.id, Lesson.deleted_at.is_(None))
            )
        )
        .scalars()
        .first()
    )
    # Plant a chunk on a source lesson (chunks are per-lesson, no course_id).
    db_session.add(
        LessonChunk(
            lesson_id=src_lesson.id,
            chunk_index=0,
            text="src chunk",
            embedding=[0.0] * 384,
        )
    )
    cloner = await _user(db_session)
    await db_session.commit()

    headers = await _login(client, cloner)
    r = await client.post(f"/api/v1/courses/{source.slug}/clone", headers=headers)
    clone_id = r.json()["id"]

    # Count chunks bound to any lesson under the clone (join lessons→modules).
    clone_chunks = (
        await db_session.execute(
            select(func.count(LessonChunk.id))
            .join(Lesson, Lesson.id == LessonChunk.lesson_id)
            .join(Module, Module.id == Lesson.module_id)
            .where(Module.course_id == clone_id)
        )
    ).scalar_one()
    assert clone_chunks == 0


async def test_clone_publish_schedules_index(client, db_session, clone_on, monkeypatch):
    """Publishing the clone fires _schedule_embedding_index for the clone's id."""
    owner = await _user(db_session)
    source = await _source_course(db_session, owner)
    cloner = await _user(db_session)
    await db_session.commit()

    headers = await _login(client, cloner)
    r = await client.post(f"/api/v1/courses/{source.slug}/clone", headers=headers)
    clone_id = r.json()["id"]

    scheduled: list[str] = []
    from app.services import courses as courses_service

    monkeypatch.setattr(
        courses_service, "_schedule_embedding_index", lambda cid: scheduled.append(cid)
    )
    pub = await client.post(f"/api/v1/courses/{clone_id}/publish", headers=headers)
    assert pub.status_code == 200, pub.text
    assert clone_id in scheduled
