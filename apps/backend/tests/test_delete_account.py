"""S6.8 — delete_account choreography (ADR-0030 §D2 / R-M3').

Self-serve deletion is anonymize-in-place: we never ``session.delete(user)``.
The ``users`` row persists forever as an anonymized tombstone; all FK graphs
stay intact; PII is irreversibly scrubbed. The core PII scrub + deactivate is
un-guarded (must succeed or the whole transaction rolls back); only the
sibling-table steps are narrowly try-guarded.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password
from app.models.audit import AuditEvent
from app.models.course import Course
from app.models.user import RefreshToken, Role, User


async def _register_and_login(client: AsyncClient, email: str, password: str) -> str:
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Doomed User"},
    )
    assert r.status_code == 201, r.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


async def test_delete_account_scrubs_core_pii(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = f"doom-{uuid.uuid4().hex[:6]}@lumen.test"
    password = "Password!1234"
    token = await _register_and_login(client, email, password)
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    uid = me.json()["id"]

    r = await client.request(
        "DELETE",
        "/api/v1/users/me",
        json={"password": password},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text

    user = await db_session.get(User, uid)
    await db_session.refresh(user)
    assert user.email == f"deleted-{uid}@lumen.invalid"
    assert user.full_name == ""
    assert user.avatar_url is None
    assert user.bio is None
    assert user.email_verified_at is None
    assert user.is_active is False
    assert user.deleted_at is not None
    # password no longer usable
    assert not verify_password(password, user.password_hash)

    # the user.deleted audit row was written (actor=self) before the scrub
    ev = (
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "user.deleted", AuditEvent.target_id == uid
                )
            )
        )
        .scalars()
        .all()
    )
    assert ev, "user.deleted audit must be written"


async def test_delete_account_wrong_password_401(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = f"wrong-{uuid.uuid4().hex[:6]}@lumen.test"
    password = "Password!1234"
    token = await _register_and_login(client, email, password)
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    uid = me.json()["id"]

    r = await client.request(
        "DELETE",
        "/api/v1/users/me",
        json={"password": "WrongPass!9999"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "auth.invalid_credentials"

    user = await db_session.get(User, uid)
    await db_session.refresh(user)
    assert user.is_active is True  # nothing scrubbed
    assert user.deleted_at is None
    assert user.email == email


async def test_delete_account_purges_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = f"sess-{uuid.uuid4().hex[:6]}@lumen.test"
    password = "Password!1234"
    token = await _register_and_login(client, email, password)
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    uid = me.json()["id"]

    r = await client.request(
        "DELETE",
        "/api/v1/users/me",
        json={"password": password},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text

    # refresh tokens hard-deleted (not just revoked) — zero rows remain
    rows = (
        (await db_session.execute(select(RefreshToken).where(RefreshToken.user_id == uid)))
        .scalars()
        .all()
    )
    assert rows == []


async def test_delete_account_delists_owned_courses(
    client: AsyncClient, db_session: AsyncSession, make_user, seed_lesson
) -> None:
    from sqlalchemy import update

    from app.models.course import CourseStatus, ModerationState, Subject, Visibility

    email = f"owner-{uuid.uuid4().hex[:6]}@lumen.test"
    password = "Password!1234"
    token = await _register_and_login(client, email, password)
    h = {"Authorization": f"Bearer {token}"}

    subject = Subject(title="Prog", slug=f"prog-{uuid.uuid4().hex[:6]}")
    db_session.add(subject)
    await db_session.commit()

    create = await client.post(
        "/api/v1/courses",
        json={"title": "Owned", "subject_id": subject.id, "overview": "x"},
        headers=h,
    )
    course_id = create.json()["id"]
    await seed_lesson(course_id, h)
    await db_session.execute(
        update(Course)
        .where(Course.id == course_id)
        .values(
            status=CourseStatus.published,
            visibility=Visibility.public,
            moderation_state=ModerationState.approved,
        )
    )
    await db_session.commit()

    # another learner enrolls — their enrollment must survive deletion
    learner = await make_user(email=f"learner-{uuid.uuid4().hex[:6]}@lumen.test", role=Role.user)
    from app.models.course import Enrollment

    db_session.add(Enrollment(user_id=learner.id, course_id=course_id))
    await db_session.commit()

    r = await client.request("DELETE", "/api/v1/users/me", json={"password": password}, headers=h)
    assert r.status_code == 200, r.text

    course = await db_session.get(Course, course_id)
    await db_session.refresh(course)
    assert course.visibility == Visibility.private
    assert course.deleted_at is not None  # soft-deleted
    # moderation_state stays sticky (R-C2) — NOT reset to none
    assert course.moderation_state == ModerationState.approved

    # the learner's enrollment is preserved (FR-DEL-02)
    enr = (
        (
            await db_session.execute(
                select(Enrollment).where(
                    Enrollment.course_id == course_id, Enrollment.user_id == learner.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(enr) == 1


async def test_delete_account_soft_deletes_authored_reviews(
    client: AsyncClient, db_session: AsyncSession, make_user, seed_lesson
) -> None:
    import uuid as _uuid

    from app.models.course import Course, Review, Subject

    email = f"rev-{_uuid.uuid4().hex[:6]}@lumen.test"
    password = "Password!1234"
    token = await _register_and_login(client, email, password)
    h = {"Authorization": f"Bearer {token}"}
    me = await client.get("/api/v1/auth/me", headers=h)
    uid = me.json()["id"]

    # an unrelated owner's course the deleting user reviewed
    owner = await make_user(email=f"co-{_uuid.uuid4().hex[:6]}@lumen.test", role=Role.user)
    subject = Subject(title="S", slug=f"s-{_uuid.uuid4().hex[:6]}")
    db_session.add(subject)
    await db_session.commit()
    course = Course(
        title="C",
        slug=f"c-{_uuid.uuid4().hex[:6]}",
        subject_id=subject.id,
        owner_id=owner.id,
        overview="x",
    )
    db_session.add(course)
    await db_session.commit()
    review = Review(author_id=uid, course_id=course.id, rating=5, body="great")
    db_session.add(review)
    await db_session.commit()
    review_id = review.id

    r = await client.request("DELETE", "/api/v1/users/me", json={"password": password}, headers=h)
    assert r.status_code == 200, r.text

    got = await db_session.get(Review, review_id)
    await db_session.refresh(got)
    assert got.deleted_at is not None  # authored review hidden
    assert got.author_id == uid  # author pointer kept at the tombstone
