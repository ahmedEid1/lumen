"""S2.3 — Central authorizer ``app.services.visibility``.

Two layers:

* **Pure (no DB)** — the ``is_publicly_listed`` truth table (R-C1′: lists iff
  ``public AND published AND approved AND not soft-deleted AND not quarantined``)
  and ``can_publish_public`` (R-CAP).

* **DB-backed (runs under ``make test.api``)** — the Python≡SQL parity test
  (``is_publicly_listed`` filtered in Python equals ``publicly_listed_sql()``
  filtered in SQL over the same mixed fixture set) plus the viewer-aware
  predicates (``can_view_course``/``can_learn_in_course``/``can_enroll``) and
  the ``retrieval_acl_clause`` owner-branch.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import CourseStatus, ModerationState, Visibility
from app.services import visibility as vis


# --------------------------------------------------------------------------
# A lightweight stand-in for a loaded Course row (is_publicly_listed is pure:
# it reads already-loaded columns, no DB / no viewer — NFR-PERF-2).
# --------------------------------------------------------------------------
@dataclass
class _FakeCourse:
    visibility: str = Visibility.public
    status: str = CourseStatus.published
    moderation_state: str = ModerationState.approved
    deleted_at: object | None = None
    quarantined: bool = False
    owner_id: str = "owner-1"


# --------------------------------------------------------------------------
# Pure: is_publicly_listed truth table (R-C1′)
# --------------------------------------------------------------------------


def test_is_publicly_listed_happy_path():
    assert vis.is_publicly_listed(_FakeCourse()) is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("visibility", Visibility.private),
        ("status", CourseStatus.draft),
        ("status", CourseStatus.archived),
        ("moderation_state", ModerationState.none),
        ("moderation_state", ModerationState.pending_review),
        ("moderation_state", ModerationState.rejected),
        ("moderation_state", ModerationState.delisted),
    ],
)
def test_is_publicly_listed_each_axis_blocks(field, value):
    c = _FakeCourse()
    setattr(c, field, value)
    assert vis.is_publicly_listed(c) is False


def test_is_publicly_listed_soft_deleted_blocks():
    import datetime as dt

    c = _FakeCourse(deleted_at=dt.datetime.now(dt.UTC))
    assert vis.is_publicly_listed(c) is False


def test_is_publicly_listed_pending_is_not_listed():
    """R-C1′: a public+published+pending_review course never lists."""
    c = _FakeCourse(moderation_state=ModerationState.pending_review)
    assert vis.is_publicly_listed(c) is False


def test_is_publicly_listed_none_is_not_listed():
    """The dead spec rule ``IN (none, approved)`` is purged — none never lists."""
    c = _FakeCourse(moderation_state=ModerationState.none)
    assert vis.is_publicly_listed(c) is False


def test_can_publish_public_is_active_only():
    @dataclass
    class _U:
        is_active: bool

        def is_admin(self) -> bool:
            return False

    assert vis.can_publish_public(_U(is_active=True)) is True
    assert vis.can_publish_public(_U(is_active=False)) is False


def test_can_clone_equals_is_publicly_listed():
    assert vis.can_clone(_FakeCourse(), viewer=None) is True
    assert vis.can_clone(_FakeCourse(visibility=Visibility.private), viewer=None) is False


# --------------------------------------------------------------------------
# DB-backed: Python≡SQL parity + viewer predicates
# --------------------------------------------------------------------------


async def _seed_owner_subject(db: AsyncSession):
    from app.core.ids import new_id
    from app.core.security import hash_password
    from app.models.course import Subject
    from app.models.user import Role, User

    owner = User(
        email=f"o-{new_id()[:8]}@lumen.test",
        password_hash=hash_password("Password!1234"),
        full_name="Owner",
        role=Role.instructor,
    )
    subject = Subject(title="S", slug=f"s-{new_id()[:8]}")
    db.add_all([owner, subject])
    await db.commit()
    await db.refresh(owner)
    await db.refresh(subject)
    return owner, subject


async def _mk_course(db, owner, subject, *, visibility, status, moderation_state, deleted=False):
    from datetime import UTC, datetime

    from app.core.ids import new_id
    from app.models.course import Course

    c = Course(
        owner_id=owner.id,
        subject_id=subject.id,
        title=f"C {new_id()[:6]}",
        slug=f"c-{new_id()[:8]}",
        overview="",
        visibility=visibility,
        status=status,
        moderation_state=moderation_state,
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


@pytest.mark.asyncio
async def test_python_sql_parity(db_session: AsyncSession):
    """is_publicly_listed (Python) selects the same ids as publicly_listed_sql()."""
    from itertools import product

    from app.models.course import Course

    owner, subject = await _seed_owner_subject(db_session)
    listed_ids: set[str] = set()
    for v, s, m in product(
        [Visibility.public, Visibility.private],
        [CourseStatus.draft, CourseStatus.published, CourseStatus.archived],
        [
            ModerationState.none,
            ModerationState.pending_review,
            ModerationState.approved,
            ModerationState.rejected,
            ModerationState.delisted,
        ],
    ):
        c = await _mk_course(db_session, owner, subject, visibility=v, status=s, moderation_state=m)
        if vis.is_publicly_listed(c):
            listed_ids.add(c.id)
    # Add a soft-deleted public+published+approved (Python excludes it).
    await _mk_course(
        db_session,
        owner,
        subject,
        visibility=Visibility.public,
        status=CourseStatus.published,
        moderation_state=ModerationState.approved,
        deleted=True,
    )

    sql_ids = {
        row[0]
        for row in (
            await db_session.execute(select(Course.id).where(vis.publicly_listed_sql()))
        ).all()
    }
    assert sql_ids == listed_ids
    # Exactly one combination lists: public+published+approved (+ live).
    assert len(listed_ids) == 1


@pytest.mark.asyncio
async def test_can_view_course_branches(db_session: AsyncSession):
    owner, subject = await _seed_owner_subject(db_session)
    from app.core.ids import new_id
    from app.core.security import hash_password
    from app.models.user import Role, User

    listed = await _mk_course(
        db_session,
        owner,
        subject,
        visibility=Visibility.public,
        status=CourseStatus.published,
        moderation_state=ModerationState.approved,
    )
    private = await _mk_course(
        db_session,
        owner,
        subject,
        visibility=Visibility.private,
        status=CourseStatus.published,
        moderation_state=ModerationState.none,
    )
    stranger = User(
        email=f"x-{new_id()[:8]}@lumen.test",
        password_hash=hash_password("Password!1234"),
        full_name="Stranger",
        role=Role.student,
    )
    admin = User(
        email=f"a-{new_id()[:8]}@lumen.test",
        password_hash=hash_password("Password!1234"),
        full_name="Admin",
        role=Role.admin,
    )
    db_session.add_all([stranger, admin])
    await db_session.commit()
    await db_session.refresh(stranger)
    await db_session.refresh(admin)

    # Listed -> anyone, incl. anon.
    assert await vis.can_view_course(db_session, listed, None) is True
    assert await vis.can_view_course(db_session, listed, stranger) is True
    # Private -> owner, admin yes; stranger + anon no.
    assert await vis.can_view_course(db_session, private, owner) is True
    assert await vis.can_view_course(db_session, private, admin) is True
    assert await vis.can_view_course(db_session, private, stranger) is False
    assert await vis.can_view_course(db_session, private, None) is False


@pytest.mark.asyncio
async def test_can_view_course_grandfathered_enrollment(db_session: AsyncSession):
    """An enrolled learner keeps access to a now-private course (R-VIS-13)."""
    from app.models.course import Enrollment

    owner, subject = await _seed_owner_subject(db_session)
    private = await _mk_course(
        db_session,
        owner,
        subject,
        visibility=Visibility.private,
        status=CourseStatus.archived,
        moderation_state=ModerationState.none,
    )
    from app.core.ids import new_id
    from app.core.security import hash_password
    from app.models.user import Role, User

    learner = User(
        email=f"l-{new_id()[:8]}@lumen.test",
        password_hash=hash_password("Password!1234"),
        full_name="Learner",
        role=Role.student,
    )
    db_session.add(learner)
    await db_session.commit()
    await db_session.refresh(learner)
    db_session.add(Enrollment(user_id=learner.id, course_id=private.id))
    await db_session.commit()

    assert await vis.can_view_course(db_session, private, learner) is True


@pytest.mark.asyncio
async def test_can_learn_in_course_owner_self_learn(db_session: AsyncSession):
    """Owner can self-learn a private/draft course (FR-LEARN-01)."""
    owner, subject = await _seed_owner_subject(db_session)
    draft = await _mk_course(
        db_session,
        owner,
        subject,
        visibility=Visibility.private,
        status=CourseStatus.draft,
        moderation_state=ModerationState.none,
    )
    assert await vis.can_learn_in_course(db_session, draft, owner) is True


@pytest.mark.asyncio
async def test_can_enroll(db_session: AsyncSession):
    owner, subject = await _seed_owner_subject(db_session)
    listed = await _mk_course(
        db_session,
        owner,
        subject,
        visibility=Visibility.public,
        status=CourseStatus.published,
        moderation_state=ModerationState.approved,
    )
    private = await _mk_course(
        db_session,
        owner,
        subject,
        visibility=Visibility.private,
        status=CourseStatus.published,
        moderation_state=ModerationState.none,
    )
    from app.core.ids import new_id
    from app.core.security import hash_password
    from app.models.user import Role, User

    stranger = User(
        email=f"x-{new_id()[:8]}@lumen.test",
        password_hash=hash_password("Password!1234"),
        full_name="Stranger",
        role=Role.student,
    )
    db_session.add(stranger)
    await db_session.commit()
    await db_session.refresh(stranger)

    assert await vis.can_enroll(db_session, listed, stranger) == (True, None)
    assert await vis.can_enroll(db_session, private, owner) == (True, None)
    ok, code = await vis.can_enroll(db_session, private, stranger)
    assert ok is False
    assert code == "enrollment.not_available"


@pytest.mark.asyncio
async def test_retrieval_acl_clause_owner_branch(db_session: AsyncSession):
    """retrieval_acl_clause: own private course is eligible; others' are not."""
    from app.models.course import Course

    owner_a, subject = await _seed_owner_subject(db_session)
    owner_b, _ = await _seed_owner_subject(db_session)

    a_private = await _mk_course(
        db_session,
        owner_a,
        subject,
        visibility=Visibility.private,
        status=CourseStatus.draft,
        moderation_state=ModerationState.none,
    )
    a_public = await _mk_course(
        db_session,
        owner_a,
        subject,
        visibility=Visibility.public,
        status=CourseStatus.published,
        moderation_state=ModerationState.approved,
    )
    b_private = await _mk_course(
        db_session,
        owner_b,
        subject,
        visibility=Visibility.private,
        status=CourseStatus.draft,
        moderation_state=ModerationState.none,
    )

    ids = {
        row[0]
        for row in (
            await db_session.execute(select(Course.id).where(vis.retrieval_acl_clause(owner_a.id)))
        ).all()
    }
    assert a_private.id in ids  # own private -> eligible
    assert a_public.id in ids  # listed -> eligible
    assert b_private.id not in ids  # other user's private -> never


