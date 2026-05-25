"""Tutor sub-agent package — the five tools the planner can dispatch.

Lumen v2 Phase I2 (the multi-agent tutor). The planner-orchestrator
in :mod:`app.services.tutor_orchestrator` picks one or more of these
sub-agents per turn; each module here owns one tool and exposes a
single ``run(...)`` coroutine that returns a Pydantic result model.

The five tools, mapped to their result models:

* :mod:`retriever`         → :class:`RetrieverResult`
    Pure RAG retrieval over ``lesson_chunks`` for the current course.
    No LLM call — wraps :func:`find_relevant_chunks(audit=True)` and
    surfaces the chunks + their citation lesson ids.
* :mod:`web_searcher`      → :class:`WebSearchResult`
    Tavily-backed web search. Disabled (returns an empty result with
    a ``note=...``) when ``TAVILY_API_KEY`` is unset — graceful
    degradation rather than a hard failure.
* :mod:`code_runner`       → :class:`CodeRunResult`
    RestrictedPython-sandboxed Python execution. Hard timeout. No
    network, no filesystem, no ``__import__``. Documented limits.
* :mod:`quiz_generator`    → :class:`QuizGenResult`
    "Give me a practice question" — one LLM call returning a 4-option
    MCQ with the correct answer index + an explanation.
* :mod:`concept_explainer` → :class:`ConceptExplainResult`
    "Explain this differently" — one LLM call returning a re-phrasing
    plus an optional analogy.

Each sub-agent:

* Writes one ``agent_traces`` row via :func:`agent_tracer.record_step`
  with ``step="sub_agent.<name>"``, parented to the orchestrator's
  current step (the planner or the re-plan).
* If it makes an LLM call, the call goes through
  :func:`llm_call_log.call_logged` with
  ``feature="tutor.subagent.<name>"`` and the resulting ``llm_calls.id``
  is recorded as ``parent_call_id`` on the trace row.
* Returns a Pydantic model so the orchestrator can serialise its
  payload into the synthesiser's prompt without bespoke JSON wrangling.

Every sub-agent is async even when it doesn't need to be (the code
runner is CPU-bound, the retriever is async-DB) so the orchestrator
can dispatch them with a uniform ``await``.
"""

from __future__ import annotations

from app.services.tutor_subagents.code_runner import (
    CodeRunResult,
    run as run_code_runner,
)
from app.services.tutor_subagents.concept_explainer import (
    ConceptExplainResult,
    run as run_concept_explainer,
)
from app.services.tutor_subagents.quiz_generator import (
    QuizGenResult,
    run as run_quiz_generator,
)
from app.services.tutor_subagents.retriever import (
    RetrieverChunk,
    RetrieverResult,
    run as run_retriever,
)
from app.services.tutor_subagents.web_searcher import (
    WebSearchResult,
    WebSearchSnippet,
    run as run_web_searcher,
)

__all__ = [
    "CodeRunResult",
    "ConceptExplainResult",
    "QuizGenResult",
    "RetrieverChunk",
    "RetrieverResult",
    "WebSearchResult",
    "WebSearchSnippet",
    "run_code_runner",
    "run_concept_explainer",
    "run_quiz_generator",
    "run_retriever",
    "run_web_searcher",
]
