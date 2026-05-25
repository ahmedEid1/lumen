"""Web-searcher sub-agent — open-web context via Tavily.

Lumen v2 Phase I2. When the planner determines a question needs
context that isn't in the course's lessons (current events, fresh
documentation, an external definition the course glosses over), it
dispatches this tool. The synthesiser prefixes any facts derived
from web snippets with "Web context (not from the course):" so the
learner can see what's grounded in their course material vs the
open web.

**Provider: Tavily.** Free tier ships 1000 searches/month at the
time of writing, exposes a simple HTTP API, and returns clean
snippets (title + url + first ~240 chars of content) — the right
shape for a small synthesiser prompt. No streaming, no auth dance,
just one API call.

**Graceful degradation.** When ``TAVILY_API_KEY`` is unset (the
default in dev, in CI, and in any operator's first-boot install),
this sub-agent returns an empty :class:`WebSearchResult` with
``note="web search disabled (no TAVILY_API_KEY)"``. The orchestrator
records the trace and moves on; the synthesiser sees an empty
``snippets`` list and falls back to the retriever's chunks. This is
the same "passive observability" trade-off the cost meter and the
retrieval-audit table make — a missing optional integration must
never fail the learner-facing request.

**No LLM call here.** Like the retriever, this sub-agent doesn't
talk to a chat model — it talks to Tavily, then returns. The cost
meter records the Tavily call as zero-cost (no metering of external
HTTP today; a future :func:`web_search_cost_logged` wrapper could
land if we ever care). The H7 trace row records the search query
and the snippet count.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.agent_trace import TRACE_STATUS_ERROR, TRACE_STATUS_OK
from app.services import agent_tracer

log = get_logger(__name__)

# Snippet content truncation. Tavily returns up to ~1KB per result;
# we keep the first 240 chars so the synthesiser prompt stays
# bounded across N snippets.
SNIPPET_MAX_CHARS = 240
# Default snippet count requested from Tavily. Five is a reasonable
# middle ground — enough to triangulate a topical answer, few enough
# that the prompt stays under control.
DEFAULT_MAX_RESULTS = 5
# Environment variable the operator sets to enable web search. Kept
# as a module constant so the docs page + the tests can refer to
# the same name without string drift.
TAVILY_API_KEY_ENV = "TAVILY_API_KEY"


class WebSearchSnippet(BaseModel):
    """One open-web result surfaced to the synthesiser."""

    model_config = ConfigDict(frozen=True)

    title: str
    url: str
    content_first_240: str


class WebSearchResult(BaseModel):
    """Output of the web-searcher sub-agent."""

    model_config = ConfigDict(frozen=True)

    snippets: list[WebSearchSnippet] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    note: str = ""


def _has_api_key() -> str | None:
    """Return the configured Tavily API key, or ``None`` if disabled."""
    raw = os.environ.get(TAVILY_API_KEY_ENV, "").strip()
    return raw or None


def _tavily_search_sync(api_key: str, query: str, max_results: int) -> dict[str, Any]:
    """Invoke the Tavily SDK synchronously (run via ``asyncio.to_thread``).

    The SDK is synchronous; we hop off the event loop so a slow
    upstream doesn't stall the rest of the orchestrator. Errors
    surface here and the caller catches them — the orchestrator
    treats a Tavily error as "no web context available" rather
    than failing the whole turn.
    """
    from tavily import TavilyClient  # type: ignore[import-not-found]

    client = TavilyClient(api_key=api_key)
    return client.search(
        query=query,
        max_results=max_results,
        search_depth="basic",
    )


async def run(
    db: AsyncSession,
    *,
    query: str,
    user_id: str,
    feature: str = "tutor.multi_agent",
    step_index: int = 0,
    parent_trace_id: str | None = None,
    parent_call_id: str | None = None,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> WebSearchResult:
    """Dispatch a Tavily web search and record the trace step.

    On missing API key → empty result with a note. On Tavily error →
    empty result with the error class name in the note + an error
    trace row. On success → up to ``max_results`` snippets and one ok
    trace row.
    """
    api_key = _has_api_key()
    if api_key is None:
        note = "web search disabled (no TAVILY_API_KEY)"
        await agent_tracer.record_step(
            db,
            user_id=user_id,
            feature=feature,
            step="sub_agent.web_searcher",
            step_index=step_index,
            parent_trace_id=parent_trace_id,
            parent_call_id=parent_call_id,
            payload={
                "args": {"query": query[:240], "max_results": max_results},
                "result_summary": {"snippet_count": 0, "note": note},
            },
            status=TRACE_STATUS_OK,
        )
        return WebSearchResult(snippets=[], citations=[], note=note)

    try:
        raw = await asyncio.to_thread(
            _tavily_search_sync, api_key, query, max_results
        )
    except Exception as exc:  # noqa: BLE001 — graceful degradation
        kind = type(exc).__name__
        note = f"web search failed ({kind})"
        log.warning(
            "web_searcher_failed",
            user_id=user_id,
            error_kind=kind,
            query_head=query[:120],
        )
        await agent_tracer.record_step(
            db,
            user_id=user_id,
            feature=feature,
            step="sub_agent.web_searcher",
            step_index=step_index,
            parent_trace_id=parent_trace_id,
            parent_call_id=parent_call_id,
            payload={
                "args": {"query": query[:240], "max_results": max_results},
                "result_summary": {"snippet_count": 0, "note": note},
                "error_kind": kind,
            },
            status=TRACE_STATUS_ERROR,
        )
        return WebSearchResult(snippets=[], citations=[], note=note)

    snippets: list[WebSearchSnippet] = []
    citations: list[str] = []
    for entry in (raw.get("results") or [])[:max_results]:
        title = str(entry.get("title") or "").strip() or "(untitled)"
        url = str(entry.get("url") or "").strip()
        content = str(entry.get("content") or "").strip()
        if len(content) > SNIPPET_MAX_CHARS:
            content = content[:SNIPPET_MAX_CHARS].rstrip() + "…"
        snippets.append(
            WebSearchSnippet(
                title=title,
                url=url,
                content_first_240=content,
            )
        )
        if url:
            citations.append(url)

    note = f"found {len(snippets)} web snippet(s)"
    await agent_tracer.record_step(
        db,
        user_id=user_id,
        feature=feature,
        step="sub_agent.web_searcher",
        step_index=step_index,
        parent_trace_id=parent_trace_id,
        parent_call_id=parent_call_id,
        payload={
            "args": {"query": query[:240], "max_results": max_results},
            "result_summary": {
                "snippet_count": len(snippets),
                "note": note,
            },
        },
        status=TRACE_STATUS_OK,
    )
    return WebSearchResult(snippets=snippets, citations=citations, note=note)


__all__ = [
    "DEFAULT_MAX_RESULTS",
    "SNIPPET_MAX_CHARS",
    "TAVILY_API_KEY_ENV",
    "WebSearchResult",
    "WebSearchSnippet",
    "run",
]
