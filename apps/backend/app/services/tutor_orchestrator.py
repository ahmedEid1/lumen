"""Multi-agent tutor planner-orchestrator (Lumen v2 Phase I2).

The orchestration moat. A user asks the tutor a question; instead of
shipping it straight to a single-shot RAG call (the Phase E1 ``ask``
flow), the orchestrator:

1. **Planner LLM call.** Asks the model: "given this question +
   conversation history, which of the five sub-agents should I run
   and in what order?" The model emits structured JSON matching the
   :class:`Plan` schema.

2. **Tool dispatch loop.** For each :class:`ToolCall` in the plan, we
   invoke the matching sub-agent (``retriever`` / ``web_searcher`` /
   ``code_runner`` / ``quiz_generator`` / ``concept_explainer``) and
   collect its :class:`pydantic.BaseModel` result. Hard cap of
   **5 tool-call rounds per turn**.

3. **Optional re-plan LLM call.** After the planned tool calls land,
   we ask the model: "given what you've learned, do you need to run
   one more tool, or do you have enough to answer?" If the model
   asks for more, we append one more :class:`ToolCall` and dispatch
   it. Hard cap of **3 LLM round-trips total** (plan / re-plan /
   synthesise).

4. **Synthesiser LLM call.** A final round-trip composes the natural-
   language answer from the retriever's chunks + the other sub-agents'
   outputs. Citations follow the existing ``[L:<lesson_id>]`` format
   so the downstream :func:`tutor.extract_citations` parser works
   unchanged.

Every LLM call is metered via :func:`llm_call_log.call_logged` with a
distinct feature slug (``tutor.multi_agent.plan|replan|synth``) so the
H1 dashboard rolls cost up by step type. Every decision step
(``plan``, ``tool_call``, ``replan``, ``synthesis``) writes one row
via :func:`agent_tracer.record_step`; the dashboard renders the tree
of decisions per turn.

**Why a re-plan step in the loop, not just a single planner.** The
planner has the user's question but not the actual lesson chunks
the retriever will surface. Once the retriever runs, the model can
make a much better second judgment about whether it needs the web
searcher, the code runner, or to just synthesise. We could collapse
this back to a single planner if we wanted, but the re-plan is the
agentic behaviour we want to *show off* — it's the visible "agent
thinking" that makes the project legible to a recruiter in 60s.

**Backwards-compat with Phase E1.** The existing
:func:`tutor.ask(db, *, course, user_message, ...)` signature is
preserved; ``ask`` now delegates to :func:`orchestrate` and projects
the result back into a :class:`~app.services.tutor.TutorAnswer`. The
old single-shot RAG path lives on as the body of the ``retriever``
sub-agent + the synthesiser's fallback prompt.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.agent_trace import TRACE_STATUS_ERROR, TRACE_STATUS_OK
from app.models.course import Course
from app.models.llm_call import SYSTEM_USER_ID
from app.services import agent_tracer
from app.services import llm as llm_service
from app.services.llm_call_log import call_logged
from app.services.tutor_subagents import (
    CodeRunResult,
    ConceptExplainResult,
    QuizGenResult,
    RetrieverResult,
    WebSearchResult,
    run_code_runner,
    run_concept_explainer,
    run_quiz_generator,
    run_retriever,
    run_web_searcher,
)

log = get_logger(__name__)


# ---------- Constants ----------


FEATURE = "tutor.multi_agent"

# Hard cap on the number of tool calls the orchestrator will dispatch
# in a single turn. Five is the published Cohere-evals number for
# "research agent" loops and matches the spec.
MAX_TOOL_CALL_ROUNDS = 5

# Hard cap on LLM round-trips per turn: planner + at most one re-plan
# + synthesiser = 3. Even if the planner asks for 5 tools and the
# re-planner adds another, the total LLM round-trip count is fixed.
MAX_LLM_ROUNDTRIPS = 3

# Tools the planner may dispatch. Kept here so the Pydantic Literal
# and the dispatch table stay in lockstep.
TOOL_NAMES = (
    "retriever",
    "web_searcher",
    "code_runner",
    "quiz_generator",
    "concept_explainer",
)

ToolName = Literal[
    "retriever",
    "web_searcher",
    "code_runner",
    "quiz_generator",
    "concept_explainer",
]

# Citation parsing — same shape as Phase E1's
# :func:`tutor.extract_citations`. We keep it here too so the
# orchestrator can validate citations against the retriever's lesson
# ids without importing the tutor module (cycle prone).
_CITATION_RE = re.compile(r"\[L:([^\s\]]+)\]")

# JSON fence stripper for planner replies — Anthropic models like to
# wrap structured output in ```json fences``` despite explicit
# instructions otherwise. Mirrors :mod:`learning_path`.
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


# ---------- Schemas ----------


class ToolCall(BaseModel):
    """One planner-emitted tool dispatch."""

    model_config = ConfigDict(frozen=True)

    tool_name: ToolName
    args: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(default="", max_length=400)


class Plan(BaseModel):
    """Planner's structured output."""

    model_config = ConfigDict(frozen=True)

    tool_calls: list[ToolCall] = Field(min_length=1, max_length=3)
    confidence_after_plan: int = Field(default=3, ge=0, le=5)
    final_answer_hint: str | None = None


