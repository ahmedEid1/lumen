"""S3.1 — ``LearningBrief`` model: persistence + the FR-PRIV-01 privacy contract.

The brief is server-owned, immutable-once-finalized, and the *raw goal text*
is field-encrypted at rest (``source_goal_enc``) via ``secrets_crypto`` (DR-22,
a key independent of the BYOK KEK). The plaintext goal must NEVER appear in
``repr``/``str``/serialization/logs (FR-PRIV-01) — these tests mirror the
BYOK sink-redaction idioms: drive a sentinel goal through every visible
surface of the ORM object and assert it is absent.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select

from app.core import secrets_crypto
from app.models.learning_brief import LearningBrief

pytestmark = pytest.mark.asyncio

# A deliberately distinctive goal so an accidental leak in repr/str/columns is
# unmistakable (mirrors the BYOK SENTINEL idiom).
SENTINEL_GOAL = "I want to MASTER-REACT-SENTINEL-do-not-leak hooks and concurrency"


async def _persist_brief(db, owner_id: str, **overrides) -> LearningBrief:
    brief = LearningBrief(
        owner_id=owner_id,
        source_goal_enc=secrets_crypto.encrypt(SENTINEL_GOAL.encode("utf-8")),
        **overrides,
    )
    db.add(brief)
    await db.commit()
    await db.refresh(brief)
    return brief


async def test_brief_persists_in_progress_on_create(make_user, db_session):
    user = await make_user()
    brief = await _persist_brief(db_session, user.id)

    assert brief.id is not None
    assert brief.owner_id == user.id
    # In-progress: not finalized yet (FR-DEFINE-08 mutability precondition).
    assert brief.finalized_at is None
    assert brief.created_at is not None


async def test_source_goal_roundtrips_through_secrets_crypto(make_user, db_session):
    """(b) the encrypted goal decrypts back to the original plaintext, and the
    stored column is opaque ciphertext bytes — not the plaintext."""
    user = await make_user()
    brief = await _persist_brief(db_session, user.id)

    # Round-trip: ciphertext decrypts to the original goal.
    assert secrets_crypto.decrypt(brief.source_goal_enc).decode("utf-8") == SENTINEL_GOAL
    # The stored bytes are opaque — the plaintext is not findable in them.
    assert isinstance(brief.source_goal_enc, (bytes, bytearray))
    assert SENTINEL_GOAL.encode("utf-8") not in bytes(brief.source_goal_enc)


async def test_goal_never_in_repr_or_str(make_user, db_session):
    """FR-PRIV-01: the plaintext goal must not surface in repr()/str()."""
    user = await make_user()
    brief = await _persist_brief(db_session, user.id)

    assert SENTINEL_GOAL not in repr(brief)
    assert SENTINEL_GOAL not in str(brief)
    # The encrypted blob bytes must not be dumped into repr either (no key
    # material / ciphertext spelunking surface).
    assert "source_goal_enc" not in repr(brief) or "b'" not in repr(brief)
    # repr still identifies the row for debugging.
    assert brief.id in repr(brief)


async def test_goal_never_in_dict_dump(make_user, db_session):
    """A naive ``__dict__`` walk (the shape a logger / serializer would grab)
    must not contain the plaintext goal."""
    user = await make_user()
    brief = await _persist_brief(db_session, user.id)

    flat = repr({k: v for k, v in brief.__dict__.items() if not k.startswith("_sa_")})
    assert SENTINEL_GOAL not in flat


async def test_structured_fields_load_and_store(make_user, db_session):
    """(c) every structured field round-trips through Postgres."""
    user = await make_user()
    brief = await _persist_brief(
        db_session,
        user.id,
        goal_summary="Master React hooks and concurrency",
        level="advanced",
        prior_knowledge="Comfortable with JS, some component basics",
        time_budget_hours=30,
        sessions_per_week=3,
        desired_outcomes=["Build a concurrent UI", "Reason about Suspense"],
        format_prefs={"hands_on": True, "video": False},
        language="en",
        suggested_subject="Frontend Engineering",
    )

    # Re-read from a fresh identity-map miss to prove it persisted.
    db_session.expunge(brief)
    reloaded = (
        await db_session.execute(select(LearningBrief).where(LearningBrief.id == brief.id))
    ).scalar_one()

    assert reloaded.goal_summary == "Master React hooks and concurrency"
    assert reloaded.level == "advanced"
    assert reloaded.prior_knowledge.startswith("Comfortable with JS")
    assert reloaded.time_budget_hours == 30
    assert reloaded.sessions_per_week == 3
    assert reloaded.desired_outcomes == ["Build a concurrent UI", "Reason about Suspense"]
    assert reloaded.format_prefs == {"hands_on": True, "video": False}
    assert reloaded.language == "en"
    assert reloaded.suggested_subject == "Frontend Engineering"


async def test_nullable_structured_fields_default_none(make_user, db_session):
    """Optional structured fields are nullable (filled across elicitation turns)."""
    user = await make_user()
    brief = await _persist_brief(db_session, user.id)

    assert brief.goal_summary is None
    assert brief.level is None
    assert brief.time_budget_hours is None
    assert brief.sessions_per_week is None
    assert brief.suggested_subject is None
    # JSONB list/dict default to empty containers (server_default), not NULL.
    assert brief.desired_outcomes == []
    assert brief.format_prefs == {}


async def test_owner_created_index_present(db_session):
    """(d) the ``(owner_id, created_at)`` index exists for owner-scoped lists.

    Inspected via ``run_sync`` against a real connection — ``inspect`` needs a
    sync Connection (AsyncEngine/AsyncSession aren't inspectable directly).
    """

    def _indexes(sync_conn) -> set[tuple[str, ...]]:
        insp = sa_inspect(sync_conn)
        return {tuple(ix["column_names"]) for ix in insp.get_indexes("learning_briefs")}

    conn = await db_session.connection()
    by_cols = await conn.run_sync(_indexes)
    assert ("owner_id", "created_at") in by_cols, f"missing composite index; have {by_cols}"
