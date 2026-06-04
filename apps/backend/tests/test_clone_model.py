"""S4.1 — Clone provenance + ``is_self`` model columns + ``IdempotencyKey``.

Pure model/ORM assertions (no DB schema hit) — proves the columns are declared,
default ``None``/``False`` on a freshly-constructed instance, and the new
``IdempotencyKey`` model is registered in ``app.models.__init__`` with the right
tablename + unique constraint. The migration-side schema check lives in
``test_migration_clone_provenance.py`` (S4.2).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course, Enrollment


def test_course_has_provenance_columns() -> None:
    # All six provenance attributes exist on the ORM class …
    for attr in (
        "origin_course_id",
        "origin_owner_id",
        "root_origin_course_id",
        "origin_title_snapshot",
        "origin_owner_name_snapshot",
        "cloned_at",
    ):
        assert hasattr(Course, attr), f"Course missing provenance column {attr!r}"

    # … and default to None on a freshly-constructed, never-flushed Course.
    c = Course()
    assert c.origin_course_id is None
    assert c.origin_owner_id is None
    assert c.root_origin_course_id is None
    assert c.origin_title_snapshot is None
    assert c.origin_owner_name_snapshot is None
    assert c.cloned_at is None


def test_enrollment_is_self_defaults_false() -> None:
    assert hasattr(Enrollment, "is_self")
    # The column carries a Python-side default of ``False`` (applied on flush)
    # and a ``server_default`` of ``false`` (existing rows on the additive
    # migration) — never NULL, never True. Pre-flush the ORM attribute is
    # unset (None); the declared default + server_default are the contract.
    col = Enrollment.__table__.columns["is_self"]
    assert col.nullable is False
    assert col.default is not None and col.default.arg is False
    assert col.server_default is not None


def test_idempotency_key_model_registered() -> None:
    from app.models import IdempotencyKey

    assert IdempotencyKey.__tablename__ == "idempotency_keys"
    # The unique constraint that backs the (user, key) idempotency lookup.
    constraint_names = {c.name for c in IdempotencyKey.__table__.constraints}
    assert "uq_idem_user_key" in constraint_names
    for col in ("user_id", "idempotency_key", "endpoint", "response_target_id", "expires_at"):
        assert col in IdempotencyKey.__table__.columns


def test_course_clone_indexes_declared() -> None:
    index_names = {ix.name for ix in Course.__table__.indexes}
    assert "ix_courses_origin_course_id" in index_names
    assert "ix_courses_root_origin" in index_names


@pytest.mark.asyncio
async def test_provenance_sentinel_is_postgres_storable(db_session: AsyncSession) -> None:
    """S4 integration regression: the deleted-owner sentinel MUST persist.

    The S6 sentinel was ``\\x00deleted_user`` — but Postgres ``varchar`` cannot
    store a NUL byte, and asyncpg rejects it at bind time even on a zero-row
    UPDATE. Once S4.1's ``origin_owner_name_snapshot`` column landed,
    ``account.delete_account``'s provenance scrub ran the UPDATE and crashed
    EVERY account deletion. The sentinel is now ``\\x01``-prefixed; this test
    writes it into the real column so a revert to ``\\x00`` fails loudly here.
    """
    from app.core.security import hash_password
    from app.models.course import Subject
    from app.models.user import Role, User
    from app.services.account import DELETED_OWNER_SNAPSHOT

    owner = User(
        email=f"o-{uuid.uuid4().hex[:8]}@lumen.test",
        password_hash=hash_password("Password!1234"),
        full_name="O",
        role=Role.user,
    )
    subject = Subject(title="S", slug=f"s-{uuid.uuid4().hex[:8]}")
    db_session.add_all([owner, subject])
    await db_session.flush()
    clone = Course(
        owner_id=owner.id,
        subject_id=subject.id,
        title="Clone",
        slug=f"c-{uuid.uuid4().hex[:8]}",
        overview="",
        origin_owner_name_snapshot=DELETED_OWNER_SNAPSHOT,
    )
    db_session.add(clone)
    await db_session.flush()
    await db_session.refresh(clone)
    assert clone.origin_owner_name_snapshot == DELETED_OWNER_SNAPSHOT
    assert "\x00" not in DELETED_OWNER_SNAPSHOT
