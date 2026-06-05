"""Goal-intake elicitation service (the "define" half of define-and-build).

S3.3 / FR-DEFINE-02/03/08/10 / R-M10 / DR-4. Orchestrates the bounded,
multi-turn clarification conversation that turns a learner's fuzzy goal into a
structured, immutable :class:`~app.models.learning_brief.LearningBrief`.

Design invariants:

* **Bounded (R-M10 / FR-DEFINE-02).** At most
  ``Settings.define_elicitation_max_turns`` assistant turns per conversation.
  The (cap+1)th ``take_turn`` raises ``define.turn_cap`` and makes NO LLM call.
* **Per-user session quota (R-M10 / R-G1).** Starting more than
  ``Settings.define_elicitation_sessions_24h`` sessions in the rolling window
  raises ``define.session_quota`` — a non-dollar DB-COUNT backstop (a started
  brief is a row), independent of the ``call_logged`` LLM request guard.
* **Deterministic convergence.** Convergence (level + time_budget +
  prior_knowledge + ≥1 outcome all present) is decided in Python, never trusted
  to the model, so tests are reproducible (FR-DEFINE-02 "asks only for fields
  still missing").
* **Immutable finalize (FR-DEFINE-03).** ``finalize`` stamps ``finalized_at``
  once and applies optional ``edits`` once; a second finalize (or any mutating
  turn after finalize) raises ``define.brief_finalized``.
* **Metered (FR-DEFINE-02).** Every LLM turn goes through
  :func:`call_logged` with a foreground-resolved :class:`LLMContext`
  (``feature="goal_elicitation"``) — BYOK-eligible per ADR-0027 §4 / DR-8; the
  decrypt happens only inside ``byok.build_provider``.
* **Privacy (FR-PRIV-01).** The raw goal is decrypted only into the in-request
  prompt builder (allowed — goal text may enter build prompts); it never enters
  a log, a trace summary, or a cross-user index. The persisted conversation
  memory is the accumulated *structured* brief (non-sensitive) plus the
  encrypted goal — no transcript is stored.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secrets_crypto
from app.core.config import get_settings
from app.core.errors import (
    DefineBriefFinalizedError,
    DefineSessionQuotaError,
    DefineTurnCapError,
)
from app.models.learning_brief import LearningBrief
from app.models.user import User
from app.repositories import learning_briefs as brief_repo
from app.schemas.learning_brief import (
    BriefDraft,
    BriefLevel,
    difficulty_from_level,
)
from app.services import byok as byok_service
from app.services import llm as llm_service
from app.services.byok import PLATFORM_CONTEXT, LLMContext
from app.services.llm_call_log import call_logged

log = structlog.get_logger(__name__)

# Re-exported so the authoring orchestrator (S3.6) imports the DR-4 seam from
# the service module the plan names.
__all__ = [
    "difficulty_from_level",
    "estimate_counts",
    "finalize",
    "start_session",
    "take_turn",
]

_FEATURE = "goal_elicitation"


# --------------------------------------------------------------------------- #
# LLM structured output
# --------------------------------------------------------------------------- #


class _BriefUpdate(BaseModel):
    """The structured slice the model returns each turn.

    The model proposes field updates (only the fields it learned this turn) +
    the next assistant message. Convergence is NOT trusted to the model — it is
    recomputed in Python from the merged state.
    """

    assistant_message: str = Field(default="", max_length=4_000)
    goal_summary: str | None = Field(default=None, max_length=2_000)
    level: BriefLevel | None = None
    prior_knowledge: str | None = Field(default=None, max_length=4_000)
    time_budget_hours: int | None = Field(default=None, ge=1, le=2_000)
    sessions_per_week: int | None = Field(default=None, ge=1, le=21)
    desired_outcomes: list[str] | None = Field(default=None, max_length=20)
    format_prefs: dict[str, bool] | None = None
    language: str | None = Field(default=None, max_length=8)
    suggested_subject: str | None = Field(default=None, max_length=120)


_SYSTEM_PROMPT = (
    "You are Lumen's goal-intake assistant. You help a SELF-DIRECTED LEARNER "
    "define a course they want to build FOR THEMSELVES to learn from. You are "
    "talking to the learner directly — never frame this as an instructor "
    "authoring for students.\n\n"
    "Your job: turn a fuzzy goal into a structured learning brief by asking "
    "SHORT, focused clarifying questions. Ask only about the fields still "
    "missing. The fields you need are: level (beginner/intermediate/advanced), "
    "time_budget_hours (total hours they can invest), prior_knowledge (what "
    "they already know), and at least one desired_outcome (a concrete thing "
    "they want to be able to do). Optionally: sessions_per_week, format_prefs, "
    "language, suggested_subject, and a one-line goal_summary.\n\n"
    "Reply ONLY with a JSON object matching this schema (no prose, no markdown "
    "fences): {assistant_message: string, goal_summary?: string, level?: "
    "'beginner'|'intermediate'|'advanced', prior_knowledge?: string, "
    "time_budget_hours?: int, sessions_per_week?: int, desired_outcomes?: "
    "[string], format_prefs?: object, language?: string, suggested_subject?: "
    "string}. Put only the fields you learned THIS turn (plus assistant_message)."
)


# --------------------------------------------------------------------------- #
# Deterministic convergence + estimate
# --------------------------------------------------------------------------- #


def _is_converged(brief: LearningBrief) -> bool:
    """Python-side completeness check (never trusted to the model).

    Converged when the four required fields are all present: level, time
    budget, prior knowledge, and ≥1 desired outcome (FR-DEFINE-02).
    """
    return bool(
        brief.level and brief.time_budget_hours and brief.prior_knowledge and brief.desired_outcomes
    )


def estimate_counts(time_budget_hours: int | None) -> tuple[int, int]:
    """Derive ``(target_modules, lessons_per_module)`` from the time budget.

    Deterministic bands (FR-DEFINE-16 / DR-4) consumed by the authoring
    orchestrator (S3.6):

    * ``<= 5h`` → 2-3 modules (low band → 2)
    * ``6-20h`` → 3-5 modules (mid band → 4)
    * ``> 20h`` → 5-8 modules (high band → 6)

    A missing budget defaults to the mid band so an under-specified brief still
    yields a reasonable course. ``lessons_per_module`` is a small fixed fan-out
    (3) — the orchestrator can refine, but the module count is the budget-driven
    signal the plan pins.
    """
    if not time_budget_hours or time_budget_hours <= 0:
        return (4, 3)
    if time_budget_hours <= 5:
        return (2, 3)
    if time_budget_hours <= 20:
        return (4, 3)
    return (6, 3)


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def to_draft(brief: LearningBrief) -> BriefDraft:
    """Project the accumulated (non-sensitive) brief state to a DTO."""
    return BriefDraft(
        goal_summary=brief.goal_summary,
        level=BriefLevel(brief.level) if brief.level else None,
        prior_knowledge=brief.prior_knowledge,
        time_budget_hours=brief.time_budget_hours,
        sessions_per_week=brief.sessions_per_week,
        desired_outcomes=list(brief.desired_outcomes or []),
        format_prefs=dict(brief.format_prefs or {}),
        language=brief.language,
        suggested_subject=brief.suggested_subject,
    )


def _apply_updates(brief: LearningBrief, update: _BriefUpdate | BriefDraft) -> None:
    """Merge non-None structured fields onto the brief (in-progress mutation)."""
    if update.goal_summary is not None:
        brief.goal_summary = update.goal_summary
    if update.level is not None:
        brief.level = update.level.value if isinstance(update.level, BriefLevel) else update.level
    if update.prior_knowledge is not None:
        brief.prior_knowledge = update.prior_knowledge
    if update.time_budget_hours is not None:
        brief.time_budget_hours = update.time_budget_hours
    if update.sessions_per_week is not None:
        brief.sessions_per_week = update.sessions_per_week
    if update.desired_outcomes is not None:
        brief.desired_outcomes = list(update.desired_outcomes)
    if update.format_prefs is not None:
        brief.format_prefs = dict(update.format_prefs)
    if update.language is not None:
        brief.language = update.language
    if update.suggested_subject is not None:
        brief.suggested_subject = update.suggested_subject


def _build_user_prompt(brief: LearningBrief, *, goal_text: str, message: str | None) -> str:
    """Render the per-turn user prompt.

    The raw decrypted ``goal_text`` lives ONLY here (in-request); it is never
    logged or persisted in clear. The accumulated structured state is included
    so the model asks only for what is still missing.
    """
    draft = to_draft(brief)
    known = draft.model_dump(mode="json", exclude_none=True)
    lines = [f"Learner's goal: {goal_text}"]
    if message:
        lines.append(f"Learner's latest reply: {message}")
    lines.append(f"Known so far (do not re-ask these): {known}")
    missing = [
        name
        for name, present in (
            ("level", bool(brief.level)),
            ("time_budget_hours", bool(brief.time_budget_hours)),
            ("prior_knowledge", bool(brief.prior_knowledge)),
            ("desired_outcomes", bool(brief.desired_outcomes)),
        )
        if not present
    ]
    if missing:
        lines.append(f"Still missing (ask about these): {missing}")
    else:
        lines.append(
            "All required fields are present. Confirm the brief back to the "
            "learner in one sentence and ask them to review and finalize."
        )
    return "\n".join(lines)


async def _call_model(
    db: AsyncSession,
    *,
    user_id: str,
    brief: LearningBrief,
    goal_text: str,
    message: str | None,
    ctx: LLMContext,
) -> _BriefUpdate:
    """One metered LLM turn → parsed :class:`_BriefUpdate`.

    Routed through :func:`call_logged` with the resolved foreground
    :class:`LLMContext` (BYOK-eligible, ADR-0027 §4). On a malformed reply the
    turn degrades gracefully to an empty update + a generic prompt rather than
    raising — the deterministic convergence check still governs the flow and
    the turn cap protects against loops.
    """
    provider, billing_mode = await byok_service.build_provider(db, ctx)
    messages = [
        llm_service.ChatMessage(role="system", content=_SYSTEM_PROMPT),
        llm_service.ChatMessage(
            role="user", content=_build_user_prompt(brief, goal_text=goal_text, message=message)
        ),
    ]
    response = await call_logged(
        provider,
        messages,
        user_id=user_id,
        feature=_FEATURE,
        session=db,
        temperature=0.3,
        billing_mode=billing_mode,
    )
    return _parse_update(response.text)


def _parse_update(raw: str) -> _BriefUpdate:
    """Parse the model's JSON reply; degrade to an empty update on failure."""
    text = (raw or "").strip()
    # Tolerate markdown fences a model sometimes adds despite instructions.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    try:
        return _BriefUpdate.model_validate_json(text)
    except ValidationError:
        log.info("goal_elicitation_unparseable_reply", feature=_FEATURE)
        return _BriefUpdate(assistant_message="Could you tell me a bit more about your goal?")