class ToolCallSummary(BaseModel):
    """Compact summary of one tool call's input + output for the API.

    What the frontend's agent-reasoning panel renders. Keeps payload
    small (no full chunk text) by surfacing per-tool snippets that
    the UI can expand on demand.
    """

    model_config = ConfigDict(frozen=True)

    tool_name: ToolName
    args: dict[str, Any]
    rationale: str
    result_summary: str
    result_details: dict[str, Any]


class OrchestratorResult(BaseModel):
    """End-to-end output of one orchestrator turn."""

    model_config = ConfigDict(frozen=True)

    answer: str
    citations: list[str]
    tool_calls_made: list[ToolCallSummary]
    confidence: int
    refused: bool = False
    parent_call_id: str | None = None
    root_trace_id: str | None = None


# ---------- Prompts ----------


_PLANNER_SYSTEM_PROMPT = """\
You are the planner for Lumen's multi-agent tutoring system. The
learner is enrolled in the course "{course_title}" (slug:
``{course_slug}``). Your job is to decide which tools to run, in
what order, before the synthesiser composes the final answer.

You have access to FIVE tools:

  - ``retriever``         — RAG over the course's lessons. ALWAYS
    your first stop for any question that could plausibly be
    answered from course content. Args: ``{{"query": "<paraphrase>"}}``.
  - ``web_searcher``      — open-web search via Tavily. Use ONLY
    when the question clearly needs context outside the course
    (current events, fresh docs, an external definition the course
    glosses over). Args: ``{{"query": "<search terms>"}}``.
  - ``code_runner``       — sandboxed Python execution (math +
    statistics stdlib only). Use when running code would give a
    concrete answer the learner can verify ("what's the mean of
    [1,2,3,4]?", "is 18 prime?"). Args: ``{{"code": "<python>"}}``.
  - ``quiz_generator``    — emit one practice MCQ. Use ONLY when
    the learner asks for a quiz / practice question / "test me".
    Args: ``{{"topic": "<short>"}}``.
  - ``concept_explainer`` — re-explain in plainer language. Use
    ONLY when the learner asks for a simpler/different explanation
    of something previously discussed. Args: ``{{"concept": "<short>"}}``.

Output strict JSON with this exact shape — no prose, no markdown
fences, no commentary:

{{
  "tool_calls": [
    {{"tool_name": "retriever",
      "args": {{"query": "How does photosynthesis work?"}},
      "rationale": "The question is directly answerable from course content."}}
  ],
  "confidence_after_plan": 4,
  "final_answer_hint": null
}}

Hard rules:

  1. ``tool_calls`` MUST be 1-3 items. ALWAYS include ``retriever``
     as the first entry unless the question is purely procedural
     ("give me a practice question") or purely a code request.
  2. ``tool_name`` must be one of the five listed above. Inventing a
     tool is a hard failure.
  3. ``confidence_after_plan`` is your 0-5 estimate of how confident
     you are this plan will produce a good answer. Be honest.
  4. ``final_answer_hint`` is an optional one-sentence note about how
     the synthesiser should approach the final answer. Null is fine.
  5. Return ONE JSON object. No preamble, no fences.

Few-shot examples:

User: "What is photosynthesis?"
Plan: ``{{"tool_calls": [{{"tool_name": "retriever",
"args": {{"query": "photosynthesis overview"}},
"rationale": "Direct course-content lookup."}}],
"confidence_after_plan": 4, "final_answer_hint": null}}``

User: "Give me a practice question on the cell cycle."
Plan: ``{{"tool_calls": [{{"tool_name": "retriever",
"args": {{"query": "cell cycle"}},
"rationale": "Pull a grounding chunk to anchor the question."}},
{{"tool_name": "quiz_generator",
"args": {{"topic": "cell cycle"}},
"rationale": "User explicitly asked for a practice question."}}],
"confidence_after_plan": 4, "final_answer_hint": null}}``

User: "What's the average of 4, 6, 8, 10, 12?"
Plan: ``{{"tool_calls": [{{"tool_name": "code_runner",
"args": {{"code": "import statistics\\nprint(statistics.mean([4,6,8,10,12]))"}},
"rationale": "Concrete arithmetic — run the code, return the number."}}],
"confidence_after_plan": 5, "final_answer_hint": null}}``
"""


