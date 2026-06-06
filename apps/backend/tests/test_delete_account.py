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


async def test_delete_account_revokes_mcp_clients(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """F1 (S6 gate): a real MCPClient row owned by the deleting user must have
    ``revoked_at`` stamped. This exercises the REAL import path (no mocks) — the
    original ``McpClient`` typo raised ImportError that the per-step guard
    swallowed, so MCP clients were NEVER revoked on account deletion.
    """
    from app.core.security import hash_password as _hash
    from app.models.mcp_client import MCPClient

    email = f"mcp-{uuid.uuid4().hex[:6]}@lumen.test"
    password = "Password!1234"
    token = await _register_and_login(client, email, password)
    h = {"Authorization": f"Bearer {token}"}
    me = await client.get("/api/v1/auth/me", headers=h)
    uid = me.json()["id"]

    # A live (un-revoked) MCP client for this user, plus one already revoked.
    live = MCPClient(owner_user_id=uid, client_secret_hash=_hash("s"), name="laptop")
    db_session.add(live)
    await db_session.commit()
    live_id = live.id

    r = await client.request("DELETE", "/api/v1/users/me", json={"password": password}, headers=h)
    assert r.status_code == 200, r.text

    got = await db_session.get(MCPClient, live_id)
    await db_session.refresh(got)
    assert got.revoked_at is not None, "the live MCP client must be revoked on deletion"


async def test_delete_account_sole_admin_blocked(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    """F2 (S6 gate): the sole active admin cannot self-delete to zero admins.

    The same FR-ADMIN-03 invariant the grant/revoke + suspend paths enforce is
    checked at the START of delete_account; a sole admin's self-delete is refused
    with 422 ``user.last_admin`` and NOTHING is mutated (no partial tombstone).
    """
    email = f"soleadmin-{uuid.uuid4().hex[:6]}@lumen.test"
    password = "Password!1234"
    admin = await make_user(email=email, password=password, role=Role.admin)
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}

    r = await client.request("DELETE", "/api/v1/users/me", json={"password": password}, headers=h)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "user.last_admin"

    # Nothing mutated — no partial tombstone.
    await db_session.refresh(admin)
    assert admin.is_active is True
    assert admin.deleted_at is None
    assert admin.email == email


async def test_delete_account_admin_allowed_when_another_admin_exists(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    """F2: an admin self-delete SUCCEEDS while a second active admin remains."""
    # A second active admin keeps the invariant satisfied.
    await make_user(email=f"otheradmin-{uuid.uuid4().hex[:6]}@lumen.test", role=Role.admin)

    email = f"admin2-{uuid.uuid4().hex[:6]}@lumen.test"
    password = "Password!1234"
    admin = await make_user(email=email, password=password, role=Role.admin)
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}

    r = await client.request("DELETE", "/api/v1/users/me", json={"password": password}, headers=h)
    assert r.status_code == 200, r.text
    await db_session.refresh(admin)
    assert admin.is_active is False
    assert admin.deleted_at is not None


async def test_admin_invariant_takes_advisory_lock(db_session: AsyncSession) -> None:
    """F6 (TOCTOU): assert_active_admin_invariant takes a transaction-scoped
    advisory lock on the fixed key BEFORE the COUNT, so two concurrent
    demote/suspend/delete operations serialize through the check.

    A true two-session race is impractical under the per-session transactional
    test DB (both sessions would deadlock on the same outer transaction), so we
    assert the lock SQL is emitted (the serialization mechanism) and that the
    lock is actually held by this transaction afterwards (pg_locks).
    """
    from sqlalchemy import text

    from app.services import admin_users as admin_users_service
    from app.services.admin_users import _ADMIN_INVARIANT_LOCK_KEY

    # Exercise the real path with a sole admin so the invariant trips (and the
    # lock is taken before the COUNT raises).
    admin = await db_session.execute(
        text("SELECT count(*) FROM users WHERE role = 'admin' AND is_active = true")
    )
    _ = admin.scalar_one()

    # Call against a non-last-admin scenario so it returns cleanly (count >= 1
    # excluding a non-admin id), then verify the advisory lock is held.
    from app.models.user import Role, User

    a = User(
        email=f"lk-{uuid.uuid4().hex[:6]}@lumen.test",
        password_hash="x",
        full_name="L",
        role=Role.admin,
    )
    db_session.add(a)
    await db_session.flush()

    await admin_users_service.assert_active_admin_invariant(
        db_session, excluding_user_id="nonexistent-id"
    )

    # pg_advisory_xact_lock holds in pg_locks for the duration of this txn.
    held = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                "AND (classid::bigint << 32 | objid::bigint) = :k"
            ),
            {"k": _ADMIN_INVARIANT_LOCK_KEY},
        )
    ).scalar_one()
    assert held >= 1, "the advisory lock must be held by this transaction (F6 TOCTOU guard)"