# --------------------------------------------------------------------------- #
# Public service API
# --------------------------------------------------------------------------- #


async def start_session(
    db: AsyncSession, *, user: User, goal: str, ctx: LLMContext = PLATFORM_CONTEXT
) -> tuple[LearningBrief, str]:
    """Open an elicitation session for ``user`` with a fuzzy ``goal``.

    Enforces the per-user session quota (R-M10) BEFORE any work, encrypts the
    goal into ``source_goal_enc`` (DR-22), creates an in-progress brief, then
    runs the first metered clarification turn. Returns ``(brief, assistant_message)``.
    """
    s = get_settings()
    window_seconds = int(s.define_elicitation_session_window_hours) * 3600
    used = await brief_repo.count_sessions_in_window(
        db, owner_id=user.id, window_seconds=window_seconds
    )
    if used >= int(s.define_elicitation_sessions_24h):
        raise DefineSessionQuotaError(
            "You've started too many course-definition sessions recently. Try again later.",
            details={
                "dimension": "sessions",
                "used": used,
                "limit": int(s.define_elicitation_sessions_24h),
            },
        )

    enc = secrets_crypto.encrypt(goal.encode("utf-8"))
    brief = await brief_repo.create_brief(db, owner_id=user.id, source_goal_enc=enc)

    update = await _call_model(
        db, user_id=user.id, brief=brief, goal_text=goal, message=None, ctx=ctx
    )
    _apply_updates(brief, update)
    brief.turns_used = 1
    await db.flush()
    return brief, update.assistant_message