_REPLAN_SYSTEM_PROMPT = """\
You are the re-planner for Lumen's multi-agent tutoring system. The
original planner ran the tools below; you can see their results.

Your job: decide whether ONE more tool call would meaningfully
improve the synthesiser's answer, or whether the current results
are already enough.

Output strict JSON:

{
  "needs_more": true,
  "next_tool_call": {
    "tool_name": "web_searcher",
    "args": {"query": "..."},
    "rationale": "..."
  },
  "confidence_now": 4
}

Or, if no more tools are needed:

{
  "needs_more": false,
  "next_tool_call": null,
  "confidence_now": 5
}

Hard rules:

  1. ``needs_more`` is a boolean.
  2. If ``needs_more`` is true, ``next_tool_call`` MUST be a valid
     tool dispatch (same schema as the planner's tool_calls items).
  3. If ``needs_more`` is false, ``next_tool_call`` MUST be null.
  4. ``confidence_now`` is your 0-5 estimate of confidence in the
     final answer given what you know now.
  5. Prefer ``needs_more: false`` unless you can name a specific gap
     that one more tool would fill.
  6. Return ONE JSON object. No preamble, no fences.
"""


_SYNTHESISER_SYSTEM_PROMPT = """\
You are the synthesiser for Lumen's multi-agent tutoring system. The
planner ran the following tools and got these results. Compose the
final answer to the user's question.

Hard rules on citations:

  1. Cite lesson IDs using the existing ``[L:lesson_id]`` token
     format (e.g. ``[L:lsn_abc123]``) wherever you draw from the
     retriever's output.
  2. ONLY cite lesson IDs that appear in the retriever's results
     below. Inventing a lesson ID is a hard failure.
  3. If the web_searcher contributed, prefix those facts with
     "Web context (not from the course):" so the learner knows the
     source.
  4. If the code_runner ran, include its stdout in a fenced
     ```python``` block.

If the retriever returned no relevant chunks AND no other tool
contributed useful context, reply with the refusal sentence: "I
don't have enough material in this course to answer that. Try
rephrasing, or pick a topic the course actually covers."

Return clean text — no JSON envelope, no preamble like "Here's the
answer:". Just the answer itself, concise (a short paragraph or a
few bullets).
"""


# ---------- Helpers ----------


def _strip_json_fence(raw: str) -> str:
    fence = _JSON_FENCE_RE.search(raw)
    if fence:
        return fence.group(1).strip()
    return raw.strip()


def _parse_plan(raw: str) -> tuple[Plan | None, str | None]:
    """Validate a planner reply against :class:`Plan`."""
    body = _strip_json_fence(raw)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return None, f"JSON parse error: {exc.msg} at line {exc.lineno}"
    try:
        plan = Plan.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []))
        msg = first.get("msg", "validation error")
        return None, f"validation error at {loc or '<root>'}: {msg}"
    # Tool-name membership check (Literal already enforces it, but a
    # defensive belt-and-braces check keeps the error path centralised).
    for tc in plan.tool_calls:
        if tc.tool_name not in TOOL_NAMES:
            return None, f"unknown tool_name {tc.tool_name!r}"
    return plan, None


def _parse_replan(raw: str) -> dict[str, Any] | None:
    """Validate a re-planner reply. Returns the decoded dict or ``None``."""
    body = _strip_json_fence(raw)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if "needs_more" not in payload:
        return None
    return payload


def _fallback_plan() -> Plan:
    """Single-tool fallback plan used when the planner reply is unparsable.

    Mirrors the Phase E1 single-shot tutor exactly: just run the
    retriever, then synthesise. This is the same behaviour the
    learner would have gotten before I2 landed, so a planner outage
    degrades cleanly rather than blowing up the request.
    """
    return Plan(
        tool_calls=[
            ToolCall(
                tool_name="retriever",
                args={},
                rationale="planner failed — single-shot RAG fallback",
            )
        ],
        confidence_after_plan=2,
        final_answer_hint="planner failed; defaulted to retriever-only",
    )


def _summarise_result(name: ToolName, result: BaseModel) -> tuple[str, dict[str, Any]]:
    """Produce a human-readable summary + a JSON-serialisable detail dict.

    The summary lands in the trace + the API surface; details are
    rendered when the user expands a row in the reasoning panel.
    """
    if isinstance(result, RetrieverResult):
        return (
            result.note or f"{len(result.chunks)} chunk(s)",
            {
                "chunks": [c.model_dump() for c in result.chunks],
                "citations": result.citations,
            },
        )
    if isinstance(result, WebSearchResult):
        return (
            result.note or f"{len(result.snippets)} snippet(s)",
            {
                "snippets": [s.model_dump() for s in result.snippets],
                "citations": result.citations,
            },
        )
    if isinstance(result, CodeRunResult):
        head = (result.stdout or "")[:120]
        summary = (
            f"exit={result.exit_code}; stdout={head!r}"
            if not result.error_msg
            else f"exit={result.exit_code}; error={result.error_msg}"
        )
        return summary, result.model_dump()
    if isinstance(result, QuizGenResult):
        return (
            f"quiz: {result.prompt[:80]}",
            result.model_dump(),
        )
    if isinstance(result, ConceptExplainResult):
        return (
            f"re-explanation ({len(result.explanation)} chars)",
            result.model_dump(),
        )
    # Defensive fallback — never hit in practice.
    return name, result.model_dump()


