"""Quiz-generator sub-agent — "give me a practice question".

Lumen v2 Phase I2. The planner dispatches this when the user asks
for a practice question, a knowledge check, or any form of "test me
on this". One LLM call produces a 4-option multiple-choice question
grounded in the supplied lesson context, plus the correct answer
index + a one-sentence explanation.

The sub-agent doesn't try to grade the learner — it just emits the
MCQ. The frontend's reasoning panel renders the question for the
recruiter watching the trace; the synthesiser embeds it into the
final answer so the learner sees a clean "Here's a question to test
your understanding" follow-up.

**Why structured JSON, not free text.** The synthesiser needs to
know which option is correct so it can render the question without
spoiling the answer. Free text would force the synthesiser to
parse "the answer is (b)" out of natural language, which is exactly
the failure mode structured outputs solve.

**Validation + one-shot retry.** Same pattern as :mod:`learning_path`:
parse the LLM's JSON, validate against a tight Pydantic model, and
retry once with the validation error in the user turn. Two failures
return a stubbed "couldn't generate a quiz" result rather than
raising — the planner shouldn't have a whole turn blow up because
one sub-agent flaked.
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.agent_trace import TRACE_STATUS_ERROR, TRACE_STATUS_OK
from app.services import agent_tracer
from app.services import llm as llm_service
from app.services.llm_call_log import call_logged

log = get_logger(__name__)

FEATURE = "tutor.subagent.quiz_generator"

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class QuizGenResult(BaseModel):
    """One generated practice question."""

    model_config = ConfigDict(frozen=True)

    prompt: str = Field(min_length=1, max_length=600)
    options: list[str] = Field(min_length=2, max_length=6)
    answer_index: int = Field(ge=0)
    explanation: str = Field(min_length=1, max_length=600)
    note: str = ""

    @field_validator("answer_index")
    @classmethod
    def _index_non_negative(cls, v: int) -> int:
        # Cross-referencing ``options`` here would require
        # ``ValidationInfo`` access; the orchestrator catches an
        # out-of-range index in ``_try_parse`` and falls back to the
        # stub result, so we only enforce the non-negativity floor
        # here. ``Field(ge=0)`` already does the same; the explicit
        # validator gives us a friendlier error message for the
        # one-shot retry prompt.
        if v < 0:
            raise ValueError("answer_index must be non-negative")
        return v


_SYSTEM_PROMPT = """\
You are Lumen's quiz-generator sub-agent. Given a topic and a short
context block of lesson excerpts, emit ONE multiple-choice question
that tests genuine understanding of the topic (not trivia, not
vocabulary). Return strict JSON with this exact shape — no prose, no
markdown fences, no commentary:

{
  "prompt": "Question text, 1-2 sentences.",
  "options": ["Option A", "Option B", "Option C", "Option D"],
  "answer_index": 2,
  "explanation": "One sentence on why the correct option is correct."
}

Hard rules:

  1. Exactly four options unless the topic naturally has fewer (then
     at least two). Each option must be a distinct, plausible answer.
  2. ``answer_index`` is 0-based against ``options``.
  3. The explanation must reference the supplied context, not the
     model's prior knowledge.
  4. Return ONE JSON object. No fences, no preamble.