async def take_turn(
    db: AsyncSession,
    *,
    user: User,
    session_id: str,
    message: str,
    ctx: LLMContext = PLATFORM_CONTEXT,
) -> tuple[LearningBrief, str, bool]:
    """Advance the conversation by one learner reply.

    Returns ``(brief, assistant_message, converged)``. Enforces:

    * immutability — a finalized brief raises ``define.brief_finalized``;
    * the turn cap — the (cap+1)th turn raises ``define.turn_cap`` and makes NO
      LLM call (FR-DEFINE-02 / R-M10).

    Returns ``None`` (caller renders 404) when the session is unknown / not the
    user's — handled by :func:`brief_repo.get_active_session` returning None.
    """
    brief = await brief_repo.get_active_session(db, session_id=session_id, owner_id=user.id)
    if brief is None:
        return None  # type: ignore[return-value]
    if brief.finalized_at is not None:
        raise DefineBriefFinalizedError("This brief is finalized and can no longer be edited.")

    s = get_settings()
    cap = int(s.define_elicitation_max_turns)
    if brief.turns_used >= cap:
        # The cap is spent — no LLM call. The client should finalize.
        raise DefineTurnCapError(
            "You've reached the clarification limit for this brief. "
            "Please review and finalize what we have.",
            details={"turns_used": brief.turns_used, "limit": cap},
        )

    update = await _call_model(
        db, user_id=user.id, brief=brief, goal_text=_decrypt_goal(brief), message=message, ctx=ctx
    )
    _apply_updates(brief, update)
    brief.turns_used += 1
    await db.flush()
    return brief, update.assistant_message, _is_converged(brief)


async def finalize(
    db: AsyncSession,
    *,
    user: User,
    session_id: str,
    edits: BriefDraft | None = None,
) -> LearningBrief | None:
    """Freeze the brief (FR-DEFINE-03), applying optional ``edits`` once.

    Returns the finalized brief, or ``None`` (caller renders 404) when the
    session is unknown / not the user's. A second finalize raises
    ``define.brief_finalized`` and leaves the row unchanged.
    """
    brief = await brief_repo.get_active_session(db, session_id=session_id, owner_id=user.id)
    if brief is None:
        return None
    if brief.finalized_at is not None:
        raise DefineBriefFinalizedError("This brief is already finalized.")

    if edits is not None:
        _apply_updates(brief, edits)
    brief.finalized_at = datetime.now(UTC)
    await db.flush()
    return brief


def _decrypt_goal(brief: LearningBrief) -> str:
    """Decrypt the goal for the in-request prompt builder ONLY (FR-PRIV-01)."""
    return secrets_crypto.decrypt(brief.source_goal_enc).decode("utf-8")
