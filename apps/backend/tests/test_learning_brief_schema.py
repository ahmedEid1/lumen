"""S3.2 — brief Pydantic schemas + ``BriefLevel`` → ``Difficulty`` mapping.

The elicitation DTOs (start / turn / finalize) and the finalized ``BriefOut``.
The privacy contract (FR-PRIV-01) reaches the schema layer too: ``BriefOut``
carries only the structured (non-sensitive) fields — never the raw goal text
or the ``source_goal_enc`` ciphertext.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.course import Difficulty
from app.schemas.learning_brief import (
    BriefDraft,
    BriefEdits,
    BriefFinalizeRequest,
    BriefLevel,
    BriefOut,
    GoalStartRequest,
    GoalTurnRequest,
    GoalTurnResponse,
    difficulty_from_level,
)

# ---------------- BriefLevel <-> Difficulty (DR-4 seam) ----------------


def test_brief_level_values():
    assert {level.value for level in BriefLevel} == {"beginner", "intermediate", "advanced"}


def test_brief_level_maps_one_to_one_to_difficulty():
    assert difficulty_from_level(BriefLevel.beginner) == Difficulty.beginner
    assert difficulty_from_level(BriefLevel.intermediate) == Difficulty.intermediate
    assert difficulty_from_level(BriefLevel.advanced) == Difficulty.advanced


def test_difficulty_from_level_accepts_string():
    """The orchestrator (S3.6) holds ``brief.level`` as a String(20) column —
    the mapper accepts the raw string too, not just the enum."""
    assert difficulty_from_level("advanced") == Difficulty.advanced


def test_difficulty_from_level_unknown_falls_back_to_beginner():
    """A drifted / missing level never crashes the build — defaults to beginner."""
    assert difficulty_from_level(None) == Difficulty.beginner
    assert difficulty_from_level("nonsense") == Difficulty.beginner


# ---------------- GoalStartRequest ----------------


def test_goal_start_request_valid():
    req = GoalStartRequest(goal="I want to get good at React")
    assert req.goal == "I want to get good at React"


def test_goal_start_request_rejects_empty_goal():
    with pytest.raises(ValidationError):
        GoalStartRequest(goal="")


def test_goal_start_request_rejects_overlong_goal():
    with pytest.raises(ValidationError):
        GoalStartRequest(goal="x" * 4_001)


def test_goal_start_request_forbids_extra_fields():
    with pytest.raises(ValidationError):
        GoalStartRequest(goal="ok", sneaky="value")


# ---------------- GoalTurnRequest ----------------


def test_goal_turn_request_valid():
    req = GoalTurnRequest(message="I already know JS")
    assert req.message == "I already know JS"


def test_goal_turn_request_rejects_empty():
    with pytest.raises(ValidationError):
        GoalTurnRequest(message="")


def test_goal_turn_request_forbids_extra():
    with pytest.raises(ValidationError):
        GoalTurnRequest(message="ok", extra=1)


# ---------------- BriefDraft (accumulated state) ----------------


def test_brief_draft_all_optional():
    draft = BriefDraft()
    assert draft.level is None
    assert draft.desired_outcomes == []
    assert draft.format_prefs == {}


def test_brief_draft_carries_structured_fields():
    draft = BriefDraft(
        goal_summary="Master React",
        level=BriefLevel.advanced,
        prior_knowledge="Solid JS",
        time_budget_hours=30,
        sessions_per_week=3,
        desired_outcomes=["Build concurrent UI"],
        format_prefs={"hands_on": True},
        language="en",
        suggested_subject="Frontend",
    )
    assert draft.level == BriefLevel.advanced
    assert draft.time_budget_hours == 30
    assert draft.desired_outcomes == ["Build concurrent UI"]


# ---------------- GoalTurnResponse ----------------


def test_goal_turn_response_shape():
    resp = GoalTurnResponse(
        session_id="brief123",
        assistant_message="What's your time budget?",
        accumulated_brief=BriefDraft(level=BriefLevel.beginner),
        turns_used=1,
        turns_remaining=5,
        converged=False,
    )
    assert resp.session_id == "brief123"
    assert resp.turns_remaining == 5
    assert resp.converged is False
    assert resp.accumulated_brief.level == BriefLevel.beginner


# ---------------- BriefFinalizeRequest ----------------


def test_finalize_request_edits_optional():
    assert BriefFinalizeRequest().edits is None
    req = BriefFinalizeRequest(edits=BriefEdits(time_budget_hours=10))
    assert req.edits.time_budget_hours == 10


def test_finalize_request_forbids_extra():
    with pytest.raises(ValidationError):
        BriefFinalizeRequest(edits=None, bogus=True)


def test_brief_edits_collections_default_none_not_empty():
    """Codex P2: BriefEdits collection fields default to None (a no-op on merge),
    NOT to empty [] / {} like BriefDraft — so a scalar-only edit never clobbers
    accumulated outcomes/format_prefs. An explicit empty IS still honoured."""
    # Omitted collections → None (the merge skips them).
    edits = BriefEdits(time_budget_hours=10)
    assert edits.desired_outcomes is None
    assert edits.format_prefs is None
    # BriefDraft (the accumulated-state transport) keeps its empty-collection
    # defaults — the divergence that makes BriefEdits necessary.
    draft = BriefDraft(time_budget_hours=10)
    assert draft.desired_outcomes == []
    assert draft.format_prefs == {}
    # An EXPLICIT empty on edits is preserved (a deliberate clear).
    explicit = BriefEdits(desired_outcomes=[], format_prefs={})
    assert explicit.desired_outcomes == []
    assert explicit.format_prefs == {}


def test_finalize_request_parses_scalar_only_json():
    """A scalar-only edits JSON (what the review UI sends) leaves collections None
    so the finalize merge preserves accumulated outcomes (Codex P2)."""
    req = BriefFinalizeRequest.model_validate(
        {"edits": {"goal_summary": "x", "level": "beginner", "time_budget_hours": 8}}
    )
    assert req.edits is not None
    assert req.edits.desired_outcomes is None  # omitted → no-op on merge
    assert req.edits.format_prefs is None


# ---------------- BriefOut (FR-PRIV-01) ----------------


class _BriefRow:
    """Stand-in ORM row to exercise ``model_validate(from_attributes=True)``."""

    def __init__(self):
        from datetime import UTC, datetime

        self.id = "briefABC"
        self.level = "advanced"
        self.time_budget_hours = 30
        self.sessions_per_week = 3
        self.prior_knowledge = "Solid JS"
        self.desired_outcomes = ["Build a concurrent UI"]
        self.goal_summary = "Master React"
        self.suggested_subject = "Frontend"
        self.language = "en"
        self.finalized_at = datetime(2026, 6, 5, tzinfo=UTC)
        # Sensitive fields that MUST NOT make it into BriefOut.
        self.source_goal_enc = b"\x00\x01ciphertext-bytes"
        self.owner_id = "ownerXYZ"


def test_brief_out_from_attributes():
    out = BriefOut.model_validate(_BriefRow())
    assert out.id == "briefABC"
    assert out.level == "advanced"
    assert out.time_budget_hours == 30
    assert out.desired_outcomes == ["Build a concurrent UI"]
    assert out.finalized_at is not None


def test_brief_out_never_exposes_raw_goal_or_ciphertext():
    """FR-PRIV-01: no ``source_goal_enc`` / raw goal field in the serialization."""
    out = BriefOut.model_validate(_BriefRow())
    dumped = out.model_dump(mode="json")
    assert "source_goal_enc" not in dumped
    assert "source_goal" not in dumped
    assert "goal" not in dumped  # no raw goal text field at all
    # And the ciphertext bytes never appear anywhere in the JSON.
    assert "ciphertext-bytes" not in str(dumped)
