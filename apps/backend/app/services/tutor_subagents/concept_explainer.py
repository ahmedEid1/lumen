"""Concept-explainer sub-agent — "explain this differently".

Lumen v2 Phase I2. The planner dispatches this when a user pushes
back on a previous answer ("can you explain it more simply?",
"what's the intuition?", "use an analogy"). One focused LLM call
returns a re-phrasing plus an optional analogy.

**Why a dedicated sub-agent.** The synthesiser at the end of every
turn already produces a fluent answer. But "explain again, differently"
is a meaningfully different prompt: instead of synthesising over the
retriever's chunks, this sub-agent is told to lean on simpler
vocabulary + concrete examples. Splitting it out gives the trace a
clear "rephrasing" step the recruiter can point at — and gives the
synthesiser a structured input it can fold into its final answer
("Here's another way to see it: ...").

**Plain-text reply, no JSON.** The output is small and the parsing
contract is trivial (split into ``explanation`` + optional
``analogy`` by parsing two short labelled sections). We don't pay
the JSON-validation tax twice — the trace records the raw reply and
the structured projection.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.agent_trace import TRACE_STATUS_ERROR, TRACE_STATUS_OK
from app.services import agent_tracer
from app.services import llm as llm_service
from app.services.llm_call_log import call_logged

log = get_logger(__name__)

FEATURE = "tutor.subagent.concept_explainer"


class ConceptExplainResult(BaseModel):
    """Output of the concept-explainer sub-agent."""

    model_config = ConfigDict(frozen=True)

    explanation: str
    analogy: str | None = None
    note: str = ""


_SYSTEM_PROMPT = """\
You are Lumen's concept-explainer sub-agent. Your job is to re-phrase
a concept in plainer language for a learner who didn't follow the
first explanation. Use shorter sentences, concrete examples, and avoid
jargon. If a vivid analogy helps, include one.

Reply in exactly this format — two labelled sections, no markdown
fences, no preamble:

EXPLANATION:
<the re-phrased explanation, 2-5 short sentences>

ANALOGY:
<one optional analogy, single sentence. Leave blank if not useful.>

Hard rules:

  1. The EXPLANATION section is required and non-empty.
  2. The ANALOGY section is optional — if you can't think of a good
     analogy, leave the section header followed by a blank line.
  3. Plain text only. No bullet lists, no markdown headings inside
     the sections, no JSON.
"""


_SECTION_RE = re.compile(
    r"EXPLANATION:\s*(?P<expl>.*?)(?:\s*ANALOGY:\s*(?P<an>.*))?$",
    re.DOTALL,
)


def _parse_sections(raw: str) -> tuple[str, str | None]:
    """Split the labelled-sections reply. Tolerant of small format drift."""
    match = _SECTION_RE.search(raw)
    if match:
        explanation = (match.group("expl") or "").strip()
        analogy_raw = (match.group("an") or "").strip()
        analogy = analogy_raw if analogy_raw else None
        if explanation:
            return explanation, analogy
    # Fallback: treat the whole reply as the explanation. Lower
    # quality but never blank — the synthesiser still gets useful
    # material to fold into its final answer.
    return raw.strip(), None


async def run(
    db: AsyncSession,
    *,
    concept: str,
    context: str,
    user_id: str,
    feature: str = "tutor.multi_agent",
    step_index: int = 0,
    parent_trace_id: str | None = None,
    parent_call_id: str | None = None,
) -> ConceptExplainResult:
    """Re-explain ``concept``, optionally leaning on ``context``."""
    provider = llm_service.get_provider()
    user_prompt = (
        f"CONCEPT TO RE-EXPLAIN:\n{concept.strip() or '(no concept supplied)'}\n\n"
        f"CONTEXT (lesson excerpts to lean on, optional):\n"
        f"{context.strip() or '(no extra context)'}\n\n"
        "Reply now in the EXPLANATION / ANALOGY format."
    )
    messages = [
        llm_service.ChatMessage(role="system", content=_SYSTEM_PROMPT),
        llm_service.ChatMessage(role="user", content=user_prompt),
    ]

    try:
        response = await call_logged(
            provider,
            messages,
            user_id=user_id,
            feature=FEATURE,
            session=db,
            temperature=0.5,
        )
    except Exception as exc:
        kind = type(exc).__name__
        log.warning(
            "concept_explainer_llm_failed",
            user_id=user_id,
            error_kind=kind,
        )
        await agent_tracer.record_step(
            db,
            user_id=user_id,
            feature=feature,
            step="sub_agent.concept_explainer",
            step_index=step_index,
            parent_trace_id=parent_trace_id,
            parent_call_id=parent_call_id,
            payload={
                "args": {"concept": concept[:240]},
                "result_summary": {"note": f"LLM call failed: {kind}"},
                "error_kind": kind,
            },
            status=TRACE_STATUS_ERROR,
        )
        return ConceptExplainResult(
            explanation="(concept-explainer unavailable)",
            analogy=None,
            note=f"LLM call failed: {kind}",
        )

    explanation, analogy = _parse_sections(response.text)
    await agent_tracer.record_step(
        db,
        user_id=user_id,
        feature=feature,
        step="sub_agent.concept_explainer",
        step_index=step_index,
        parent_trace_id=parent_trace_id,
        parent_call_id=parent_call_id,
        payload={
            "args": {"concept": concept[:240], "context_len": len(context or "")},
            "result_summary": {
                "explanation_head": explanation[:160],
                "has_analogy": analogy is not None,
            },
        },
        status=TRACE_STATUS_OK,
    )
    return ConceptExplainResult(
        explanation=explanation or "(empty explanation)",
        analogy=analogy,
        note="",
    )


__all__ = ["FEATURE", "ConceptExplainResult", "run"]
