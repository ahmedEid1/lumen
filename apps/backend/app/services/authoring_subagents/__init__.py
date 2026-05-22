"""Authoring sub-agents for the self-critique loop (Lumen v2 Phase I3).

Each module is one focused sub-agent the orchestrator dispatches:

* :mod:`researcher` — Tavily web search + catalog-neighbour lookup,
  compressed into a ~200-token context bundle for the outliner.

The critic / reviser / final-critic sub-agents live inline in
:mod:`app.services.authoring_orchestrator` because they're small
single-LLM-call wrappers tightly coupled to the orchestrator's
state machine. The researcher is split out because it does
non-LLM work (Tavily HTTP + a catalog DB query) the orchestrator
shouldn't have to know the shape of.
"""

from app.services.authoring_subagents.researcher import (
    ResearchBundle,
    ResearchCatalogNeighbour,
    ResearchWebSnippet,
    run_researcher,
)

__all__ = [
    "ResearchBundle",
    "ResearchCatalogNeighbour",
    "ResearchWebSnippet",
    "run_researcher",
]