@pytest.mark.asyncio
async def test_retrieval_acl_clause_none_viewer_listed_only(db_session: AsyncSession):
    """A None viewer (system context) collapses to publicly_listed_sql only."""
    from app.models.course import Course

    owner, subject = await _seed_owner_subject(db_session)
    private = await _mk_course(
        db_session,
        owner,
        subject,
        visibility=Visibility.private,
        status=CourseStatus.draft,
        moderation_state=ModerationState.none,
    )
    ids = {
        row[0]
        for row in (
            await db_session.execute(select(Course.id).where(vis.retrieval_acl_clause(None)))
        ).all()
    }
    assert private.id not in ids


async def _mk_learner(db: AsyncSession):
    from app.core.ids import new_id
    from app.core.security import hash_password
    from app.models.user import Role, User

    learner = User(
        email=f"l-{new_id()[:8]}@lumen.test",
        password_hash=hash_password("Password!1234"),
        full_name="Learner",
        role=Role.student,
    )
    db.add(learner)
    await db.commit()
    await db.refresh(learner)
    return learner


@pytest.mark.asyncio
async def test_retrieval_acl_clause_enrolled_grandfather(db_session: AsyncSession):
    """R-VIS-13: a grandfathered learner keeps retrieval on a now-private course.

    Mirrors ``can_view_course``'s enrollment branch in SQL — the learner
    enrolled while the course was visible and keeps chunk-level access even
    after the owner unpublishes/unshares it. The non-enrolled stranger never
    sees it.
    """
    from app.models.course import Course, Enrollment

    owner, subject = await _seed_owner_subject(db_session)
    learner = await _mk_learner(db_session)
    stranger = await _mk_learner(db_session)

    # A course the learner enrolled in, then it went private + unpublished.
    private = await _mk_course(
        db_session,
        owner,
        subject,
        visibility=Visibility.private,
        status=CourseStatus.draft,
        moderation_state=ModerationState.none,
    )
    db_session.add(Enrollment(user_id=learner.id, course_id=private.id))
    await db_session.commit()

    learner_ids = {
        row[0]
        for row in (
            await db_session.execute(select(Course.id).where(vis.retrieval_acl_clause(learner.id)))
        ).all()
    }
    assert private.id in learner_ids  # enrolled grandfather -> eligible

    stranger_ids = {
        row[0]
        for row in (
            await db_session.execute(select(Course.id).where(vis.retrieval_acl_clause(stranger.id)))
        ).all()
    }
    assert private.id not in stranger_ids  # non-enrolled non-owner -> blocked


