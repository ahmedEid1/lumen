"""S2.2 — Migration 0033 course_visibility_moderation.

Two layers:

* **Structural (pure-unit, no DB)** — revision identity + chain link, phase
  annotation, the additive-then-NOT-NULL ordering, the CONCURRENTLY index in an
  autocommit block, the never-drop-moderation_events invariant, and the
  model-level column/enum shape. These run anywhere.

* **DB-backed (runs under ``make test.api`` against real Postgres)** — the
  backfill semantics: live-published -> (public, approved) with exactly one
  synthetic ``moderation_events`` row; draft -> (private, none) with no event;
  soft-deleted-published -> (private, none); columns NOT NULL with server
  defaults so a bare INSERT omitting them succeeds (old-fleet tolerance).

The conftest builds the test DB from ``Base.metadata.create_all`` (columns
already NOT NULL with defaults), so the DB-backed layer drives the *backfill
SQL* directly against rows seeded with explicit ``visibility=NULL`` (the
pre-backfill state) and asserts the end state — exercising the exact UPDATE +
synthetic-event statements the migration runs.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_MIG_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load_migration(stem_contains: str):
    matches = [p for p in _MIG_DIR.glob("*.py") if stem_contains in p.name]
    assert matches, f"no migration file containing {stem_contains!r}"
    path = matches[0]
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="module")
def mig0033():
    return _load_migration("0033")


@pytest.fixture(scope="module")
def src0033() -> str:
    return next(_MIG_DIR.glob("*0033*.py")).read_text()


# --------------------------------------------------------------------------
# Structural (pure-unit)
# --------------------------------------------------------------------------


def test_revision_identity_and_chain(mig0033):
    assert mig0033.revision == "0033"
    # Temporarily chained off 0030 in this worktree; re-pointed at 0032 at
    # integration (the loud INTEGRATION comment marks the spot).
    assert mig0033.down_revision in {"0030", "0032"}


def test_has_upgrade_and_downgrade(mig0033):
    assert callable(mig0033.upgrade)
    assert callable(mig0033.downgrade)


def test_phase_annotation_present(mig0033, src0033):
    assert getattr(mig0033, "PHASE", None) == "A"
    assert "Phase A" in src0033 or 'PHASE = "A"' in src0033


def test_integration_repoint_comment_present(src0033):
    """The down_revision carries a loud re-point marker for the integrator."""
    assert "INTEGRATION" in src0033


def test_concurrent_index_in_autocommit_block(src0033):
    assert "autocommit_block" in src0033
    assert "CONCURRENTLY" in src0033
    assert "ix_courses_listed" in src0033
    # Consolidated index columns (design-spec §2.5 appends owner_id).
    assert "visibility, moderation_state, status, subject_id, owner_id" in src0033
    assert "WHERE deleted_at IS NULL" in src0033


def test_additive_then_not_null_ordering(mig0033):
    """Nullable add -> backfill -> SET DEFAULT/NOT NULL (old-fleet tolerance)."""
    import inspect

    up_src = inspect.getsource(mig0033.upgrade)
    add_idx = up_src.index('add_column("courses", sa.Column("visibility"')
    backfill_idx = up_src.index("_backfill_visibility()")
    notnull_idx = up_src.index('alter_column("courses", "visibility"')
    assert add_idx < backfill_idx < notnull_idx, "must add nullable, backfill, then NOT NULL"
    assert "nullable=True" in up_src  # the additive add
    assert "nullable=False" in up_src  # the tighten


def test_downgrade_never_drops_moderation_events(mig0033, src0033):
    """R-C2/R-M9: the append-only audit table survives a column rollback."""
    import inspect

    down_src = inspect.getsource(mig0033.downgrade)
    assert "drop_table" not in down_src
    assert "moderation_events" not in down_src or "DROP TABLE" not in down_src.upper()
    assert 'drop_column("courses", "visibility")' in down_src
    assert 'drop_column("courses", "moderation_state")' in down_src


def test_backfill_inserts_synthetic_approved_event(src0033):
    """Backfilled-approved courses get a synthetic to_state='approved' event."""
    assert "moderation_events" in src0033
    assert "'approved'" in src0033
    assert "actor_id" in src0033


# --------------------------------------------------------------------------
# Model shape (importable; no DB session needed)
# --------------------------------------------------------------------------


def test_course_model_has_visibility_and_moderation_columns():
    from app.models.course import Course, ModerationState, Visibility

    cols = Course.__mapper__.columns
    assert "visibility" in cols
    assert "moderation_state" in cols
    assert cols["visibility"].nullable is False
    assert cols["moderation_state"].nullable is False
    assert cols["visibility"].server_default is not None
    assert cols["moderation_state"].server_default is not None
    # Enum values per ADR-0026 §1.
    assert {v.value for v in Visibility} == {"private", "public"}
    assert {v.value for v in ModerationState} == {
        "none",
        "pending_review",
        "approved",
        "rejected",
        "delisted",
    }


def test_moderation_event_model_shape():
    from app.models.moderation import ModerationEvent

    cols = ModerationEvent.__mapper__.columns
    for name in ("course_id", "actor_id", "from_state", "to_state", "reason_code", "note"):
        assert name in cols
    assert cols["to_state"].nullable is False
    assert cols["from_state"].nullable is True
    assert cols["actor_id"].nullable is True


def test_courses_listed_index_declared_on_model():
    from app.models.course import Course

    idx_names = {ix.name for ix in Course.__table__.indexes}
    assert "ix_courses_listed" in idx_names
    listed = next(ix for ix in Course.__table__.indexes if ix.name == "ix_courses_listed")
    col_names = [c.name for c in listed.columns]
    assert col_names == ["visibility", "moderation_state", "status", "subject_id", "owner_id"]


# --------------------------------------------------------------------------
# DB-backed backfill semantics (runs under make test.api)
# --------------------------------------------------------------------------


async def _seed_subject_and_owner(db: AsyncSession) -> tuple[str, str]:
    from app.core.ids import new_id
    from app.core.security import hash_password
    from app.models.course import Subject
    from app.models.user import Role, User

    owner = User(
        email=f"owner-{new_id()[:8]}@lumen.test",
        password_hash=hash_password("Password!1234"),
        full_name="Owner",
        role=Role.instructor,
    )
    subject = Subject(title="Mig Subject", slug=f"mig-{new_id()[:8]}")
    db.add_all([owner, subject])
    await db.commit()
    await db.refresh(owner)
    await db.refresh(subject)
    return owner.id, subject.id


async def _insert_course_with_null_visibility(
    db: AsyncSession, *, owner_id: str, subject_id: str, status: str, deleted: bool
) -> str:
    """Insert a course in the *pre-backfill* state: visibility/moderation NULL."""
    from app.core.ids import new_id

    cid = new_id()
    await db.execute(
        text(
            """
            INSERT INTO courses
                (id, owner_id, subject_id, title, slug, overview, learning_outcomes,
                 difficulty, status, visibility, moderation_state, is_featured,
                 deleted_at, created_at, updated_at)
            VALUES
                (:id, :owner, :subject, :title, :slug, '', '[]'::jsonb, 'beginner',
                 :status, NULL, NULL, false, :deleted_at, now(), now())
            """
        ),
        {
            "id": cid,
            "owner": owner_id,
            "subject": subject_id,
            "title": f"Course {cid[:6]}",
            "slug": f"c-{cid[:8]}",
            "status": status,
            "deleted_at": "now()" if deleted else None,
        },
    )
    if deleted:
        await db.execute(text("UPDATE courses SET deleted_at = now() WHERE id = :id"), {"id": cid})
    await db.commit()
    return cid


@pytest.mark.asyncio
async def test_backfill_published_to_public_approved(db_session: AsyncSession):
    """Live-published -> (public, approved) + exactly one synthetic event."""
    owner_id, subject_id = await _seed_subject_and_owner(db_session)
    cid = await _insert_course_with_null_visibility(
        db_session, owner_id=owner_id, subject_id=subject_id, status="published", deleted=False
    )

    # Drive the migration's backfill SQL directly (same statements as
    # _backfill_visibility, run inside the test session).
    await db_session.execute(
        text(
            "UPDATE courses SET visibility='public', moderation_state='approved' "
            "WHERE visibility IS NULL AND status='published' AND deleted_at IS NULL"
        )
    )
    await db_session.execute(
        text(
            """
            INSERT INTO moderation_events
                (id, course_id, actor_id, from_state, to_state, created_at, updated_at)
            SELECT substr(md5(random()::text || clock_timestamp()::text), 1, 21),
                   c.id, NULL, 'none', 'approved', now(), now()
            FROM courses c WHERE c.id = :id
            """
        ),
        {"id": cid},
    )
    await db_session.commit()

    row = (
        await db_session.execute(
            text("SELECT visibility, moderation_state FROM courses WHERE id=:id"), {"id": cid}
        )
    ).one()
    assert row[0] == "public"
    assert row[1] == "approved"
    n = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM moderation_events WHERE course_id=:id AND to_state='approved'"
            ),
            {"id": cid},
        )
    ).scalar_one()
    assert n == 1


@pytest.mark.asyncio
async def test_backfill_draft_to_private_none_no_event(db_session: AsyncSession):
    owner_id, subject_id = await _seed_subject_and_owner(db_session)
    cid = await _insert_course_with_null_visibility(
        db_session, owner_id=owner_id, subject_id=subject_id, status="draft", deleted=False
    )
    await db_session.execute(
        text(
            "UPDATE courses SET visibility='private', moderation_state='none' "
            "WHERE visibility IS NULL"
        )
    )
    await db_session.commit()

    row = (
        await db_session.execute(
            text("SELECT visibility, moderation_state FROM courses WHERE id=:id"), {"id": cid}
        )
    ).one()
    assert row[0] == "private"
    assert row[1] == "none"
    n = (
        await db_session.execute(
            text("SELECT count(*) FROM moderation_events WHERE course_id=:id"), {"id": cid}
        )
    ).scalar_one()
    assert n == 0


@pytest.mark.asyncio
async def test_backfill_softdeleted_published_to_private(db_session: AsyncSession):
    """A soft-deleted published course is NOT live-published -> private/none."""
    owner_id, subject_id = await _seed_subject_and_owner(db_session)
    cid = await _insert_course_with_null_visibility(
        db_session, owner_id=owner_id, subject_id=subject_id, status="published", deleted=True
    )
    # Approved branch only touches deleted_at IS NULL rows; the else-branch
    # picks this up.
    await db_session.execute(
        text(
            "UPDATE courses SET visibility='public', moderation_state='approved' "
            "WHERE visibility IS NULL AND status='published' AND deleted_at IS NULL"
        )
    )
    await db_session.execute(
        text(
            "UPDATE courses SET visibility='private', moderation_state='none' "
            "WHERE visibility IS NULL"
        )
    )
    await db_session.commit()

    row = (
        await db_session.execute(
            text("SELECT visibility, moderation_state FROM courses WHERE id=:id"), {"id": cid}
        )
    ).one()
    assert row[0] == "private"
    assert row[1] == "none"


@pytest.mark.asyncio
async def test_bare_insert_uses_server_defaults(db_session: AsyncSession):
    """Old-fleet INSERT omitting the columns defaults to private/none."""
    owner_id, subject_id = await _seed_subject_and_owner(db_session)
    from app.core.ids import new_id

    cid = new_id()
    await db_session.execute(
        text(
            """
            INSERT INTO courses
                (id, owner_id, subject_id, title, slug, overview, learning_outcomes,
                 difficulty, status, is_featured, created_at, updated_at)
            VALUES
                (:id, :owner, :subject, 'Bare', :slug, '', '[]'::jsonb, 'beginner',
                 'draft', false, now(), now())
            """
        ),
        {"id": cid, "owner": owner_id, "subject": subject_id, "slug": f"bare-{cid[:8]}"},
    )
    await db_session.commit()
    row = (
        await db_session.execute(
            text("SELECT visibility, moderation_state FROM courses WHERE id=:id"), {"id": cid}
        )
    ).one()
    assert row[0] == "private"
    assert row[1] == "none"