"""


def _strip_json_fence(raw: str) -> str:
    fence = _JSON_FENCE_RE.search(raw)
    if fence:
        return fence.group(1).strip()
    return raw.strip()


def _try_parse(raw: str) -> tuple[QuizGenResult | None, str | None]:
    """Parse + validate raw LLM output. Returns ``(result, None)`` or ``(None, err)``."""
    body = _strip_json_fence(raw)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return None, f"JSON parse error: {exc.msg} at line {exc.lineno}"
    try:
        result = QuizGenResult.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []))
        msg = first.get("msg", "validation error")
        return None, f"validation error at {loc or '<root>'}: {msg}"
    if result.answer_index >= len(result.options):
        return None, (
            f"answer_index {result.answer_index} is out of range "
            f"for options of length {len(result.options)}"
        )
    return result, None


def _fallback(reason: str) -> QuizGenResult:
    """Stub result when the LLM fails twice."""
    return QuizGenResult(
        prompt="(quiz generation unavailable)",
        options=["(no options)", "(no options)"],
        answer_index=0,
        explanation="The quiz-generator sub-agent could not produce a question.",
        note=reason,
    )


async def run(
    db: AsyncSession,
    *,
    topic: str,
    context: str,
    user_id: str,
    feature: str = "tutor.multi_agent",
    step_index: int = 0,
    parent_trace_id: str | None = None,
    parent_call_id: str | None = None,
) -> QuizGenResult:
    """Generate one MCQ for ``topic`` grounded in ``context``.

    ``context`` should be a short block of lesson excerpts (e.g. the
    retriever's serialised chunks). If it's empty the LLM is told
    explicitly to lean on the topic alone — the result will be lower
    quality but still in the schema.
    """
    provider = llm_service.get_provider()
    user_prompt = (
        f"TOPIC:\n{topic.strip() or '(no topic)'}\n\n"
        f"CONTEXT (lesson excerpts):\n{context.strip() or '(no context — use the topic alone)'}\n\n"
        "Emit the JSON object now."
    )
    messages = [
        llm_service.ChatMessage(role="system", content=_SYSTEM_PROMPT),
        llm_service.ChatMessage(role="user", content=user_prompt),
    ]

    # ---- Turn 1 ----
    try:
        response = await call_logged(
            provider,
            messages,
            user_id=user_id,
            feature=FEATURE,
            session=db,
            temperature=0.4,
        )
    except Exception as exc:
        kind = type(exc).__name__
        log.warning(
            "quiz_generator_llm_failed",
            user_id=user_id,
            error_kind=kind,
        )
        await agent_tracer.record_step(
            db,
            user_id=user_id,
            feature=feature,
            step="sub_agent.quiz_generator",
            step_index=step_index,
            parent_trace_id=parent_trace_id,
            parent_call_id=parent_call_id,
            payload={
                "args": {"topic": topic[:240], "context_len": len(context or "")},
                "result_summary": {"note": f"LLM call failed: {kind}"},
                "error_kind": kind,
            },
            status=TRACE_STATUS_ERROR,
        )
        return _fallback(f"LLM call failed: {kind}")

    result, err = _try_parse(response.text)
    if result is not None:
        await agent_tracer.record_step(
            db,
            user_id=user_id,
            feature=feature,
            step="sub_agent.quiz_generator",
            step_index=step_index,
            parent_trace_id=parent_trace_id,
            parent_call_id=parent_call_id,
            payload={
                "args": {"topic": topic[:240], "context_len": len(context or "")},
                "result_summary": {
                    "prompt_head": result.prompt[:120],
                    "option_count": len(result.options),
                    "answer_index": result.answer_index,
                },
            },
            status=TRACE_STATUS_OK,
        )
        return result

    # ---- Turn 2 (retry with the validation error in the user turn) ----
    messages.extend(
        [
            llm_service.ChatMessage(role="assistant", content=response.text),
            llm_service.ChatMessage(
                role="user",
                content=(
                    "Your previous response was invalid. "
                    f"Reason: {err}\n\n"
                    "Reply again with a corrected JSON object that matches "
                    "the schema exactly. No prose, no markdown fences."
                ),
            ),
        ]
    )
    try:
        response2 = await call_logged(
            provider,
            messages,
            user_id=user_id,
            feature=FEATURE,
            session=db,
            temperature=0.4,
        )
    except Exception as exc:
        kind = type(exc).__name__
        log.warning(
            "quiz_generator_llm_failed_retry",
            user_id=user_id,
            error_kind=kind,
        )
        await agent_tracer.record_step(
            db,
            user_id=user_id,
            feature=feature,
            step="sub_agent.quiz_generator",
            step_index=step_index,
            parent_trace_id=parent_trace_id,
            parent_call_id=parent_call_id,
            payload={
                "args": {"topic": topic[:240]},
                "result_summary": {"note": f"retry LLM call failed: {kind}"},
                "error_kind": kind,
            },
            status=TRACE_STATUS_ERROR,
        )
        return _fallback(f"retry LLM call failed: {kind}")

    result2, err2 = _try_parse(response2.text)
    if result2 is not None:
        await agent_tracer.record_step(
            db,
            user_id=user_id,
            feature=feature,
            step="sub_agent.quiz_generator",
            step_index=step_index,
            parent_trace_id=parent_trace_id,
            parent_call_id=parent_call_id,
            payload={
                "args": {"topic": topic[:240]},
                "result_summary": {
                    "prompt_head": result2.prompt[:120],
                    "recovered_on_retry": True,
                },
            },
            status=TRACE_STATUS_OK,
        )
        return result2

    log.warning(
        "quiz_generator_bad_output",
        user_id=user_id,
        first_error=err,
        retry_error=err2,
    )
    await agent_tracer.record_step(
        db,
        user_id=user_id,
        feature=feature,
        step="sub_agent.quiz_generator",
        step_index=step_index,
        parent_trace_id=parent_trace_id,
        parent_call_id=parent_call_id,
        payload={
            "args": {"topic": topic[:240]},
            "result_summary": {
                "note": "invalid output after retry",
                "first_error": err,
                "retry_error": err2,
            },
        },
        status=TRACE_STATUS_ERROR,
    )
    return _fallback("invalid output after retry")


__all__ = ["FEATURE", "QuizGenResult", "run"]