@pytest.mark.asyncio
async def test_retrieval_acl_clause_enrolled_quarantined_blocked(db_session: AsyncSession):
    """R-C6′ full lockout: even an enrolled learner gets nothing on a quarantined
    course — mirrors ``can_view_course`` returning False for the enrolled."""
    from app.models.course import Course, Enrollment

    owner, subject = await _seed_owner_subject(db_session)
    learner = await _mk_learner(db_session)

    quarantined = await _mk_course(
        db_session,
        owner,
        subject,
        visibility=Visibility.public,
        status=CourseStatus.published,
        moderation_state=ModerationState.approved,
    )
    quarantined.quarantined = True
    db_session.add(Enrollment(user_id=learner.id, course_id=quarantined.id))
    await db_session.commit()

    ids = {
        row[0]
        for row in (
            await db_session.execute(select(Course.id).where(vis.retrieval_acl_clause(learner.id)))
        ).all()
    }
    assert quarantined.id not in ids  # quarantine beats enrollment (full lockout)


async def test_retrieval_acl_clause_enrolled_deleted_course_blocked(db_session: AsyncSession):
    """Head fix on the enrollment arm: soft-delete does NOT remove enrollment
    rows, and the SQL path has no repo-load 404 precondition — without an
    explicit ``deleted_at IS NULL`` guard an ex-enrollee could retrieve chunks
    of a deleted course. Every SQL branch carries the guard itself."""
    from datetime import UTC, datetime

    from app.models.course import Course, Enrollment

    owner, subject = await _seed_owner_subject(db_session)
    learner = await _mk_learner(db_session)

    deleted = await _mk_course(
        db_session,
        owner,
        subject,
        visibility=Visibility.public,
        status=CourseStatus.published,
        moderation_state=ModerationState.approved,
    )
    db_session.add(Enrollment(user_id=learner.id, course_id=deleted.id))
    await db_session.flush()
    deleted.deleted_at = datetime.now(UTC)
    await db_session.commit()

    ids = {
        row[0]
        for row in (
            await db_session.execute(select(Course.id).where(vis.retrieval_acl_clause(learner.id)))
        ).all()
    }
    assert deleted.id not in ids  # deletion beats enrollment grandfathering