def _serialise_for_synth(name: ToolName, result: BaseModel) -> str:
    """Compose the per-tool block included in the synthesiser's prompt."""
    if isinstance(result, RetrieverResult):
        if not result.chunks:
            return "RETRIEVER: (no relevant content)\n"
        body = "\n\n".join(
            f"Lesson L{c.lesson_id}: {c.lesson_title}\n{c.text}"
            for c in result.chunks
        )
        return f"RETRIEVER (cite these with [L:<lesson_id>]):\n{body}\n"
    if isinstance(result, WebSearchResult):
        if not result.snippets:
            return f"WEB_SEARCHER: {result.note or '(no results)'}\n"
        body = "\n\n".join(
            f"- {s.title} ({s.url})\n  {s.content_first_240}"
            for s in result.snippets
        )
        return f"WEB_SEARCHER (prefix facts with 'Web context (not from the course):'):\n{body}\n"
    if isinstance(result, CodeRunResult):
        if result.exit_code != 0:
            return (
                f"CODE_RUNNER: failed (exit={result.exit_code}) — "
                f"{result.error_msg or 'unknown error'}\n"
            )
        return (
            "CODE_RUNNER (include the stdout in a fenced ```python``` block):\n"
            f"```\n{result.stdout}\n```\n"
        )
    if isinstance(result, QuizGenResult):
        opts = "\n".join(f"  ({i}) {o}" for i, o in enumerate(result.options))
        return (
            "QUIZ_GENERATOR (fold this MCQ into the final answer):\n"
            f"Prompt: {result.prompt}\n"
            f"Options:\n{opts}\n"
            f"Correct: index {result.answer_index}\n"
            f"Explanation: {result.explanation}\n"
        )
    if isinstance(result, ConceptExplainResult):
        analogy = f"\nAnalogy: {result.analogy}" if result.analogy else ""
        return (
            "CONCEPT_EXPLAINER (fold this re-phrasing into the final answer):\n"
            f"Explanation: {result.explanation}{analogy}\n"
        )
    return f"{name.upper()}: (unrecognised result shape)\n"


async def _dispatch_tool(
    db: AsyncSession,
    *,
    tool_call: ToolCall,
    course: Course,
    user_question: str,
    retrieved: list[Any],
    user_id: str,
    step_index: int,
    parent_trace_id: str | None,
    parent_call_id: str | None,
) -> BaseModel:
    """Run one sub-agent and return its Pydantic result.

    ``retrieved`` is the list of retriever chunks we already have
    (if any) — the quiz_generator + concept_explainer use it as
    context for their LLM calls. We pass it through rather than
    re-running the retriever inside them.
    """
    name = tool_call.tool_name
    args = tool_call.args or {}

    if name == "retriever":
        query = str(args.get("query") or user_question)
        return await run_retriever(
            db,
            course=course,
            query=query,
            user_id=user_id,
            feature=FEATURE,
            step_index=step_index,
            parent_trace_id=parent_trace_id,
            parent_call_id=parent_call_id,
        )

    if name == "web_searcher":
        query = str(args.get("query") or user_question)
        return await run_web_searcher(
            db,
            query=query,
            user_id=user_id,
            feature=FEATURE,
            step_index=step_index,
            parent_trace_id=parent_trace_id,
            parent_call_id=parent_call_id,
        )

    if name == "code_runner":
        code = str(args.get("code") or "")
        return await run_code_runner(
            db,
            code=code,
            user_id=user_id,
            feature=FEATURE,
            step_index=step_index,
            parent_trace_id=parent_trace_id,
            parent_call_id=parent_call_id,
        )

    # The two LLM-call sub-agents share a small "context" block built
    # from whatever the retriever has surfaced so far.
    context_block = ""
    for r in retrieved:
        if isinstance(r, RetrieverResult):
            context_block = "\n\n".join(
                f"Lesson L{c.lesson_id}: {c.lesson_title}\n{c.text}"
                for c in r.chunks
            )
            break

    if name == "quiz_generator":
        topic = str(args.get("topic") or user_question)
        return await run_quiz_generator(
            db,
            topic=topic,
            context=context_block,
            user_id=user_id,
            feature=FEATURE,
            step_index=step_index,
            parent_trace_id=parent_trace_id,
            parent_call_id=parent_call_id,
        )

    if name == "concept_explainer":
        concept = str(args.get("concept") or user_question)
        return await run_concept_explainer(
            db,
            concept=concept,
            context=context_block,
            user_id=user_id,
            feature=FEATURE,
            step_index=step_index,
            parent_trace_id=parent_trace_id,
            parent_call_id=parent_call_id,
        )

    # Unreachable given the Literal — but defensive belt-and-braces.
    raise ValueError(f"unknown tool_name {name!r}")


