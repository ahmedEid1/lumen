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
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.core.ids import new_id
from app.core.logging import get_logger
from app.models.course import (
    Course,
    CourseStatus,
    Difficulty,
    Lesson,
    LessonType,
    Module,
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
outline. The instructor pasted a brief; a research sub-agent has \
gathered context for you. Use it to scope the outline.

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
- Generate 3-6 modules unless the brief explicitly asked for a \
different number.
- Each module has 3-5 lessons.
- Most lessons should be "text". Every module should end with one \
"quiz" lesson that checks the module's material.
- Only use "text" or "quiz" as the lesson type.
- Titles must be specific, not generic.
- Treat the WEB block as background only; the CATALOG block lists \
existing Lumen courses so you can avoid duplicating their angles.
"""


_CRITIC_SYSTEM_PROMPT = """\
You are a course-design critic. The instructor's brief and the \
proposed outline are provided. Rate the outline on three axes, \
each 0-5 inclusive:

  - "coverage"     — does the outline cover the brief's stated \
scope? Missing major topics drops this score.
  - "learning_arc" — do later modules genuinely build on earlier \
ones? A flat list of topics is a 2; a deliberate progression is \
a 5.
  - "scope"        — is the outline neither too broad (10 modules \
trying to teach a whole field) nor too narrow (3 lessons that \
under-deliver on the brief)?

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
You are a course-design reviser. The instructor's brief, the \
previous outline, and a critic's weak-spot notes are provided. \
Produce a revised outline that addresses the weak spots while \
keeping the parts that the critic didn't flag.

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
You are the final critic for an AI-drafted course. The instructor \
will see your score before they hit Publish. The brief, the full \
outline, and the per-lesson body lengths are provided.

Rate the course on the same three axes, each 0-5 inclusive:

  - "coverage"     — does the finished course deliver on the brief?
  - "learning_arc" — do the modules + lessons actually build on \
each other?
  - "scope"        — is the depth right for the brief's audience?

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
    brief: str,
    subject_slug: str,
    ctx: LLMContext = PLATFORM_CONTEXT,
) -> OrchestratorResult:
    """Run the full self-critique authoring pipeline.

    On success, persists one ``courses`` row + N ``modules`` + M
    ``lessons`` (all draft status) + K ``course_draft_traces`` rows.
    Returns an :class:`OrchestratorResult` the API surface returns
    to the instructor.

    On unrecoverable LLM failure, raises :class:`AppError`
    (``authoring.outliner_failed`` or ``authoring.subject_not_found``)
    which the API edge converts to 502 / 404 respectively.

    Important: this function commits its own course rows but does
    NOT commit the outer transaction — the caller's API handler is
    responsible for committing (via the DBSession dependency's
    request-scoped commit, same pattern as every other service
    method in the codebase).
    """
    brief = brief.strip()
    if not brief:
        raise AppError("Brief must not be empty", code="authoring.brief_empty")

    # Resolve subject up front — if it doesn't exist we want to
    # fail before burning any LLM tokens.
    subject = await courses_repo.get_subject_by_slug(db, subject_slug)
    if subject is None:
        raise NotFoundError(
            f"Subject {subject_slug!r} not found",
            code="authoring.subject_not_found",
        )

    draft_id = new_id()
    user_id = user.id
    metered_user_id = user_id or SYSTEM_USER_ID
    step_index = 0

    # ---------- Step 1. Researcher ----------
    started = time.perf_counter()
    research_bundle: ResearchBundle = await run_researcher(db, brief=brief)
    research_duration_ms = int((time.perf_counter() - started) * 1000)
    await _record_trace(
        db,
        draft_id=draft_id,
        user_id=user_id,
        step=DRAFT_STEP_RESEARCHER,
        step_index=step_index,
        payload={
            "prompt_summary": brief[:240],
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
        brief=brief,
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
                "prompt_summary": brief[:240],
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
            "prompt_summary": brief[:240],
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
            brief=brief,
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
            brief=brief,
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
    course = await _persist_outline(
        db,
        user=user,
        subject_id=subject.id,
        outline=outline,
    )
    # Back-fill course_id on the trace rows we wrote before the
    # course existed.
    await _backfill_course_id(db, draft_id=draft_id, course_id=course.id)

    # ---------- Step 6. Lesson-drafter (one per lesson) ----------
    # We iterate the freshly-persisted modules so we can populate
    # ``lesson.data`` in place (and record traces against real
    # lesson ids). The cascade in ``_persist_outline`` already
    # added every lesson with placeholder data — we just overwrite.
    lesson_count = 0
    for module in sorted(course.modules, key=lambda m: m.order):
        for lesson in sorted(module.lessons, key=lambda lsn: lsn.order):
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
        brief=brief,
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
    research: ResearchBundle,
    ctx: LLMContext = PLATFORM_CONTEXT,
) -> tuple[ai_authoring.CourseOutline | None, str, str | None]:
    """First-pass outline call with the research bundle in the prompt."""
    user_msg = (
        f"BRIEF:\n{brief}\n\nRESEARCH:\n{research.to_prompt_block()}\n\nDraft the outline now."
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
    outline: ai_authoring.CourseOutline,
    ctx: LLMContext = PLATFORM_CONTEXT,
) -> tuple[CritiqueResult | None, str, str | None]:
    """Critic call against a candidate outline."""
    user_msg = (
        f"BRIEF:\n{brief}\n\n"
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
    outline: ai_authoring.CourseOutline,
    critique: CritiqueResult,
    ctx: LLMContext = PLATFORM_CONTEXT,
) -> tuple[ai_authoring.CourseOutline | None, str, str | None]:
    """Revise a flagged outline against the critic's weak-spot list."""
    weak_block = (
        "\n".join(f"- {w}" for w in critique.weak_spots)
        or "- (no specific weak spots — improve the outline broadly)"
    )
    user_msg = (
        f"BRIEF:\n{brief}\n\n"
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
    outline: ai_authoring.CourseOutline,
    lesson_count: int,
    ctx: LLMContext = PLATFORM_CONTEXT,
) -> CritiqueResult:
    """Final critic. Always returns a :class:`CritiqueResult`.

    On LLM failure synthesises a neutral 3/5 score with an
    operator-visible note in the rationale — the instructor still
    needs *some* score to render on the publish-anyway button.
    """
    user_msg = (
        f"BRIEF:\n{brief}\n\n"
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


async def _persist_outline(
    db: AsyncSession,
    *,
    user: User,
    subject_id: str,
    outline: ai_authoring.CourseOutline,
) -> Course:
    """Materialise the outline as draft course + modules + lessons.

    Lessons are inserted with placeholder ``data`` (same shape as the
    E2 commit_outline path) so the schema's non-empty-content
    constraint is satisfied; the lesson-drafter step overwrites
    ``data`` in place after this returns.

    Course slug is minted via the same ``_unique_slug`` helper the
    courses service uses, so a slug collision on the draft title
    degrades to ``"<base>-2"`` etc. without crashing.
    """
    slug = await _unique_slug(db, outline.title)
    course = Course(
        owner_id=user.id,
        subject_id=subject_id,
        title=outline.title,
        slug=slug,
        overview=outline.overview,
        difficulty=Difficulty.beginner,
        status=CourseStatus.draft,
    )
    db.add(course)
    await db.flush()

    for mi, m in enumerate(outline.modules):
        module = Module(
            course_id=course.id,
            title=m.title,
            description="",
            order=mi,
        )
        db.add(module)
        await db.flush()
        for li, lesson_spec in enumerate(m.lessons):
            # Default placeholder; overwritten by the lesson-drafter
            # loop in the orchestrator.
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

    # Re-fetch with relationships so the orchestrator's lesson-drafter
    # loop can iterate ``course.modules`` + ``module.lessons``.
    fresh = await courses_repo.get_course(db, course.id, with_modules=True)
    if fresh is None:
        # Shouldn't happen — we just inserted the row — but the
        # type-checker doesn't know that.
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
    "list_traces_for_course",
]
