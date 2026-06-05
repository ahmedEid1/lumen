"""Self-critique authoring orchestrator (Lumen v2 Phase I3).

The multi-step reasoning moat. Where the Phase E2 ``ai_authoring``
service does a single-shot outline → lessons → quizzes call, this
orchestrator runs:

::

    Researcher (Tavily + catalog neighbours)
        → Outliner (LLM, structured)
        → Critic (LLM, structured) ↺ Reviser (LLM, structured)
        → Lesson-drafter (LLM × N, via ai_authoring.generate_lesson_body
                              + .generate_quiz)
        → Final-critic (LLM, structured)

Every step writes one :class:`CourseDraftTrace` row so the instructor
can replay the agent's reasoning in the studio surface. Cost-meter
rows ride the same path through :func:`call_logged`.

Hard caps:

* Max 3 outline revisions (revisions_used ∈ ``{0, 1, 2, 3}``).
* Max 6 LLM calls in the outline phase
  (researcher-summary disabled in v1 — researcher does no LLM call;
  outliner = 1, critic = up to 4, reviser = up to 3, capped at 6).
* Final-critic always runs once at the end.
* No per-lesson critique loop in v1 — the lesson drafter calls
  :func:`ai_authoring.generate_lesson_body` + :func:`ai_authoring.generate_quiz`
  which carry their own retry-once-on-malformed-JSON behaviour.

Why no LLM in the researcher. The bundle is small enough (5-8
snippets + 5 catalog rows) to feed the outliner verbatim through
:meth:`ResearchBundle.to_prompt_block`. Adding a compression LLM
call would double the latency for no measurable quality gain on
the outliner's behaviour. Easy to wire in later if the bundle
grows; for now we trust the outliner to filter.

Backwards compatibility. The existing ``/studio/ai/outline``,
``.../lesson-body``, ``.../quiz`` endpoints stay untouched; this
orchestrator is reached via a new ``POST /studio/ai/draft-course``
endpoint. The instructor decides which path to take — fast
single-shot for "I trust the model" use, or the full critique-revise
loop for "show me how it thinks."

**Persistence shape.** One :class:`Course` row + N :class:`Module` +
M :class:`Lesson` rows (all in ``draft`` status), AND N
:class:`CourseDraftTrace` rows for the reasoning chain. The
``course_id`` column on early trace rows (researcher + initial
outliner + first critic, written before the course exists) is
back-filled at the end of the orchestration so the course-scoped
read endpoint sees the full timeline.
"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import (
    AccessRevokedError,
    AppError,
    DefineBriefNotFinalizedError,
    NotFoundError,
)
from app.core.ids import new_id
from app.core.logging import get_logger
from app.models.course import (
    Course,
    CourseStatus,
    Difficulty,
    Lesson,
    LessonType,
    Module,
    Visibility,
)
from app.models.course_draft_trace import (
    DRAFT_STATUS_ERROR,
    DRAFT_STATUS_OK,
    DRAFT_STEP_CRITIC,
    DRAFT_STEP_FINAL_CRITIC,
    DRAFT_STEP_LESSON_DRAFTER,
    DRAFT_STEP_OUTLINER,
    DRAFT_STEP_RESEARCHER,
    DRAFT_STEP_REVISER,
    CourseDraftTrace,
)
from app.models.llm_call import SYSTEM_USER_ID
from app.models.user import User
from app.repositories import courses as courses_repo
from app.services import account as account_service
from app.services import ai_authoring
from app.services import byok as byok_service
from app.services import llm as llm_service
from app.services.authoring_subagents import ResearchBundle, run_researcher
from app.services.byok import PLATFORM_CONTEXT, LLMContext
from app.services.courses import _unique_slug
from app.services.llm_call_log import call_logged

log = get_logger(__name__)


# ---------- Constants ----------


# Feature slug roots — child step slugs are derived as
# ``f"{FEATURE_ROOT}.{step}"`` and surface in the H1 cost meter
# rolled-up by step type.
FEATURE_ROOT = "authoring"
FEATURE_RESEARCHER = f"{FEATURE_ROOT}.researcher"
FEATURE_OUTLINER = f"{FEATURE_ROOT}.outliner"
FEATURE_CRITIC = f"{FEATURE_ROOT}.critic"
FEATURE_REVISER = f"{FEATURE_ROOT}.reviser"
FEATURE_LESSON_DRAFTER = f"{FEATURE_ROOT}.lesson_drafter"
FEATURE_FINAL_CRITIC = f"{FEATURE_ROOT}.final_critic"

# Maximum number of revise → critic iterations. After 3 revisions
# the loop stops regardless of the critic's score — at that point
# either the outline is good enough or the prompt is fighting us,
# and burning a fourth round won't change either.
MAX_REVISIONS = 3

# Mean-score threshold the critic must reach for the loop to stop
# accepting the current outline. Anything below this triggers a
# revision (subject to MAX_REVISIONS). The number is half-empirical:
# 4.0/5 is "no obvious gaps" in our hand-graded test outlines.
ACCEPTANCE_MEAN_SCORE = 4.0

# Hard cap on LLM calls in the outline phase. The math:
# outliner (1) + critic (≤4) + reviser (≤3) = ≤8 in theory, but we
# cap at 6 so a pathological "critic always says 3.something"
# pattern still degrades cleanly. Researcher does no LLM call in
# v1 (we feed the snippet bundle directly to the outliner).
MAX_OUTLINE_PHASE_LLM_CALLS = 6


# ---------- Public schemas ----------


class CriticScores(BaseModel):
    """Three-axis critic scoring, each axis 0-5 inclusive.

    The reviser fires when ``mean < ACCEPTANCE_MEAN_SCORE`` AND the
    revision budget hasn't been spent. Why three axes and not one
    "overall" score: separating coverage / arc / scope makes the
    revise prompt actionable — the reviser knows *which* axis to
    repair.
    """

    model_config = ConfigDict(frozen=True)

    coverage: int = Field(ge=0, le=5)
    learning_arc: int = Field(ge=0, le=5)
    scope: int = Field(ge=0, le=5)

    @property
    def mean(self) -> float:
        """Arithmetic mean of the three axes."""
        return (self.coverage + self.learning_arc + self.scope) / 3.0


class CritiqueResult(BaseModel):
    """One critic / final-critic output.

    ``weak_spots`` are concrete prose suggestions the reviser
    consumes; ``rationale`` is a human-readable paragraph the
    studio surface renders verbatim.
    """

    model_config = ConfigDict(frozen=True)

    scores: CriticScores
    weak_spots: list[str] = Field(default_factory=list, max_length=5)
    rationale: str = Field(default="", max_length=2_000)


class OrchestratorResult(BaseModel):
    """End-to-end output of one :func:`draft_course` call.

    The API endpoint returns this as-is. The studio surface uses
    ``draft_id`` to fetch the full trace via the read endpoint.
    """

    model_config = ConfigDict(frozen=True)

    course_id: str
    slug: str
    module_count: int
    lesson_count: int
    final_score: CriticScores
    final_rationale: str
    draft_id: str
    revisions_used: int


# ---------- Helpers: parsing ----------


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _strip_json_fence(raw: str) -> str:
    """Pull JSON out of a model reply, even if wrapped in ``` fences."""
    fence = _JSON_FENCE_RE.search(raw)
    if fence:
        return fence.group(1).strip()
    return raw.strip()


def _try_parse[M: BaseModel](raw: str, model: type[M]) -> tuple[M | None, str | None]:
    """Parse ``raw`` as JSON + validate against ``model``.

    Returns ``(instance, None)`` on success, ``(None, error)`` on
    failure. Single error path so the retry logic stays branchless.
    """
    body = _strip_json_fence(raw)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return None, f"JSON parse error: {exc.msg} at line {exc.lineno}"
    try:
        return model.model_validate(payload), None
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []))
        msg = first.get("msg", "validation error")
        return None, f"validation error at {loc or '<root>'}: {msg}"


# ---------- Helpers: trace persistence ----------


async def _record_trace(
    db: AsyncSession,
    *,
    draft_id: str,
    user_id: str,
    step: str,
    step_index: int,
    course_id: str | None = None,
    parent_trace_id: str | None = None,
    parent_call_id: str | None = None,
    payload: dict[str, Any] | None = None,
    duration_ms: int = 0,
    status: str = DRAFT_STATUS_OK,
) -> CourseDraftTrace | None:
    """Persist one ``course_draft_traces`` row. Best-effort.

    Mirrors :func:`agent_tracer.record_step` exactly: SAVEPOINT-isolated
    so a transient DB hiccup on the trace doesn't roll back the
    orchestrator's actual work. Returns ``None`` on failure; the
    caller never depends on the returned row being non-None for
    correctness (parent_trace_id is optional everywhere in v1).
    """
    try:
        async with db.begin_nested():
            row = CourseDraftTrace(
                draft_id=draft_id,
                course_id=course_id,
                user_id=user_id,
                step=step,
                step_index=step_index,
                parent_trace_id=parent_trace_id,
                parent_call_id=parent_call_id,
                payload=payload or {},
                duration_ms=duration_ms,
                status=status,
            )
            db.add(row)
            await db.flush()
            await db.refresh(row)
            return row
    except SQLAlchemyError:
        log.exception(
            "course_draft_trace_persist_failed",
            draft_id=draft_id,
            user_id=user_id,
            step=step,
        )
        return None


async def _backfill_course_id(db: AsyncSession, *, draft_id: str, course_id: str) -> None:
    """Stamp ``course_id`` on every trace row tied to ``draft_id``.

    Early steps (researcher, first outliner pass, first critic)
    write rows with ``course_id=None`` because the course row
    doesn't exist yet. Once the orchestrator persists the course,
    we back-fill so the course-scoped read endpoint sees the full
    timeline.

    Wrapped in a SAVEPOINT for the same reason as ``_record_trace``:
    a hiccup here must not roll back the persisted course rows.
    """
    try:
        async with db.begin_nested():
            stmt = (
                update(CourseDraftTrace)
                .where(
                    CourseDraftTrace.draft_id == draft_id,
                    CourseDraftTrace.course_id.is_(None),
                )
                .values(course_id=course_id)
            )
            await db.execute(stmt)
    except SQLAlchemyError:
        log.exception(
            "course_draft_trace_backfill_failed",
            draft_id=draft_id,
            course_id=course_id,
        )


# ---------- Prompts (system-side, kept as module constants) ----------


_OUTLINER_WITH_RESEARCH_SYSTEM = """\
You are a course-design assistant working on the first pass of an \
outline. You are helping a SELF-DIRECTED LEARNER build a course FOR \
THEMSELVES to learn from — the learner described a goal, which a goal- \
intake step distilled into the brief + explicit constraints below; a \
research sub-agent has gathered context for you. Use them to scope the \
outline so it fits the learner's level, time budget, and desired \
outcomes.

Return a single JSON object with this exact shape (no surrounding \
prose, no markdown code fences):

{
  "title": "Short course title",
  "overview": "1-2 paragraphs the instructor can paste straight into \
the course detail page",
  "modules": [
    {
      "title": "Module title",
      "lessons": [
        { "title": "Lesson title", "type": "text" },
        { "title": "Quiz title",  "type": "quiz" }
      ]
    }
  ]
}

Rules:
- Honour the CONSTRAINTS block: aim for the target module count it \
gives (derived from the learner's time budget), pitch every lesson at \
the stated level, and make sure the outline delivers the learner's \
required outcomes.
- Each module has 3-5 lessons.
- Most lessons should be "text". Every module should end with one \
"quiz" lesson that checks the module's material.
- Only use "text" or "quiz" as the lesson type.
- Titles must be specific, not generic.
- Treat the WEB block as background only; the CATALOG block lists \
existing Lumen courses so you can avoid duplicating their angles.
"""


_CRITIC_SYSTEM_PROMPT = """\
You are a course-design critic. The learner's brief, the explicit \
CONSTRAINTS (level, time budget → target module count, required \
outcomes), and the proposed outline are provided. Rate the outline on \
three axes, each 0-5 inclusive:

  - "coverage"     — does the outline cover the brief's stated \
scope AND deliver the learner's required outcomes? Missing major \
topics or an unmet outcome drops this score.
  - "learning_arc" — do later modules genuinely build on earlier \
ones? A flat list of topics is a 2; a deliberate progression is \
a 5.
  - "scope"        — is the outline sized to the learner's time \
budget (the CONSTRAINTS give a target module count) and pitched at \
the stated level — neither too broad nor too narrow?

Identify up to THREE weak spots — concrete, actionable prose \
suggestions the reviser can act on. Examples:

  - "Module 2 is mis-named — its lessons cover X but the title \
implies Y."
  - "Add a lesson on Z before the quiz in module 3; the brief \
mentioned Z but no lesson covers it."
  - "Module 5 duplicates module 2's material; merge or drop one."

Return strict JSON with this exact shape — no prose, no markdown \
fences:

{
  "scores": {"coverage": 4, "learning_arc": 3, "scope": 5},
  "weak_spots": [
    "Module 2 is mis-named ...",
    "Add a lesson on Z ..."
  ],
  "rationale": "One short paragraph (≤2 sentences) summarising \
the overall verdict."
}

Hard rules:
- All three axes must be integers 0-5 inclusive.
- ``weak_spots`` is a list of 0-3 strings, each ≤300 chars.
- ``rationale`` is ≤2000 chars.
- Return ONE JSON object. No preamble, no fences.
"""


_REVISER_SYSTEM_PROMPT = """\
You are a course-design reviser. The learner's brief, the explicit \
CONSTRAINTS (level, time budget → target module count, required \
outcomes), the previous outline, and a critic's weak-spot notes are \
provided. Produce a revised outline that addresses the weak spots and \
honours the constraints while keeping the parts the critic didn't flag.

Return a single JSON object with the same shape as an outliner \
reply (no surrounding prose, no markdown code fences):

{
  "title": "Short course title",
  "overview": "1-2 paragraphs ...",
  "modules": [
    {
      "title": "Module title",
      "lessons": [
        { "title": "Lesson title", "type": "text" },
        { "title": "Quiz title",  "type": "quiz" }
      ]
    }
  ]
}

Hard rules (same as the outliner):
- 3-6 modules.
- Each module has 3-5 lessons.
- Only "text" or "quiz" as the lesson type.
- Titles specific, not generic.
- ADDRESS every weak spot the critic listed. If you choose to \
ignore one, explain in the overview WHY.
"""


_FINAL_CRITIC_SYSTEM_PROMPT = """\
You are the final critic for an AI-drafted course. The self-directed \
learner who is building this course to study from will see your score \
before they start learning. The brief, the explicit CONSTRAINTS (level, \
time budget, required outcomes), the full outline, and the per-lesson \
body counts are provided.

Rate the course on the same three axes, each 0-5 inclusive:

  - "coverage"     — does the finished course deliver on the brief \
AND the learner's required outcomes?
  - "learning_arc" — do the modules + lessons actually build on \
each other?
  - "scope"        — is the depth right for the learner's stated \
level and time budget?

Return strict JSON with this exact shape — no prose, no markdown \
fences:

{
  "scores": {"coverage": 4, "learning_arc": 4, "scope": 4},
  "weak_spots": [
    "Lesson 3.2 is shorter than its siblings — consider expanding."
  ],
  "rationale": "One short paragraph summarising whether the \
instructor should publish as-is or revise before going live."
}

Hard rules:
- All three axes must be integers 0-5 inclusive.
- ``weak_spots`` is a list of 0-5 strings, each ≤300 chars.
- ``rationale`` is ≤2000 chars.
- Return ONE JSON object. No preamble, no fences.
"""


# ---------- Brief → build threading (DR-4 / S3.6) ----------


class _BuildBrief(BaseModel):
    """In-request, decrypted view of a finalized :class:`LearningBrief`.

    The orchestrator works against this value object instead of the raw model so
    the decrypted goal text is decrypted exactly ONCE (FR-PRIV-01) and the
    constraint plumbing (level / time budget → module estimate / outcomes) is a
    single, testable surface. ``goal_text`` is the only sensitive field — it is
    fed into prompts (allowed) but NEVER into a trace summary or log
    (``goal_summary`` is the non-sensitive paraphrase used for traces).
    """

    model_config = ConfigDict(frozen=True)

    brief_id: str
    goal_text: str
    goal_summary: str
    difficulty: Difficulty
    level: str
    time_budget_hours: int | None
    target_modules: int
    desired_outcomes: list[str]
    desired_subject_hint: str | None


def _load_build_brief(brief) -> _BuildBrief:
    """Project a finalized ``LearningBrief`` ORM row → :class:`_BuildBrief`.

    Decrypts the goal once (DR-22 / FR-PRIV-01). Raises
    ``define.brief_not_finalized`` if the brief was never finalized (FR-DEFINE-07:
    a build starts only on explicit confirmation). Difficulty + module estimate
    are derived through the DR-4 seams in ``services.learning_brief``.
    """
    from app.core import secrets_crypto
    from app.schemas.learning_brief import difficulty_from_level
    from app.services.learning_brief import estimate_counts

    if brief.finalized_at is None:
        raise DefineBriefNotFinalizedError(
            "Review and confirm your course brief before building.",
            details={"brief_id": brief.id},
        )
    goal_text = secrets_crypto.decrypt(brief.source_goal_enc).decode("utf-8")
    target_modules, _ = estimate_counts(brief.time_budget_hours)
    # goal_summary is non-sensitive; fall back to a generic label (never the raw
    # goal) when the learner never gave one, so traces stay leak-free.
    summary = brief.goal_summary or "a self-directed learning goal"
    return _BuildBrief(
        brief_id=brief.id,
        goal_text=goal_text,
        goal_summary=summary,
        difficulty=difficulty_from_level(brief.level),
        level=brief.level or "beginner",
        time_budget_hours=brief.time_budget_hours,
        target_modules=target_modules,
        desired_outcomes=list(brief.desired_outcomes or []),
        desired_subject_hint=brief.suggested_subject,
    )


async def _assert_build_not_cancelled(db: AsyncSession, course_id: str) -> None:
    """R-S10 cooperative-cancel fence for the build job (S3.8 / DR-1a).

    Re-reads ``course.status`` straight from the DB (NOT the identity map, which a
    sibling cancel-build request can't have mutated in THIS session) and raises
    ``AccessRevokedError`` if the owner cancelled the build mid-run (status flipped
    to ``build_failed`` by :func:`courses.cancel_build`). Called at the per-lesson
    phase boundary so a cancel during the expensive lesson-drafting loop aborts
    before the next lesson-body LLM call fires (no further partial work).
    """
    from app.core.errors import AccessRevokedError

    status_now = (
        await db.execute(
            select(Course.status)
            .where(Course.id == course_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if status_now == CourseStatus.build_failed.value or status_now == CourseStatus.build_failed:
        raise AccessRevokedError("This build was cancelled.", code="define.build_cancelled")


async def _resolve_subject(db: AsyncSession, suggested: str | None):
    """Resolve the build's subject (FR-DEFINE-12).

    Match the learner's ``suggested_subject`` to a live :class:`Subject` by slug
    first, then by case-insensitive title; fall back to the reserved
    ``personal-self-directed`` subject when there is no match (or no suggestion).
    A self-serve build must NEVER hard-fail on the admin-only subject taxonomy —
    so this never raises ``authoring.subject_not_found`` (that path is reserved
    for the legacy instructor ``/studio/ai/draft-course`` flow, which is gone for
    the define entry).

    The Personal subject is seeded idempotently by migration 0051 + the demo
    seed; if it is somehow absent we raise a clear ``define.personal_subject_missing``
    so the operator fixes the seed rather than the learner seeing a vendor 404.
    """
    from app.models.course import Subject

    if suggested:
        by_slug = await courses_repo.get_subject_by_slug(db, suggested)
        if by_slug is not None:
            return by_slug
        # Fall back to a case-insensitive title match before Personal.
        from sqlalchemy import func, select

        by_title = (
            await db.execute(
                select(Subject).where(func.lower(Subject.title) == suggested.strip().lower())
            )
        ).scalar_one_or_none()
        if by_title is not None:
            return by_title

    personal_slug = get_settings().personal_subject_slug
    personal = await courses_repo.get_subject_by_slug(db, personal_slug)
    if personal is None:
        raise NotFoundError(
            "The reserved Personal subject is not seeded — run the seed/migration.",
            code="define.personal_subject_missing",
        )
    return personal


def _constraints_block(bb: _BuildBrief) -> str:
    """Render the explicit constraint lines DR-4 injects into every build prompt.

    The critic scores the outline against these (DR-4 "the critic scores the
    outline against the budget"). Contains the level, the time budget, the
    budget-derived target module count, and the required outcomes — but NEVER the
    raw goal (that rides the dedicated ``Learner's goal`` line in the user
    message, which is allowed in prompts but not in traces).
    """
    budget = f"{bb.time_budget_hours} hours" if bb.time_budget_hours else "unspecified"
    outcomes = "\n".join(f"  - {o}" for o in bb.desired_outcomes) or "  - (none specified)"
    return (
        "CONSTRAINTS:\n"
        f"- Target level: {bb.level}.\n"
        f"- Time budget: {budget} → aim for ~{bb.target_modules} modules.\n"
        "- Required outcomes (the course MUST enable the learner to):\n"
        f"{outcomes}"
    )


# ---------- LLM call helpers ----------


async def _chat_with_retry[M: BaseModel](
    db: AsyncSession,
    *,
    user_id: str,
    system: str,
    user: str,
    model: type[M],
    feature: str,
    temperature: float = 0.4,
    ctx: LLMContext = PLATFORM_CONTEXT,
) -> tuple[M | None, str, str | None]:
    """Single LLM call + one retry on malformed JSON.

    Returns ``(parsed, raw_text, error)``. On success ``parsed`` is
    non-None and ``error`` is None; on double-failure ``parsed`` is
    None, ``raw_text`` carries the last reply we saw, and ``error``
    explains the failure.

    Routed through :func:`call_logged` so every turn lands a metered
    ``llm_calls`` row tagged with ``feature``. Both turns of a retry
    pay separately — that's the right shape: the second turn really
    is extra spend the operator should see in the cost dashboard.
    """
    # S5.12/DR-8: BYOK for a user-initiated authoring draft; platform for the
    # default ctx. The decrypt happens inside byok.build_provider only.
    provider, billing_mode = await byok_service.build_provider(db, ctx)
    messages = [
        llm_service.ChatMessage(role="system", content=system),
        llm_service.ChatMessage(role="user", content=user),
    ]
    response = await call_logged(
        provider,
        messages,
        user_id=user_id,
        feature=feature,
        session=db,
        temperature=temperature,
        billing_mode=billing_mode,
    )
    raw = response.text
    parsed, err = _try_parse(raw, model)
    if parsed is not None:
        return parsed, raw, None

    # One-shot retry — quote the parse / validation error back to
    # the model so it can self-correct. We drop the temperature on
    # the retry so the model leans toward "fix the JSON" rather
    # than "be creative again."
    messages.extend(
        [
            llm_service.ChatMessage(role="assistant", content=raw),
            llm_service.ChatMessage(
                role="user",
                content=(
                    "Your previous response could not be parsed.\n"
                    f"Error: {err}\n\n"
                    "Reply with a corrected JSON object matching the "
                    "schema exactly. No prose, no markdown fences."
                ),
            ),
        ]
    )
    response2 = await call_logged(
        provider,
        messages,
        user_id=user_id,
        feature=feature,
        session=db,
        temperature=max(0.1, temperature - 0.3),
        billing_mode=billing_mode,
    )
    raw2 = response2.text
    parsed2, err2 = _try_parse(raw2, model)
    if parsed2 is not None:
        return parsed2, raw2, None
    return None, raw2, err2 or err


# ---------- Lesson-drafter ----------


async def _draft_lesson_content(
    db: AsyncSession,
    *,
    user_id: str,
    course_title: str,
    course_overview: str,
    lesson_title: str,
    lesson_type: LessonType,
    ctx: LLMContext = PLATFORM_CONTEXT,
) -> dict[str, Any]:
    """Draft one lesson's body + quiz via the existing E2 helpers.

    Returns the ``lesson.data`` JSONB blob ready to persist. The
    quiz path returns a ``{type: "quiz", pass_score, questions}``
    blob; the text path returns ``{type: "text", body_markdown,
    blocks}``. Both shapes match what Phase E2 ``commit_outline``
    placeholder builder produces — so the lessons render in the
    editor without a follow-up edit.

    On LLM failure (after the helper's own retry), falls back to
    the same placeholder content the E2 commit_outline path uses.
    That way one bad lesson generation doesn't take down a whole
    course draft — the instructor sees a placeholder they can
    re-generate from the editor.
    """
    context = f"{course_title}: {course_overview[:300]}"
    if lesson_type == LessonType.quiz:
        try:
            questions = await ai_authoring.generate_quiz(
                lesson_title=lesson_title,
                course_context=context,
                n=4,
                session=db,
                user_id=user_id,
                ctx=ctx,
            )
            return {
                "type": "quiz",
                "pass_score": 60,
                "questions": [q.model_dump() for q in questions],
            }
        except Exception as exc:
            log.warning(
                "authoring_lesson_drafter_quiz_failed",
                lesson_title=lesson_title[:120],
                error_kind=type(exc).__name__,
            )
            return _placeholder_quiz_data()

    # text-type lessons
    try:
        doc = await ai_authoring.generate_lesson_body(
            lesson_title=lesson_title,
            course_context=context,
            session=db,
            user_id=user_id,
            ctx=ctx,
        )
        return {
            "type": "text",
            "body_markdown": "",
            "blocks": doc,
        }
    except Exception as exc:
        log.warning(
            "authoring_lesson_drafter_body_failed",
            lesson_title=lesson_title[:120],
            error_kind=type(exc).__name__,
        )
        return _placeholder_text_data()


def _placeholder_quiz_data() -> dict[str, Any]:
    """Minimum-valid quiz payload — same shape as E2's commit_outline."""
    return {
        "type": "quiz",
        "pass_score": 60,
        "questions": [
            {
                "id": "q1",
                "prompt": "Draft question — replace before publishing",
                "kind": "single",
                "choices": [
                    {"id": "a", "text": "Option A"},
                    {"id": "b", "text": "Option B"},
                ],
                "answer_keys": ["a"],
            }
        ],
    }


def _placeholder_text_data() -> dict[str, Any]:
    """Minimum-valid text payload — same shape as E2's commit_outline."""
    placeholder = "Draft — replace before publishing."
    return {
        "type": "text",
        "body_markdown": placeholder,
        "blocks": {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": placeholder}],
                }
            ],
        },
    }


# ---------- Main entry point ----------


async def draft_course(
    db: AsyncSession,
    *,
    user: User,
    brief_id: str,
    ctx: LLMContext = PLATFORM_CONTEXT,
    existing_course_id: str | None = None,
) -> OrchestratorResult:
    """Run the full self-critique authoring pipeline against a finalized brief.

    DR-4 / S3.6: the build is driven by a finalized
    :class:`~app.models.learning_brief.LearningBrief` (``brief_id``), NOT a raw
    free-form string + subject slug. Difficulty derives from ``brief.level``,
    learning outcomes from the brief, the module-count target from
    ``time_budget_hours``, and the level/budget/outcomes are injected as explicit
    constraint lines into the outliner + critic + reviser + final-critic prompts.
    The subject auto-resolves to the learner's ``suggested_subject`` when it
    matches a live Subject, else to the reserved ``personal-self-directed``
    subject (FR-DEFINE-12 — self-serve build never 404s on the admin taxonomy).
    The built course is ``visibility=private, status=draft`` (FR-DEFINE-11).

    On success, persists one ``courses`` row + N ``modules`` + M
    ``lessons`` (all draft + private) + K ``course_draft_traces`` rows.
    Returns an :class:`OrchestratorResult`.

    ``existing_course_id`` (S3.7 shell-first): when the S3.7 build wrapper has
    already committed a durable in-flight shell, the pipeline FILLS that exact
    course row (title/overview/outcomes + modules/lessons) instead of inserting a
    new one — so a successful build is ONE course (the shell), not two. ``None``
    (the legacy / direct-call path) inserts a fresh course.

    On an un-finalized brief, raises ``define.brief_not_finalized`` (FR-DEFINE-07)
    before any LLM tokens are burned. On unrecoverable LLM failure, raises
    :class:`AppError` (``authoring.outliner_failed``); the S3.7 build wrapper
    (:func:`build_from_brief`) is responsible for translating that into the
    ``build_failed`` course state + a normalized error.

    Important: this function commits its own course rows but does
    NOT commit the outer transaction — the caller's API handler is
    responsible for committing (via the DBSession dependency's
    request-scoped commit, same pattern as every other service
    method in the codebase).
    """
    from app.repositories import learning_briefs as brief_repo

    user_id = user.id

    brief_row = await brief_repo.get_active_session(db, session_id=brief_id, owner_id=user_id)
    if brief_row is None:
        # Existence-hide: unknown or another user's brief is a 404.
        raise NotFoundError("Goal session not found", code="define.session_not_found")
    # Decrypt the goal ONCE + derive all DR-4 constraints; raises
    # define.brief_not_finalized when the brief was never confirmed (FR-DEFINE-07).
    bb = _load_build_brief(brief_row)

    # Subject auto-resolution (FR-DEFINE-12): match the learner's suggested
    # subject to a live Subject by slug; fall back to the reserved Personal
    # subject so a self-serve build NEVER raises authoring.subject_not_found.
    subject = await _resolve_subject(db, bb.desired_subject_hint)

    return await _run_pipeline(
        db,
        user=user,
        bb=bb,
        subject_id=subject.id,
        ctx=ctx,
        existing_course_id=existing_course_id,
    )


async def draft_course_from_text(
    db: AsyncSession,
    *,
    user: User,
    brief: str,
    subject_slug: str,
    ctx: LLMContext = PLATFORM_CONTEXT,
) -> OrchestratorResult:
    """LEGACY raw-brief build path for the instructor ``/studio/ai/draft-course``.

    The pre-S3 single-paragraph free-form entry. Kept intact (the studio surface
    + ``test_authoring_trace_api.py`` still exercise it) but now layered on the
    same shared pipeline as the brief-driven build by synthesising a minimal
    :class:`_BuildBrief` (no level/budget/outcomes constraints, beginner default).
    The subject is resolved by exact slug here — a missing slug 404s
    (``authoring.subject_not_found``) the way the studio UI expects (it picks a
    real Subject), unlike the self-serve define entry which never 404s.
    """
    brief = brief.strip()
    if not brief:
        raise AppError("Brief must not be empty", code="authoring.brief_empty")
    subject = await courses_repo.get_subject_by_slug(db, subject_slug)
    if subject is None:
        raise NotFoundError(
            f"Subject {subject_slug!r} not found",
            code="authoring.subject_not_found",
        )
    bb = _BuildBrief(
        brief_id="",
        goal_text=brief,
        goal_summary=brief[:200],
        difficulty=Difficulty.beginner,
        level="beginner",
        time_budget_hours=None,
        target_modules=4,
        desired_outcomes=[],
        desired_subject_hint=subject_slug,
    )
    return await _run_pipeline(db, user=user, bb=bb, subject_id=subject.id, ctx=ctx)


async def _run_pipeline(
    db: AsyncSession,
    *,
    user: User,
    bb: _BuildBrief,
    subject_id: str,
    ctx: LLMContext = PLATFORM_CONTEXT,
    existing_course_id: str | None = None,
) -> OrchestratorResult:
    """Shared researcher→outliner→critic↺reviser→drafter→final-critic pipeline.

    Driven by a resolved :class:`_BuildBrief` + subject id. Used by both the
    brief-driven :func:`draft_course` (S3.6) and the legacy text path
    :func:`draft_course_from_text`. Commits its own course rows but not the outer
    transaction (caller's request-scoped commit).

    ``existing_course_id`` (S3.7 shell-first): when set,
    :func:`_persist_outline_shell` fills that pre-committed shell row in place
    (per-phase commit: outline UPDATE + skeleton in its own short txn, then the
    lesson loop on the request session) instead of inserting a new course.
    """
    user_id = user.id
    constraints = _constraints_block(bb)
    # The free-form prompt brief is the decrypted goal + the structured summary;
    # the goal text may enter prompts (FR-PRIV-01) but never a trace.
    prompt_brief = f"Learner's goal: {bb.goal_text}\nSummary: {bb.goal_summary}"

    draft_id = new_id()
    metered_user_id = user_id or SYSTEM_USER_ID
    step_index = 0

    # R-S10 cooperative-cancellation fence (ADR-0030 §D4): if the authoring user
    # was suspended/deleted before the build started, abort here before burning
    # any LLM tokens. Fenced again at the lesson-drafter and final-critic phase
    # boundaries so a mid-build flip aborts the phase (no partial course persists
    # past the next fence).
    if user_id:
        await account_service.assert_account_active(db, user_id)

    # ---------- Step 1. Researcher ----------
    started = time.perf_counter()
    # S2.7: thread the authoring user so the researcher's cross-catalog read
    # may surface the author's OWN private courses but never another user's.
    research_bundle: ResearchBundle = await run_researcher(
        db, brief=prompt_brief, requesting_user_id=user_id
    )
    research_duration_ms = int((time.perf_counter() - started) * 1000)
    await _record_trace(
        db,
        draft_id=draft_id,
        user_id=user_id,
        step=DRAFT_STEP_RESEARCHER,
        step_index=step_index,
        payload={
            # FR-PRIV-01: trace summaries use the non-sensitive goal_summary,
            # NEVER the decrypted raw goal text.
            "prompt_summary": bb.goal_summary[:240],
            "brief_id": bb.brief_id,
            "response_summary": (
                f"{len(research_bundle.web_snippets)} web snippet(s); "
                f"{len(research_bundle.catalog_neighbours)} catalog "
                f"neighbour(s); note={research_bundle.note!r}"
            ),
            "web_snippets": [s.model_dump() for s in research_bundle.web_snippets],
            "catalog_neighbours": [n.model_dump() for n in research_bundle.catalog_neighbours],
        },
        duration_ms=research_duration_ms,
        status=DRAFT_STATUS_OK,
    )
    step_index += 1

    # ---------- Step 2. Outliner (first pass) ----------
    outline_phase_calls = 0
    outline, outline_raw, outline_err = await _call_outliner(
        db,
        user_id=metered_user_id,
        brief=prompt_brief,
        constraints=constraints,
        research=research_bundle,
        ctx=ctx,
    )
    outline_phase_calls += 1
    if outline is None:
        await _record_trace(
            db,
            draft_id=draft_id,
            user_id=user_id,
            step=DRAFT_STEP_OUTLINER,
            step_index=step_index,
            payload={
                "prompt_summary": bb.goal_summary[:240],
                "response_summary": (outline_raw or "")[:240],
                "error": outline_err,
            },
            status=DRAFT_STATUS_ERROR,
        )
        raise AppError(
            "The AI failed to draft an outline — try again.",
            code="authoring.outliner_failed",
        )
    await _record_trace(
        db,
        draft_id=draft_id,
        user_id=user_id,
        step=DRAFT_STEP_OUTLINER,
        step_index=step_index,
        payload={
            "prompt_summary": bb.goal_summary[:240],
            "response_summary": _summarise_outline(outline),
            "outline": outline.model_dump(),
        },
        status=DRAFT_STATUS_OK,
    )
    step_index += 1

    # ---------- Steps 3-4. Critique → revise loop ----------
    revisions_used = 0
    final_critique: CritiqueResult | None = None
    while True:
        # Hard cap on LLM calls — degrade cleanly if the critic
        # never converges.
        if outline_phase_calls >= MAX_OUTLINE_PHASE_LLM_CALLS:
            log.warning(
                "authoring_outline_phase_cap_hit",
                draft_id=draft_id,
                outline_phase_calls=outline_phase_calls,
            )
            await _record_trace(
                db,
                draft_id=draft_id,
                user_id=user_id,
                step=DRAFT_STEP_CRITIC,
                step_index=step_index,
                payload={
                    "note": (
                        f"outline-phase LLM call cap reached "
                        f"({MAX_OUTLINE_PHASE_LLM_CALLS}); accepting "
                        "current outline."
                    ),
                    "revisions_used": revisions_used,
                },
                status=DRAFT_STATUS_OK,
            )
            step_index += 1
            break

        critique, critic_raw, critic_err = await _call_critic(
            db,
            user_id=metered_user_id,
            brief=prompt_brief,
            constraints=constraints,
            outline=outline,
            ctx=ctx,
        )
        outline_phase_calls += 1
        if critique is None:
            # Critic itself failed — log + accept the outline.
            await _record_trace(
                db,
                draft_id=draft_id,
                user_id=user_id,
                step=DRAFT_STEP_CRITIC,
                step_index=step_index,
                payload={
                    "prompt_summary": _summarise_outline(outline),
                    "response_summary": (critic_raw or "")[:240],
                    "error": critic_err,
                    "revision_number": revisions_used,
                },
                status=DRAFT_STATUS_ERROR,
            )
            step_index += 1
            break

        await _record_trace(
            db,
            draft_id=draft_id,
            user_id=user_id,
            step=DRAFT_STEP_CRITIC,
            step_index=step_index,
            payload={
                "prompt_summary": _summarise_outline(outline),
                "response_summary": critique.rationale[:240],
                "critic_scores": critique.scores.model_dump(),
                "weak_spots": critique.weak_spots,
                "revision_number": revisions_used,
            },
            status=DRAFT_STATUS_OK,
        )
        step_index += 1
        final_critique = critique

        # Accept on high score OR when the revision budget is gone.
        if critique.scores.mean >= ACCEPTANCE_MEAN_SCORE:
            break
        if revisions_used >= MAX_REVISIONS:
            break
        if outline_phase_calls >= MAX_OUTLINE_PHASE_LLM_CALLS:
            break

        # ---------- Reviser ----------
        revised, reviser_raw, reviser_err = await _call_reviser(
            db,
            user_id=metered_user_id,
            brief=prompt_brief,
            constraints=constraints,
            outline=outline,
            critique=critique,
            ctx=ctx,
        )
        outline_phase_calls += 1
        revisions_used += 1
        if revised is None:
            # Reviser failure: log + accept the current outline. We
            # don't retry the reviser a second time because each
            # round burns 2 LLM calls (reviser + next critic) and
            # the budget is precious.
            log.warning(
                "authoring_reviser_failed",
                draft_id=draft_id,
                revision_number=revisions_used,
                error=reviser_err,
            )
            await _record_trace(
                db,
                draft_id=draft_id,
                user_id=user_id,
                step=DRAFT_STEP_REVISER,
                step_index=step_index,
                payload={
                    "prompt_summary": _summarise_outline(outline),
                    "response_summary": (reviser_raw or "")[:240],
                    "error": reviser_err,
                    "revision_number": revisions_used,
                },
                status=DRAFT_STATUS_ERROR,
            )
            step_index += 1
            break

        await _record_trace(
            db,
            draft_id=draft_id,
            user_id=user_id,
            step=DRAFT_STEP_REVISER,
            step_index=step_index,
            payload={
                "prompt_summary": "; ".join(critique.weak_spots)[:240],
                "response_summary": _summarise_outline(revised),
                "outline": revised.model_dump(),
                "revision_number": revisions_used,
            },
            status=DRAFT_STATUS_OK,
        )
        step_index += 1
        outline = revised
        # Loop back to the critic with the revised outline.

    # ---------- Step 5. Persist course + modules + lessons ----------
    # Shell-first path (S3.7): fill the pre-committed shell with the outline UPDATE
    # in its OWN short txn (releasing the parent-row write lock) + a cancel-aware
    # refill, then insert the skeleton on the request session (Codex P1). The
    # legacy / direct-call path inserts a fresh course atomically.
    if existing_course_id is not None:
        course = await _persist_outline_shell(
            db,
            user=user,
            subject_id=subject_id,
            outline=outline,
            build_brief=bb,
            existing_course_id=existing_course_id,
        )
    else:
        course = await _persist_outline(
            db,
            user=user,
            subject_id=subject_id,
            outline=outline,
            build_brief=bb,
        )
    # Back-fill course_id on the trace rows we wrote before the
    # course existed.
    await _backfill_course_id(db, draft_id=draft_id, course_id=course.id)

    # R-S10 fence before the (expensive) per-lesson drafting phase: a user
    # suspended/deleted during the outline phase aborts here (account.access_
    # revoked) before the N lesson-body LLM calls fire.
    if user_id:
        await account_service.assert_account_active(db, user_id)

    # ---------- Step 6. Lesson-drafter (one per lesson) ----------
    # We iterate the freshly-persisted modules so we can populate
    # ``lesson.data`` in place (and record traces against real
    # lesson ids). The skeleton insert (``_persist_outline`` /
    # ``_persist_outline_shell``) already added every lesson with placeholder
    # data — we just overwrite. On the shell path these UPDATEs lock the
    # ``lessons`` rows only; the parent ``courses`` row carries no write lock here
    # (its outline UPDATE already committed in its own txn), so a mid-loop cancel
    # lands promptly and the per-lesson fence sees it within one lesson (P1#1).
    lesson_count = 0
    for module in sorted(course.modules, key=lambda m: m.order):
        for lesson in sorted(module.lessons, key=lambda lsn: lsn.order):
            # R-S10 cooperative-cancel fence (S3.8): abort the lesson-drafting
            # loop if the owner cancelled the build (course flipped to
            # build_failed by POST /me/courses/{id}/cancel-build) — before the
            # next lesson-body LLM call fires.
            await _assert_build_not_cancelled(db, course.id)
            lesson_started = time.perf_counter()
            data = await _draft_lesson_content(
                db,
                user_id=metered_user_id,
                course_title=outline.title,
                course_overview=outline.overview,
                lesson_title=lesson.title,
                lesson_type=lesson.type,
                ctx=ctx,
            )
            lesson.data = data
            await db.flush()
            lesson_count += 1
            await _record_trace(
                db,
                draft_id=draft_id,
                course_id=course.id,
                user_id=user_id,
                step=DRAFT_STEP_LESSON_DRAFTER,
                step_index=step_index,
                payload={
                    "prompt_summary": lesson.title[:240],
                    "response_summary": (f"{data.get('type', 'unknown')} lesson drafted"),
                    "lesson_id": lesson.id,
                    "lesson_type": str(lesson.type),
                },
                duration_ms=int((time.perf_counter() - lesson_started) * 1000),
                status=DRAFT_STATUS_OK,
            )
            step_index += 1

    # ---------- Step 7. Final-critic ----------
    final_critique = await _call_final_critic(
        db,
        user_id=metered_user_id,
        brief=prompt_brief,
        constraints=constraints,
        outline=outline,
        lesson_count=lesson_count,
        ctx=ctx,
    )
    await _record_trace(
        db,
        draft_id=draft_id,
        course_id=course.id,
        user_id=user_id,
        step=DRAFT_STEP_FINAL_CRITIC,
        step_index=step_index,
        payload={
            "prompt_summary": _summarise_outline(outline),
            "response_summary": final_critique.rationale[:240],
            "critic_scores": final_critique.scores.model_dump(),
            "weak_spots": final_critique.weak_spots,
        },
        status=DRAFT_STATUS_OK,
    )

    # ---------- Step 8. Stamp the honest completion marker (Codex P1) ----------
    # ``build_completed_at`` is the durable "this build finished" signal that
    # replaces the fragile ">=1 module" heuristic (build._is_successfully_built).
    # Stamped on the request session at the very end so it commits with the final
    # tree: a crash/cancel BEFORE this point leaves it NULL (re-buildable, never
    # replayed as success). This is the only parent-row write after the outline
    # phase — a short FOR-NO-KEY-UPDATE hold to the request commit, not across the
    # loop, so it doesn't reintroduce the P1#1 long lock.
    course.build_completed_at = datetime.now(UTC)
    await db.flush()

    log.info(
        "authoring_draft_course_done",
        draft_id=draft_id,
        course_id=course.id,
        revisions_used=revisions_used,
        outline_phase_calls=outline_phase_calls,
        lesson_count=lesson_count,
        final_mean=final_critique.scores.mean,
    )

    return OrchestratorResult(
        course_id=course.id,
        slug=course.slug,
        module_count=len(course.modules),
        lesson_count=lesson_count,
        final_score=final_critique.scores,
        final_rationale=final_critique.rationale,
        draft_id=draft_id,
        revisions_used=revisions_used,
    )


# ---------- LLM-call wrappers per step ----------


async def _call_outliner(
    db: AsyncSession,
    *,
    user_id: str,
    brief: str,
    constraints: str,
    research: ResearchBundle,
    ctx: LLMContext = PLATFORM_CONTEXT,
) -> tuple[ai_authoring.CourseOutline | None, str, str | None]:
    """First-pass outline call with the research bundle + DR-4 constraints."""
    user_msg = (
        f"BRIEF:\n{brief}\n\n"
        f"{constraints}\n\n"
        f"RESEARCH:\n{research.to_prompt_block()}\n\n"
        "Draft the outline now."
    )
    return await _chat_with_retry(
        db,
        user_id=user_id,
        system=_OUTLINER_WITH_RESEARCH_SYSTEM,
        user=user_msg,
        model=ai_authoring.CourseOutline,
        feature=FEATURE_OUTLINER,
        temperature=0.5,
        ctx=ctx,
    )


async def _call_critic(
    db: AsyncSession,
    *,
    user_id: str,
    brief: str,
    constraints: str,
    outline: ai_authoring.CourseOutline,
    ctx: LLMContext = PLATFORM_CONTEXT,
) -> tuple[CritiqueResult | None, str, str | None]:
    """Critic call against a candidate outline (scored against the DR-4 budget)."""
    user_msg = (
        f"BRIEF:\n{brief}\n\n"
        f"{constraints}\n\n"
        f"OUTLINE:\n{_render_outline_for_prompt(outline)}\n\n"
        "Emit the JSON critique now."
    )
    return await _chat_with_retry(
        db,
        user_id=user_id,
        system=_CRITIC_SYSTEM_PROMPT,
        user=user_msg,
        model=CritiqueResult,
        feature=FEATURE_CRITIC,
        temperature=0.2,
        ctx=ctx,
    )


async def _call_reviser(
    db: AsyncSession,
    *,
    user_id: str,
    brief: str,
    constraints: str,
    outline: ai_authoring.CourseOutline,
    critique: CritiqueResult,
    ctx: LLMContext = PLATFORM_CONTEXT,
) -> tuple[ai_authoring.CourseOutline | None, str, str | None]:
    """Revise a flagged outline against the critic's weak-spot list + constraints."""
    weak_block = (
        "\n".join(f"- {w}" for w in critique.weak_spots)
        or "- (no specific weak spots — improve the outline broadly)"
    )
    user_msg = (
        f"BRIEF:\n{brief}\n\n"
        f"{constraints}\n\n"
        f"PREVIOUS OUTLINE:\n{_render_outline_for_prompt(outline)}\n\n"
        f"CRITIC WEAK SPOTS:\n{weak_block}\n\n"
        "Produce the revised outline JSON now."
    )
    return await _chat_with_retry(
        db,
        user_id=user_id,
        system=_REVISER_SYSTEM_PROMPT,
        user=user_msg,
        model=ai_authoring.CourseOutline,
        feature=FEATURE_REVISER,
        temperature=0.4,
        ctx=ctx,
    )


async def _call_final_critic(
    db: AsyncSession,
    *,
    user_id: str,
    brief: str,
    constraints: str,
    outline: ai_authoring.CourseOutline,
    lesson_count: int,
    ctx: LLMContext = PLATFORM_CONTEXT,
) -> CritiqueResult:
    """Final critic. Always returns a :class:`CritiqueResult`.

    On LLM failure synthesises a neutral 3/5 score with an
    operator-visible note in the rationale — the learner still
    needs *some* score before they start studying their built course.
    """
    user_msg = (
        f"BRIEF:\n{brief}\n\n"
        f"{constraints}\n\n"
        f"OUTLINE:\n{_render_outline_for_prompt(outline)}\n\n"
        f"LESSON COUNT: {lesson_count}\n\n"
        "Emit the final critique JSON now."
    )
    critique, raw, err = await _chat_with_retry(
        db,
        user_id=user_id,
        system=_FINAL_CRITIC_SYSTEM_PROMPT,
        user=user_msg,
        model=CritiqueResult,
        feature=FEATURE_FINAL_CRITIC,
        temperature=0.2,
        ctx=ctx,
    )
    if critique is not None:
        return critique

    # Synthesise a neutral score so the API contract still holds.
    log.warning(
        "authoring_final_critic_failed",
        error=err,
        raw_head=(raw or "")[:200],
    )
    return CritiqueResult(
        scores=CriticScores(coverage=3, learning_arc=3, scope=3),
        weak_spots=[],
        rationale=(
            "(final critic unavailable — neutral score synthesised; "
            f"underlying error: {err or 'unknown'})"
        ),
    )


# ---------- Persistence ----------


async def _insert_skeleton_modules_lessons(
    db: AsyncSession,
    *,
    course_id: str,
    outline: ai_authoring.CourseOutline,
) -> None:
    """Insert the outline's modules + lessons (placeholder ``data``) under a course.

    Lessons get placeholder ``data`` (same shape as the E2 commit_outline path) so
    the schema's non-empty-content constraint is satisfied; the lesson-drafter loop
    overwrites ``data`` in place afterwards.

    Critically (Codex confirm-round P1#1): these child INSERTs take only ``FOR KEY
    SHARE`` on the parent ``courses`` row (the FK reference lock), which does NOT
    conflict with a concurrent cancel/failure-flip's ``FOR NO KEY UPDATE``. So when
    this runs on the request session AFTER the parent-row outline UPDATE has been
    committed in its own short transaction, the long lesson-drafting loop holds no
    parent-row write lock and a mid-build cancel lands promptly.
    """
    for mi, m in enumerate(outline.modules):
        module = Module(
            course_id=course_id,
            title=m.title,
            description="",
            order=mi,
        )
        db.add(module)
        await db.flush()
        for li, lesson_spec in enumerate(m.lessons):
            data = (
                _placeholder_quiz_data() if lesson_spec.type == "quiz" else _placeholder_text_data()
            )
            lesson = Lesson(
                module_id=module.id,
                title=lesson_spec.title,
                order=li,
                type=LessonType(lesson_spec.type),
                duration_seconds=None,
                is_preview=False,
                data=data,
            )
            db.add(lesson)
        await db.flush()


async def _persist_outline(
    db: AsyncSession,
    *,
    user: User,
    subject_id: str,
    outline: ai_authoring.CourseOutline,
    build_brief: _BuildBrief,
) -> Course:
    """Materialise the outline as a fresh PRIVATE draft course + modules + lessons.

    LEGACY / direct-call path (``existing_course_id is None``): the studio raw-brief
    flow + direct ``draft_course`` calls. Inserts one fresh ``courses`` row plus the
    module/lesson skeleton in the caller's (request) transaction — atomic single-txn
    is acceptable here because there is no shell and no cancel target (no
    cancellability to trade for). The shell-first build uses
    :func:`_persist_outline_shell` instead.

    DR-4 / S3.6 / FR-DEFINE-04/11: ``difficulty`` derives from the brief's level,
    ``learning_outcomes`` from ``desired_outcomes``, ``visibility=private``. Slug is
    minted via the same ``_unique_slug`` helper so a collision degrades to
    ``"<base>-2"`` without crashing.
    """
    slug = await _unique_slug(db, outline.title)
    course = Course(
        owner_id=user.id,
        subject_id=subject_id,
        title=outline.title,
        slug=slug,
        overview=outline.overview,
        learning_outcomes=list(build_brief.desired_outcomes),
        difficulty=build_brief.difficulty,
        status=CourseStatus.draft,
        visibility=Visibility.private,
    )
    db.add(course)
    await db.flush()

    await _insert_skeleton_modules_lessons(db, course_id=course.id, outline=outline)

    fresh = await courses_repo.get_course(db, course.id, with_modules=True)
    if fresh is None:
        raise AppError(
            "Drafted course vanished between insert and read.",
            code="authoring.persistence_failed",
        )
    return fresh


async def _persist_outline_shell(
    db: AsyncSession,
    *,
    user: User,
    subject_id: str,
    outline: ai_authoring.CourseOutline,
    build_brief: _BuildBrief,
    existing_course_id: str,
) -> Course:
    """Fill a pre-committed shell — outline phase in its OWN txn, then skeleton.

    S3.7 shell-first + Codex confirm-round P1 fix. Two phases:

    **Phase 1 — outline UPDATE in its OWN short session (closes P1#1 + P1#2).**
    Open a fresh session from :func:`get_sessionmaker`, re-read the shell
    ``FOR UPDATE``, and:

    * **Cancel-aware refill (P1#2).** If the shell is ALREADY ``build_failed`` (the
      owner cancelled, or a prior attempt's failure-flip landed) abort the build
      immediately via the cancel/abort path — raise ``AccessRevokedError`` with the
      ``define.build_cancelled`` code. The old code unconditionally reset the shell
      to ``draft``, erasing a cancel that arrived between shell-materialization and
      this point; the per-lesson fence then never observed it.
    * Otherwise update the parent row's outline fields (title/slug/overview/
      outcomes/difficulty/subject) + drop any stale modules from a prior partial
      attempt, then COMMIT this own session. The parent-row write lock releases at
      that commit — so the subsequent (long) lesson-drafting loop on the request
      session holds NO parent-row write lock, and a concurrent cancel/failure-flip
      lands promptly (P1#1). Per-phase commit trades whole-tree atomicity for
      cancellability + durable-partial (the shell-first contract); each committed
      phase leaves a state the fence/sweep/replay understand (``build_completed_at``
      stays NULL until the very end, so a crash here is re-buildable, never
      replayed as success).

    The module/lesson SKELETON (placeholder ``data``) is inserted + COMMITTED in
    this same own session, so a crash mid lesson-drafting leaves a DURABLE partial
    course (HAS modules) — yet ``build_completed_at`` stays NULL, so the replay
    distinguisher (:func:`build._is_successfully_built`) reports it un-built and
    re-buildable (the exact ">=1 module isn't enough" fix). The lesson-drafter loop
    then only OVERWRITES ``lesson.data`` on the request session — those updates
    lock the ``lessons`` rows, never taking a conflicting write lock on the parent
    ``courses`` row.

    **Phase 2 — re-read on the request session.** Re-fetch the (committed) course
    with relations on the caller's ``db`` and return it for the lesson-drafter loop.
    """
    from app.db.base import get_sessionmaker

    # ---- Phase 1: outline UPDATE + stale-module cleanup + skeleton, OWN txn ----
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as own_db:
        shell = (
            await own_db.execute(
                select(Course)
                .where(Course.id == existing_course_id, Course.deleted_at.is_(None))
                .with_for_update()
            )
        ).scalar_one_or_none()
        if shell is None:
            # Shell deleted/swept between materialization and now — fall back to a
            # fresh insert on the request session so the build still completes.
            return await _persist_outline(
                db,
                user=user,
                subject_id=subject_id,
                outline=outline,
                build_brief=build_brief,
            )
        # Cancel-aware refill (P1#2): a shell already terminal-failed (cancel or a
        # prior fail-flip) must NOT be reset to draft — abort the build instead.
        if shell.status == CourseStatus.build_failed:
            raise AccessRevokedError(
                "This build was cancelled.", code="define.build_cancelled"
            )
        # Drop stale modules from a prior partial attempt so the new outline is
        # clean (a re-run of a crashed draft shell). The module cascade removes
        # their lessons.
        stale = (
            (
                await own_db.execute(
                    select(Module).where(Module.course_id == existing_course_id)
                )
            )
            .scalars()
            .all()
        )
        for m in stale:
            await own_db.delete(m)
        await own_db.flush()
        shell.subject_id = subject_id
        shell.title = outline.title
        shell.slug = await _unique_slug(own_db, outline.title, exclude_id=existing_course_id)
        shell.overview = outline.overview
        shell.learning_outcomes = list(build_brief.desired_outcomes)
        shell.difficulty = build_brief.difficulty
        shell.status = CourseStatus.draft
        shell.visibility = Visibility.private
        # Skeleton modules/lessons in the SAME own txn → durable-partial: a crash
        # in the request-session lesson loop leaves committed modules but a NULL
        # build_completed_at (un-built, re-buildable). The parent-row write lock
        # is held only until THIS commit, never across the loop (P1#1).
        await _insert_skeleton_modules_lessons(
            own_db, course_id=existing_course_id, outline=outline
        )
        await own_db.commit()

    # ---- Phase 2: re-read the committed course on the REQUEST session ----
    # Drop any identity-mapped/stale copy of the shell (+ its modules) so the
    # request session re-reads the just-committed parent state + new tree.
    cached = await db.get(Course, existing_course_id)
    if cached is not None:
        await db.refresh(cached)
        db.expire(cached, ["modules"])
    fresh = await courses_repo.get_course(db, existing_course_id, with_modules=True)
    if fresh is None:
        raise AppError(
            "Drafted course vanished between insert and read.",
            code="authoring.persistence_failed",
        )
    return fresh


# ---------- Prompt rendering helpers ----------


def _render_outline_for_prompt(outline: ai_authoring.CourseOutline) -> str:
    """Compact text representation of an outline for the critic/reviser.

    JSON would also work but is noisier in the prompt; the indented
    plain-text form reads more like an editorial brief, which seems
    to help the critic stay on the meta-level instead of arguing
    with the JSON schema.
    """
    lines = [f"Title: {outline.title}", "", f"Overview: {outline.overview}", ""]
    for mi, m in enumerate(outline.modules, start=1):
        lines.append(f"Module {mi}: {m.title}")
        for li, lesson in enumerate(m.lessons, start=1):
            lines.append(f"  {mi}.{li} [{lesson.type}] {lesson.title}")
    return "\n".join(lines)


def _summarise_outline(outline: ai_authoring.CourseOutline) -> str:
    """One-line summary for trace ``response_summary`` fields."""
    return (
        f"{outline.title} — {len(outline.modules)} module(s), "
        f"{sum(len(m.lessons) for m in outline.modules)} lesson(s)"
    )


# ---------- Trace read helpers (used by the API surface) ----------


async def list_traces_for_course(db: AsyncSession, *, course_id: str) -> list[CourseDraftTrace]:
    """Return every trace row for the latest draft of ``course_id``.

    "Latest draft" = the rows with the most recent ``draft_id``
    that has any row pointing at this course. We fetch in two
    steps because the latest-draft set is small and the index is
    on ``(draft_id, step_index)`` — a join-style query would
    confuse the planner.
    """
    # Find the most recent draft_id tied to this course.
    latest_stmt = (
        select(CourseDraftTrace.draft_id)
        .where(CourseDraftTrace.course_id == course_id)
        .order_by(CourseDraftTrace.created_at.desc())
        .limit(1)
    )
    latest = (await db.execute(latest_stmt)).scalar_one_or_none()
    if latest is None:
        return []
    rows_stmt = (
        select(CourseDraftTrace)
        .where(CourseDraftTrace.draft_id == latest)
        .order_by(CourseDraftTrace.step_index.asc())
    )
    return list((await db.execute(rows_stmt)).scalars().all())


__all__ = [
    "ACCEPTANCE_MEAN_SCORE",
    "FEATURE_CRITIC",
    "FEATURE_FINAL_CRITIC",
    "FEATURE_LESSON_DRAFTER",
    "FEATURE_OUTLINER",
    "FEATURE_RESEARCHER",
    "FEATURE_REVISER",
    "FEATURE_ROOT",
    "MAX_OUTLINE_PHASE_LLM_CALLS",
    "MAX_REVISIONS",
    "CriticScores",
    "CritiqueResult",
    "OrchestratorResult",
    "draft_course",
    "draft_course_from_text",
    "list_traces_for_course",
]
