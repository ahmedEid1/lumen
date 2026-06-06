"""Pydantic DTOs for the goal-intake (define) flow.

S3.2 / FR-DEFINE-02/03/04 / FR-PRIV-01. The elicitation request/response
shapes plus the finalized :class:`BriefOut`, and the :class:`BriefLevel` enum
that maps 1:1 to :class:`~app.models.course.Difficulty` (the DR-4 seam the
authoring orchestrator consumes at build time, S3.6).

**Privacy contract (FR-PRIV-01):** ``BriefOut`` carries only the structured,
non-sensitive fields — never the raw goal text and never the
``source_goal_enc`` ciphertext. There is no ``goal`` field on any *output*
DTO; the raw goal enters only on ``GoalStartRequest`` (input) and is
field-encrypted by the service before it touches the DB.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.models.course import Difficulty


class BriefLevel(StrEnum):
    """Self-assessed learner level. Maps 1:1 to :class:`Difficulty` (DR-4)."""

    beginner = "beginner"
    intermediate = "intermediate"
    advanced = "advanced"


# The 1:1 mapping is intentionally total over BriefLevel; kept as an explicit
# table (not ``Difficulty(level.value)``) so a future divergence is a one-line
# edit here rather than a silent value-coupling.
_LEVEL_TO_DIFFICULTY: dict[BriefLevel, Difficulty] = {
    BriefLevel.beginner: Difficulty.beginner,
    BriefLevel.intermediate: Difficulty.intermediate,
    BriefLevel.advanced: Difficulty.advanced,
}


def difficulty_from_level(level: BriefLevel | str | None) -> Difficulty:
    """Map a brief level → course :class:`Difficulty` (DR-4 seam for S3.6).

    Accepts the enum, the raw string (``brief.level`` is a String(20) column),
    or ``None``. A missing/drifted level never crashes the build — it falls
    back to ``beginner`` (the safest default for an under-specified goal).
    """
    if level is None:
        return Difficulty.beginner
    try:
        return _LEVEL_TO_DIFFICULTY[BriefLevel(level)]
    except (ValueError, KeyError):
        return Difficulty.beginner


class BriefDraft(BaseModel):
    """The accumulated, still-mutable structured brief during elicitation.

    Every field is optional — they fill in across turns (FR-DEFINE-08). Also
    used as the ``edits`` payload on finalize (applied once, FR-DEFINE-03).
    """

    model_config = ConfigDict(extra="forbid")

    goal_summary: str | None = Field(default=None, max_length=2_000)
    level: BriefLevel | None = None
    prior_knowledge: str | None = Field(default=None, max_length=4_000)
    time_budget_hours: int | None = Field(default=None, ge=1, le=2_000)
    sessions_per_week: int | None = Field(default=None, ge=1, le=21)
    desired_outcomes: list[str] = Field(default_factory=list, max_length=20)
    format_prefs: dict[str, bool] = Field(default_factory=dict)
    language: str | None = Field(default=None, max_length=8)
    suggested_subject: str | None = Field(default=None, max_length=120)


class BriefEdits(BaseModel):
    """Last-mile partial edits applied once on finalize (FR-DEFINE-03 / Codex P2).

    Distinct from :class:`BriefDraft` (the accumulated-state transport) on ONE
    point that matters: the collection fields default to ``None``, NOT to empty
    ``[]`` / ``{}``. ``BriefDraft`` uses ``default_factory=list/dict`` so that a
    deserialized accumulated brief always carries concrete collections — but that
    is exactly wrong for an EDITS payload. The review UI sends only the scalar
    fields it lets the learner tweak (goal_summary / level / time budget /
    sessions) and renders ``desired_outcomes`` read-only; under ``BriefDraft`` the
    omitted ``desired_outcomes`` / ``format_prefs`` deserialize to ``[]`` / ``{}``
    and the finalize merge (``_apply_updates``, "apply when ``is not None``")
    overwrites the accumulated outcomes with empty — silently dropping the
    learner's outcomes right before the build reads them. Defaulting these to
    ``None`` here means an omitted collection is a NO-OP (merge skips it), while an
    EXPLICIT ``[]`` / ``{}`` still clears it (a deliberate edit is honoured).
    """

    model_config = ConfigDict(extra="forbid")

    goal_summary: str | None = Field(default=None, max_length=2_000)
    level: BriefLevel | None = None
    prior_knowledge: str | None = Field(default=None, max_length=4_000)
    time_budget_hours: int | None = Field(default=None, ge=1, le=2_000)
    sessions_per_week: int | None = Field(default=None, ge=1, le=21)
    desired_outcomes: list[str] | None = Field(default=None, max_length=20)
    format_prefs: dict[str, bool] | None = None
    language: str | None = Field(default=None, max_length=8)
    suggested_subject: str | None = Field(default=None, max_length=120)


class GoalStartRequest(BaseModel):
    """Open the elicitation with a fuzzy goal (the ONLY raw-goal input site)."""

    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1, max_length=4_000)


class GoalTurnRequest(BaseModel):
    """One learner reply in the bounded clarification conversation."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4_000)


class GoalTurnResponse(BaseModel):
    """The assistant's reply + the running brief + bounded-turn bookkeeping."""

    session_id: str
    assistant_message: str
    accumulated_brief: BriefDraft
    turns_used: int
    turns_remaining: int
    converged: bool


class BriefFinalizeRequest(BaseModel):
    """Freeze the brief, applying optional last-mile ``edits`` once.

    ``edits`` is a :class:`BriefEdits` (None-defaulted collections) rather than a
    :class:`BriefDraft` so a scalar-only edit from the review UI never clobbers
    the accumulated ``desired_outcomes`` / ``format_prefs`` with empty (Codex P2).
    """

    model_config = ConfigDict(extra="forbid")

    edits: BriefEdits | None = None


class BriefOut(BaseModel):
    """The finalized, immutable brief — STRUCTURED FIELDS ONLY (FR-PRIV-01).

    Deliberately omits the raw goal text and the ``source_goal_enc`` ciphertext.
    ``goal_summary`` is the non-sensitive paraphrase safe to surface.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    level: str | None = None
    time_budget_hours: int | None = None
    sessions_per_week: int | None = None
    prior_knowledge: str | None = None
    desired_outcomes: list[str] = Field(default_factory=list)
    goal_summary: str | None = None
    suggested_subject: str | None = None
    language: str | None = None
    finalized_at: datetime | None = None