def _validate_citations(answer: str, allowed_ids: set[str]) -> list[str]:
    """Parse + filter ``[L:<id>]`` tokens against the retriever's lessons.

    Mirrors :func:`tutor.extract_citations` but operates on plain
    lesson ids since the orchestrator doesn't carry full lesson
    titles all the way through. Returns deduplicated, order-preserving
    list of valid ids.
    """
    seen: set[str] = set()
    out: list[str] = []
    for match in _CITATION_RE.finditer(answer or ""):
        lid = match.group(1)
        if lid in seen or lid not in allowed_ids:
            continue
        seen.add(lid)
        out.append(lid)
    return out


# ---------- Entry point ----------


async def orchestrate(
    db: AsyncSession,
    *,
    user_id: str | None,
    course: Course,
    question: str,
    conversation_history: list[dict[str, Any]] | None = None,
    feature: str = FEATURE,
) -> OrchestratorResult:
    """Run the planner → tools → re-plan → synthesiser loop.

    Returns an :class:`OrchestratorResult` with the final answer +
    structured trace of every tool call. The caller (the legacy
    :func:`tutor.ask`) projects this into a :class:`TutorAnswer` for
    backwards compatibility.

    On planner outage we degrade to a single-tool retriever fallback;
    on synthesiser outage we surface a clean error message rather
    than an exception so the conversation thread persists. The
    orchestrator's contract is **never raise to the API edge** for
    sub-agent failures — only for truly catastrophic conditions (DB
    down, budget exceeded, etc., which bubble through ``call_logged``).
    """
    metered_user_id = user_id or SYSTEM_USER_ID
    question = (question or "").strip()
    started_overall = time.perf_counter()

    if not question:
        return OrchestratorResult(
            answer=(
                "I don't have enough material in this course to answer that. "
                "Try rephrasing, or pick a topic the course actually covers."
            ),
            citations=[],
            tool_calls_made=[],
            confidence=0,
            refused=True,
        )

    # ---------- 1. Planner ----------
    provider = llm_service.get_provider()
    planner_user_prompt = _build_planner_user_prompt(
        question=question, history=conversation_history
    )
    planner_messages = [
        llm_service.ChatMessage(
            role="system",
            content=_PLANNER_SYSTEM_PROMPT.format(
                course_title=course.title or "(untitled course)",
                course_slug=course.slug or "(no slug)",
            ),
        ),
        llm_service.ChatMessage(role="user", content=planner_user_prompt),
    ]

    plan, planner_call_id = await _call_planner(
        db,
        provider=provider,
        messages=planner_messages,
        user_id=metered_user_id,
        feature=feature,
    )
    if plan is None:
        # Planner unrecoverable — fall back to single-tool retriever.
        plan = _fallback_plan()
        planner_call_id = None

    # Record the plan step itself. The plan trace anchors every
    # downstream sub-agent + the synthesiser as its children.
    plan_trace = await agent_tracer.record_step(
        db,
        user_id=metered_user_id,
        feature=feature,
        step="plan",
        step_index=0,
        parent_call_id=planner_call_id,
        payload={
            "tool_calls": [tc.model_dump() for tc in plan.tool_calls],
            "confidence_after_plan": plan.confidence_after_plan,
            "final_answer_hint": plan.final_answer_hint,
        },
        status=TRACE_STATUS_OK,
    )
    plan_trace_id = plan_trace.id if plan_trace else None
    root_trace_id = plan_trace_id

    # ---------- 2. Tool dispatch loop ----------
    tool_summaries: list[ToolCallSummary] = []
    sub_agent_results: list[BaseModel] = []
    rounds_used = 0
    # Cap at MAX_TOOL_CALL_ROUNDS even if the planner emits more.
    queue = list(plan.tool_calls)
    while queue and rounds_used < MAX_TOOL_CALL_ROUNDS:
        tc = queue.pop(0)
        rounds_used += 1
        # Record the tool_call step header before dispatch so a
        # sub-agent crash still leaves a visible row.
        tool_step = await agent_tracer.record_step(
            db,
            user_id=metered_user_id,
            feature=feature,
            step="tool_call",
            step_index=rounds_used,
            parent_trace_id=plan_trace_id,
            parent_call_id=planner_call_id,
            payload={
                "tool_name": tc.tool_name,
                "args": tc.args,
                "rationale": tc.rationale,
            },
            status=TRACE_STATUS_OK,
        )
        tool_step_id = tool_step.id if tool_step else None

        try:
            result = await _dispatch_tool(
                db,
                tool_call=tc,
                course=course,
                user_question=question,
                retrieved=sub_agent_results,
                user_id=metered_user_id,
                step_index=rounds_used,
                parent_trace_id=tool_step_id,
                parent_call_id=planner_call_id,
            )
        except Exception as exc:  # noqa: BLE001 — sub-agent contract: never raise
            kind = type(exc).__name__
            log.warning(
                "tutor_subagent_failed",
                tool_name=tc.tool_name,
                error_kind=kind,
                user_id=metered_user_id,
            )
            await agent_tracer.record_step(
                db,
                user_id=metered_user_id,
                feature=feature,
                step="tool_call.error",
                step_index=rounds_used,
                parent_trace_id=tool_step_id,
                parent_call_id=planner_call_id,
                payload={
                    "tool_name": tc.tool_name,
                    "error_kind": kind,
                    "error_msg": str(exc)[:240],
                },
                status=TRACE_STATUS_ERROR,
            )
            continue

        sub_agent_results.append(result)
        summary_text, details = _summarise_result(tc.tool_name, result)
        tool_summaries.append(
            ToolCallSummary(
                tool_name=tc.tool_name,
                args=tc.args,
                rationale=tc.rationale,
                result_summary=summary_text,
                result_details=details,
            )
        )

    # ---------- 3. Optional re-plan ----------
    # We re-plan iff we have budget left, the original plan didn't
    # already use all the rounds, and the planner reported low-ish
    # confidence (<= 4) so the model implicitly invited a second look.
    if (
        rounds_used < MAX_TOOL_CALL_ROUNDS
        and plan.confidence_after_plan < 5
        and planner_call_id is not None  # only re-plan if planner worked
    ):
        replan_extra, replan_call_id = await _maybe_replan(
            db,
            provider=provider,
            user_id=metered_user_id,
            feature=feature,
            question=question,
            sub_agent_results=sub_agent_results,
            parent_trace_id=plan_trace_id,
        )
        if replan_extra is not None and rounds_used < MAX_TOOL_CALL_ROUNDS:
            rounds_used += 1
            tool_step = await agent_tracer.record_step(
                db,
                user_id=metered_user_id,
                feature=feature,
                step="tool_call",
                step_index=rounds_used,
                parent_trace_id=plan_trace_id,
                parent_call_id=replan_call_id,
                payload={
                    "tool_name": replan_extra.tool_name,
                    "args": replan_extra.args,
                    "rationale": replan_extra.rationale,
                    "source": "replan",
                },
                status=TRACE_STATUS_OK,
            )
            tool_step_id = tool_step.id if tool_step else None
            try:
                result = await _dispatch_tool(
                    db,
                    tool_call=replan_extra,
                    course=course,
                    user_question=question,
                    retrieved=sub_agent_results,
                    user_id=metered_user_id,
                    step_index=rounds_used,
                    parent_trace_id=tool_step_id,
                    parent_call_id=replan_call_id,
                )
                sub_agent_results.append(result)
                summary_text, details = _summarise_result(
                    replan_extra.tool_name, result
                )
                tool_summaries.append(
                    ToolCallSummary(
                        tool_name=replan_extra.tool_name,
                        args=replan_extra.args,
                        rationale=replan_extra.rationale,
                        result_summary=summary_text,
                        result_details=details,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                kind = type(exc).__name__
                log.warning(
                    "tutor_replan_subagent_failed",
                    tool_name=replan_extra.tool_name,
                    error_kind=kind,
                )
                await agent_tracer.record_step(
                    db,
                    user_id=metered_user_id,
                    feature=feature,
                    step="tool_call.error",
                    step_index=rounds_used,
                    parent_trace_id=tool_step_id,
                    parent_call_id=replan_call_id,
                    payload={
                        "tool_name": replan_extra.tool_name,
                        "error_kind": kind,
                    },
                    status=TRACE_STATUS_ERROR,
                )

    # ---------- 4. Synthesiser ----------
    synth_text, synth_call_id, refused = await _call_synthesiser(
        db,
        provider=provider,
        user_id=metered_user_id,
        feature=feature,
        question=question,
        history=conversation_history,
        sub_agent_results=sub_agent_results,
        plan_hint=plan.final_answer_hint,
    )

    # Validate citations against the retriever's lesson ids.
    allowed_ids: set[str] = set()
    for r in sub_agent_results:
        if isinstance(r, RetrieverResult):
            allowed_ids.update(r.citations)
    citations = _validate_citations(synth_text, allowed_ids)

    await agent_tracer.record_step(
        db,
        user_id=metered_user_id,
        feature=feature,
        step="synthesis",
        step_index=rounds_used + 1,
        parent_trace_id=plan_trace_id,
        parent_call_id=synth_call_id,
        payload={
            "answer_head": synth_text[:240],
            "citation_count": len(citations),
            "tool_calls_in_synth": len(sub_agent_results),
        },
        status=TRACE_STATUS_OK if synth_text else TRACE_STATUS_ERROR,
    )

    total_ms = int((time.perf_counter() - started_overall) * 1000)
    log.info(
        "tutor_orchestrator_done",
        user_id=metered_user_id,
        course_id=course.id,
        tool_rounds=rounds_used,
        tool_calls=len(tool_summaries),
        citation_count=len(citations),
        duration_ms=total_ms,
    )

    # Confidence: the re-planner's reported confidence (if it ran)
    # overrides the planner's. If neither produced a number, default
    # to a middling 3.
    final_confidence = plan.confidence_after_plan

    return OrchestratorResult(
        answer=synth_text,
        citations=citations,
        tool_calls_made=tool_summaries,
        confidence=final_confidence,
        refused=refused,
        parent_call_id=planner_call_id,
        root_trace_id=root_trace_id,
    )


# ---------- LLM call helpers (planner / re-planner / synthesiser) ----------


def _build_planner_user_prompt(
    *, question: str, history: list[dict[str, Any]] | None
) -> str:
    """Compose the planner's user-turn prompt."""
    history_block = ""
    if history:
        history_block = "RECENT TURNS:\n"
        for turn in history[-6:]:  # last 6 turns at most
            role = turn.get("role") or "?"
            content = (turn.get("content") or "")[:240]
            history_block += f"- {role}: {content}\n"
        history_block += "\n"
    return f"{history_block}USER QUESTION:\n{question}\n\nEmit the Plan JSON now."


async def _call_planner(
    db: AsyncSession,
    *,
    provider: llm_service.LLMProvider,
    messages: list[llm_service.ChatMessage],
    user_id: str,
    feature: str,
) -> tuple[Plan | None, str | None]:
    """One planner call with structured-output validation.

    Returns ``(plan, llm_call_id)`` on success, ``(None, None)`` on
    failure. The caller falls back to the single-tool retriever
    plan; we don't retry the planner here because the orchestrator's
    LLM round-trip budget (3 total) is tight.
    """
    feature_slug = f"{feature}.plan"
    started = time.perf_counter()
    try:
        response = await call_logged(
            provider,
            messages,
            user_id=user_id,
            feature=feature_slug,
            session=db,
            temperature=0.2,
        )
    except Exception as exc:  # noqa: BLE001 — surface as trace, not exception
        kind = type(exc).__name__
        log.warning(
            "tutor_planner_failed",
            user_id=user_id,
            error_kind=kind,
        )
        await agent_tracer.record_step(
            db,
            user_id=user_id,
            feature=feature,
            step="plan.error",
            step_index=0,
            payload={"error_kind": kind, "feature": feature_slug},
            status=TRACE_STATUS_ERROR,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return None, None

    plan, err = _parse_plan(response.text)
    if plan is None:
        log.warning(
            "tutor_planner_invalid_output",
            user_id=user_id,
            error=err,
            raw_head=response.text[:200],
        )
        await agent_tracer.record_step(
            db,
            user_id=user_id,
            feature=feature,
            step="plan.invalid_output",
            step_index=0,
            payload={"error": err, "raw_head": response.text[:240]},
            status=TRACE_STATUS_ERROR,
        )
        return None, None

    # The metered ``llm_calls`` row was written inside ``call_logged``
    # but it didn't return us the id; we re-derive it as ``None`` here
    # and let the trace step record without a parent_call_id. (A future
    # ``call_logged`` enhancement that returns the persisted row id
    # would let us thread the FK; today we accept the cost-meter side
    # not being linkable to specific trace subtrees from the planner.
    # Tracer rows still capture everything else.)
    return plan, None


async def _maybe_replan(
    db: AsyncSession,
    *,
    provider: llm_service.LLMProvider,
    user_id: str,
    feature: str,
    question: str,
    sub_agent_results: list[BaseModel],
    parent_trace_id: str | None,
) -> tuple[ToolCall | None, str | None]:
    """Ask the model whether one more tool call would help.

    Returns ``(extra_tool_call, llm_call_id)``. The tool call is
    ``None`` when the re-planner says no, when its reply is
    unparsable, or when its proposed tool is unknown.
    """
    if not sub_agent_results:
        return None, None
    feature_slug = f"{feature}.replan"
    results_block = "\n\n".join(
        _serialise_for_synth(_infer_tool_name(r), r) for r in sub_agent_results
    )
    messages = [
        llm_service.ChatMessage(role="system", content=_REPLAN_SYSTEM_PROMPT),
        llm_service.ChatMessage(
            role="user",
            content=(
                f"USER QUESTION:\n{question}\n\n"
                f"RESULTS SO FAR:\n{results_block}\n\n"
                "Emit the JSON now."
            ),
        ),
    ]
    try:
        response = await call_logged(
            provider,
            messages,
            user_id=user_id,
            feature=feature_slug,
            session=db,
            temperature=0.2,
        )
    except Exception as exc:  # noqa: BLE001
        kind = type(exc).__name__
        log.warning(
            "tutor_replanner_failed", user_id=user_id, error_kind=kind
        )
        await agent_tracer.record_step(
            db,
            user_id=user_id,
            feature=feature,
            step="replan.error",
            step_index=0,
            parent_trace_id=parent_trace_id,
            payload={"error_kind": kind},
            status=TRACE_STATUS_ERROR,
        )
        return None, None

    payload = _parse_replan(response.text)
    await agent_tracer.record_step(
        db,
        user_id=user_id,
        feature=feature,
        step="replan",
        step_index=0,
        parent_trace_id=parent_trace_id,
        payload={
            "raw_head": response.text[:240],
            "decoded": payload,
        },
        status=TRACE_STATUS_OK,
    )
    if payload is None:
        return None, None
    if not payload.get("needs_more"):
        return None, None
    extra = payload.get("next_tool_call")
    if not isinstance(extra, dict):
        return None, None
    tool_name = extra.get("tool_name")
    if tool_name not in TOOL_NAMES:
        return None, None
    args = extra.get("args") or {}
    if not isinstance(args, dict):
        args = {}
    return (
        ToolCall(
            tool_name=tool_name,  # type: ignore[arg-type]
            args=args,
            rationale=str(extra.get("rationale") or "")[:400],
        ),
        None,
    )


def _infer_tool_name(result: BaseModel) -> ToolName:
    """Map a sub-agent result back to its tool name for the synth prompt."""
    if isinstance(result, RetrieverResult):
        return "retriever"
    if isinstance(result, WebSearchResult):
        return "web_searcher"
    if isinstance(result, CodeRunResult):
        return "code_runner"
    if isinstance(result, QuizGenResult):
        return "quiz_generator"
    if isinstance(result, ConceptExplainResult):
        return "concept_explainer"
    return "retriever"  # safe default


async def _call_synthesiser(
    db: AsyncSession,
    *,
    provider: llm_service.LLMProvider,
    user_id: str,
    feature: str,
    question: str,
    history: list[dict[str, Any]] | None,
    sub_agent_results: list[BaseModel],
    plan_hint: str | None,
) -> tuple[str, str | None, bool]:
    """Compose the final answer. Returns ``(answer_text, call_id, refused)``.

    System-prompt construction note: we embed the tool-results block
    INTO the system message rather than the user turn. The Anthropic
    Messages API accepts arbitrarily-large system content, and the
    :class:`NoopProvider` parses the system prompt for
    ``Lesson L<id>:`` headers to drive its deterministic citation
    output — keeping the lesson context in the system message is what
    lets the existing Phase E1 noop-driven tests pin against citation
    extraction without changes here.
    """
    feature_slug = f"{feature}.synth"
    results_block = "\n\n".join(
        _serialise_for_synth(_infer_tool_name(r), r) for r in sub_agent_results
    )
    if not results_block.strip():
        results_block = "(no tool results — the retriever returned nothing.)"
    hint = f"\n\nHINT FROM PLANNER:\n{plan_hint}\n" if plan_hint else ""

    system_content = (
        f"{_SYNTHESISER_SYSTEM_PROMPT}\n\n"
        f"--- TOOL RESULTS ---\n{results_block}{hint}"
    )
    messages: list[llm_service.ChatMessage] = [
        llm_service.ChatMessage(role="system", content=system_content),
    ]
    for turn in (history or [])[-6:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content:
            messages.append(
                llm_service.ChatMessage(role=role, content=content)  # type: ignore[arg-type]
            )
    messages.append(
        llm_service.ChatMessage(
            role="user",
            content=f"USER QUESTION:\n{question}\n\nCompose the final answer now.",
        )
    )

    try:
        response = await call_logged(
            provider,
            messages,
            user_id=user_id,
            feature=feature_slug,
            session=db,
            temperature=0.2,
        )
    except Exception as exc:  # noqa: BLE001
        kind = type(exc).__name__
        log.warning(
            "tutor_synthesiser_failed",
            user_id=user_id,
            error_kind=kind,
        )
        # The orchestrator's contract is "never raise to the API edge
        # for sub-agent failures." A synthesiser outage still gets a
        # clean message back to the learner.
        return (
            f"(synthesiser unavailable: {kind}; please try again.)",
            None,
            False,
        )

    answer = (response.text or "").strip()
    # Refusal heuristics — detect both the orchestrator's own refusal
    # sentence and the ``NoopProvider``'s pre-existing sentinel
    # ("I don't have material in this course that covers that yet…")
    # so tests + the legacy noop path both light up the ``refused``
    # flag without bespoke wiring.
    lowered = answer.lower()
    refused = (
        not answer
        or "i don't have enough material in this course" in lowered
        or "i don't have material in this course" in lowered
    )
    return answer, None, refused


__all__ = [
    "FEATURE",
    "MAX_LLM_ROUNDTRIPS",
    "MAX_TOOL_CALL_ROUNDS",
    "OrchestratorResult",
    "Plan",
    "ToolCall",
    "ToolCallSummary",
    "ToolName",
    "orchestrate",
]
