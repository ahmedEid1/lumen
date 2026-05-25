"""LLM-as-judge — score one model run against its golden item.

Lumen v2 Phase H2. The judge is a deliberately separate prompt path
from the feature it evaluates: the same LLM provider is reused, but
the **system prompt is built specifically for scoring**, never for
answering the user's question. This keeps the judge prompt
auditable in one place and makes it easy to swap a different judge
model later (we keep the option open via the ``judge_model`` knob
on the runner CLI).

Per-suite scoring axes
======================
- **tutor**: ``faithfulness`` (answer is grounded in the context),
  ``citation_correctness`` (each cited lesson actually contained the
  cited claim), ``helpfulness`` (the answer is the right shape and
  length for the question).
- **authoring**: ``coverage`` (the outline hits the brief's topics),
  ``learning_arc`` (lessons flow from foundations to application),
  ``scope`` (size is reasonable — neither thin nor bloated),
  ``brief_fidelity`` (the outline reads like an honest response to
  *this* brief, not a generic template).
- **ingest**: ``chapter_count_accuracy`` (number of chapters matches
  the expectation, within ±1), ``key_phrase_presence`` (each
  expected phrase appears somewhere in the output),
  ``structure_quality`` (the chaptering is sensible, not arbitrary
  splits on transcript timestamps).

All axes are scored 0–5 (integer). The judge also returns a short
``rationale`` string that the admin dashboard renders alongside the
score so a reviewer can see *why* the judge gave that number.

Robustness
==========
The judge prompt asks for JSON-only output. If the model returns
prose or malformed JSON we retry once with the error attached. Two
failures and we record ``{"judge_error": True}`` on the item so the
run as a whole still finishes — a couple of judge failures in 30
items is normal; a run-killing exception is not.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.services.llm import ChatMessage, LLMProvider, get_provider

log = get_logger(__name__)


# A judge chat function: takes (provider, messages) and returns the
# reply text. Pluggable so the runner can wrap each judge call in H1's
# ``call_logged`` for cost attribution, while a unit test can pass a
# plain callable that calls ``provider.chat`` directly.
ChatFn = Callable[[LLMProvider, list[ChatMessage]], Awaitable[str]]


async def _default_chat(provider: LLMProvider, messages: list[ChatMessage]) -> str:
    return await provider.chat(messages, temperature=0.0)


# ---------- Axes per suite ----------


TUTOR_AXES: tuple[str, ...] = (
    "faithfulness",
    "citation_correctness",
    "helpfulness",
)

AUTHORING_AXES: tuple[str, ...] = (
    "coverage",
    "learning_arc",
    "scope",
    "brief_fidelity",
)

INGEST_AXES: tuple[str, ...] = (
    "chapter_count_accuracy",
    "key_phrase_presence",
    "structure_quality",
)


# ---------- Score dataclass ----------


@dataclass(frozen=True, slots=True)
class JudgeResult:
    """One score envelope.

    ``scores`` keys are the suite's axis names; values are ints in
    ``[0, 5]``. ``rationale`` is a free-form short string the judge
    returns to justify the score. ``judge_error`` is ``True`` only
    when both attempts at parsing the judge reply failed — when
    that happens, ``scores`` is empty and the item is excluded from
    the mean-score rollup the report computes.
    """

    scores: dict[str, int]
    rationale: str
    judge_error: bool = False
    raw_replies: list[str] = field(default_factory=list)

    def mean(self) -> float | None:
        if self.judge_error or not self.scores:
            return None
        return sum(self.scores.values()) / len(self.scores)


# ---------- Prompt builders ----------


def _tutor_prompt(*, item: dict[str, Any], actual: dict[str, Any]) -> str:
    """Build the tutor scorer's user prompt.

    ``item`` carries the golden fields (question, ideal_answer,
    must_cite_lessons). ``actual`` carries what the live tutor
    produced (answer, citations).
    """
    must_cite = item.get("must_cite_lessons") or []
    citations = actual.get("citations") or []
    return (
        "Score the candidate's tutor answer 0-5 on three axes:\n"
        "  - faithfulness: every claim is supported by the course content\n"
        "  - citation_correctness: each cited lesson actually contains the "
        "claim it's attached to, and the must-cite lessons are present\n"
        "  - helpfulness: the answer is the right shape and length\n\n"
        "Return STRICT JSON only — no prose, no markdown fences — matching:\n"
        '{"faithfulness": 0-5, "citation_correctness": 0-5, '
        '"helpfulness": 0-5, "rationale": "one short sentence"}\n\n'
        f"Question: {item.get('question', '')}\n\n"
        f"Ideal answer (reference): {item.get('ideal_answer', '')}\n\n"
        f"Must-cite lessons (titles): {json.dumps(must_cite)}\n\n"
        f"Actual answer: {actual.get('answer', '')}\n\n"
        f"Citations emitted by the model: {json.dumps(citations)}"
    )


def _authoring_prompt(*, item: dict[str, Any], actual: dict[str, Any]) -> str:
    return (
        "Score the candidate's course outline 0-5 on four axes:\n"
        "  - coverage: hits the topics the brief asks for\n"
        "  - learning_arc: lessons sequence from foundations to application\n"
        "  - scope: 3-6 modules, 3-5 lessons each, neither thin nor bloated\n"
        "  - brief_fidelity: the outline reads like an honest response to "
        "this brief, not a generic template\n\n"
        "Return STRICT JSON only — no prose, no markdown fences — matching:\n"
        '{"coverage": 0-5, "learning_arc": 0-5, "scope": 0-5, '
        '"brief_fidelity": 0-5, "rationale": "one short sentence"}\n\n'
        f"Brief: {item.get('brief', '')}\n\n"
        f"Ideal outline (reference): "
        f"{json.dumps(item.get('ideal_outline') or {}, ensure_ascii=False)}\n\n"
        f"Actual outline: "
        f"{json.dumps(actual.get('outline') or {}, ensure_ascii=False)}"
    )


def _ingest_prompt(*, item: dict[str, Any], actual: dict[str, Any]) -> str:
    return (
        "Score the candidate's ingest result 0-5 on three axes:\n"
        "  - chapter_count_accuracy: number of chapters matches the "
        "expectation (within ±1)\n"
        "  - key_phrase_presence: each expected phrase appears somewhere "
        "in the output\n"
        "  - structure_quality: chaptering is sensible, not arbitrary "
        "splits on transcript timestamps\n\n"
        "Return STRICT JSON only — no prose, no markdown fences — matching:\n"
        '{"chapter_count_accuracy": 0-5, "key_phrase_presence": 0-5, '
        '"structure_quality": 0-5, "rationale": "one short sentence"}\n\n'
        f"URL: {item.get('url', '')} (kind: {item.get('kind', '')})\n\n"
        f"Expected chapter count: {item.get('expected_chapter_count')}\n"
        f"Expected key phrases: {json.dumps(item.get('expected_key_phrases') or [])}\n\n"
        f"Actual chapters: "
        f"{json.dumps(actual.get('chapters') or [], ensure_ascii=False)}\n\n"
        f"Actual key phrases / titles: "
        f"{json.dumps(actual.get('key_phrases') or [], ensure_ascii=False)}"
    )


_PROMPT_BUILDERS = {
    "tutor": (_tutor_prompt, TUTOR_AXES),
    "authoring": (_authoring_prompt, AUTHORING_AXES),
    "ingest": (_ingest_prompt, INGEST_AXES),
}


_JUDGE_SYSTEM = (
    "You are a strict evaluation judge for an AI-first learning platform. "
    "You output only JSON. No prose, no markdown code fences, no commentary "
    "outside the JSON object. Every score is an integer in [0, 5]. "
    "Be conservative — a 5 means 'no flaws I can find'; most real outputs "
    "should land 3-4."
)


# ---------- Parsing ----------


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _strip_fences(raw: str) -> str:
    m = _FENCE_RE.search(raw)
    if m:
        return m.group(1).strip()
    return raw.strip()


def _coerce_scores(payload: Any, axes: tuple[str, ...]) -> tuple[dict[str, int] | None, str | None]:
    """Coerce the judge's JSON to ``{axis: int}`` and a rationale.

    Returns ``({...}, None)`` on success, ``(None, error_msg)`` on
    failure. We accept floats and round; we clamp to [0, 5] to
    forgive a judge that emits 6 or -1. Missing axes are an error.
    """
    if not isinstance(payload, dict):
        return None, "judge reply was not a JSON object"

    out: dict[str, int] = {}
    for axis in axes:
        if axis not in payload:
            return None, f"missing axis '{axis}'"
        raw = payload[axis]
        try:
            score = int(round(float(raw)))
        except (TypeError, ValueError):
            return None, f"axis '{axis}' was not numeric: {raw!r}"
        out[axis] = max(0, min(5, score))
    return out, None


def _parse_judge_reply(raw: str, axes: tuple[str, ...]) -> tuple[dict[str, int] | None, str, str | None]:
    """Parse one judge reply.

    Returns ``(scores, rationale, error_msg)``. ``scores`` is None on
    failure; ``rationale`` is "" on failure.
    """
    body = _strip_fences(raw)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return None, "", f"JSON parse error: {exc.msg}"
    scores, err = _coerce_scores(payload, axes)
    if scores is None:
        return None, "", err
    rationale = ""
    if isinstance(payload, dict):
        r = payload.get("rationale")
        if isinstance(r, str):
            rationale = r.strip()
    return scores, rationale, None


# ---------- Public entry point ----------


async def judge_item(
    suite: str,
    *,
    item: dict[str, Any],
    actual: dict[str, Any],
    provider: LLMProvider | None = None,
    chat_fn: ChatFn | None = None,
) -> JudgeResult:
    """Score one (item, actual) pair.

    On a malformed judge reply we retry exactly once with the error
    fed back to the model — same shallow-retry policy that
    ``ai_authoring._chat_with_retry`` lands on. Two failures and we
    record ``judge_error=True``; the run continues.

    ``chat_fn`` lets the caller override how the judge's LLM call is
    dispatched — the runner uses this to thread H1's ``call_logged``
    so every judge round-trip lands in the cost meter under
    ``feature="eval.judge"``. Tests pass ``None`` and get the
    default ``provider.chat`` path.
    """
    if suite not in _PROMPT_BUILDERS:
        raise ValueError(f"unknown suite: {suite}")
    build_prompt, axes = _PROMPT_BUILDERS[suite]
    user_prompt = build_prompt(item=item, actual=actual)
    prov = provider or get_provider()
    call = chat_fn or _default_chat

    raw_replies: list[str] = []

    messages = [
        ChatMessage(role="system", content=_JUDGE_SYSTEM),
        ChatMessage(role="user", content=user_prompt),
    ]
    raw1 = await call(prov, messages)
    raw_replies.append(raw1)
    scores, rationale, err = _parse_judge_reply(raw1, axes)
    if scores is not None:
        return JudgeResult(scores=scores, rationale=rationale, raw_replies=raw_replies)

    # Retry once with the parse error attached. The follow-up turn
    # quotes the error verbatim so the model can self-correct without
    # us re-engineering the prompt.
    messages.extend(
        [
            ChatMessage(role="assistant", content=raw1),
            ChatMessage(
                role="user",
                content=(
                    "Your previous reply could not be parsed.\n"
                    f"Error: {err}\n\n"
                    "Reply with a corrected JSON object only — no prose, "
                    "no markdown fences."
                ),
            ),
        ]
    )
    raw2 = await call(prov, messages)
    raw_replies.append(raw2)
    scores, rationale, err2 = _parse_judge_reply(raw2, axes)
    if scores is not None:
        log.info("judge_retry_succeeded", suite=suite, first_error=err)
        return JudgeResult(scores=scores, rationale=rationale, raw_replies=raw_replies)

    log.warning(
        "judge_failed",
        suite=suite,
        first_error=err,
        retry_error=err2,
        first_raw_head=raw1[:200],
        retry_raw_head=raw2[:200],
    )
    return JudgeResult(
        scores={},
        rationale=f"judge error: {err2 or err}",
        judge_error=True,
        raw_replies=raw_replies,
    )


__all__ = [
    "AUTHORING_AXES",
    "INGEST_AXES",
    "JudgeResult",
    "TUTOR_AXES",
    "judge_item",
]