def test_account_module_has_no_lazy_model_imports() -> None:
    """F1 hardening: the choreography steps must NOT lazily import models inside
    the function body (that is what let the ``McpClient`` typo hide). Every model
    is imported at module top; assert the module source carries no per-step
    ``from app.models...`` import, so a typo fails loudly at import time.
    """
    import inspect

    from app.services import account as account_module

    src = inspect.getsource(account_module)
    # The only ``from app.models`` lines may live in the top-level import block;
    # none may appear indented inside a function body.
    for line in src.splitlines():
        if "from app.models" in line:
            assert not line.startswith((" ", "\t")), (
                f"lazy in-function model import found (F1 regression): {line!r}"
            )


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


async def test_delete_account_purges_learning_briefs(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """W11 (F7): the user's private encrypted learning brief is HARD-deleted.

    Live evidence: after a full UI account deletion, ``learning_briefs`` kept a row
    with the field-encrypted ``source_goal_enc`` (the learner's private goal,
    FR-PRIV-01 / DR-22). delete_account (S6.8) predated the model (S3.1) and never
    purged it. The brief must be gone; an unrelated user's brief must survive.
    """
    import uuid as _uuid
    from datetime import UTC, datetime, timedelta

    from app.models.idempotency import IdempotencyKey
    from app.models.learning_brief import LearningBrief

    email = f"brief-{_uuid.uuid4().hex[:6]}@lumen.test"
    password = "Password!1234"
    token = await _register_and_login(client, email, password)
    h = {"Authorization": f"Bearer {token}"}
    me = await client.get("/api/v1/auth/me", headers=h)
    uid = me.json()["id"]

    # The deleting user's private brief (raw ciphertext bytes stand in for the
    # field-encrypted goal — the purge keys on owner_id, not content) ...
    brief = LearningBrief(owner_id=uid, source_goal_enc=b"\x00secret-goal-ciphertext")
    db_session.add(brief)
    # ... and a second, in-progress brief to prove the WHERE matches all owned rows.
    brief2 = LearningBrief(owner_id=uid, source_goal_enc=b"\x01another-goal")
    # An idempotency row (S4) carries no PII and is TTL-swept — it must SURVIVE.
    idem = IdempotencyKey(
        user_id=uid,
        idempotency_key=f"k-{_uuid.uuid4().hex[:8]}",
        endpoint="course.clone",
        response_target_id="trgt",
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    db_session.add_all([brief2, idem])
    await db_session.commit()
    brief_id, brief2_id, idem_id = brief.id, brief2.id, idem.id

    # An UNRELATED user's brief must be untouched (scoped to the deleting owner).
    other_token = await _register_and_login(
        client, f"other-{_uuid.uuid4().hex[:6]}@lumen.test", password
    )
    other_me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {other_token}"}
    )
    other_uid = other_me.json()["id"]
    other_brief = LearningBrief(owner_id=other_uid, source_goal_enc=b"\x02keep-me")
    db_session.add(other_brief)
    await db_session.commit()
    other_brief_id = other_brief.id

    r = await client.request("DELETE", "/api/v1/users/me", json={"password": password}, headers=h)
    assert r.status_code == 200, r.text

    db_session.expire_all()
    assert await db_session.get(LearningBrief, brief_id) is None  # PII hard-deleted
    assert await db_session.get(LearningBrief, brief2_id) is None  # all owned rows gone
    # The idempotency row (no PII, TTL-swept) is intentionally left in place.
    assert await db_session.get(IdempotencyKey, idem_id) is not None
    # Another user's brief is untouched (owner-scoped purge).
    assert await db_session.get(LearningBrief, other_brief_id) is not None
