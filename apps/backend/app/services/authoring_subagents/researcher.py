"""Researcher sub-agent — web snippets + catalog neighbours.

Lumen v2 Phase I3. The first step in the self-critique authoring
loop. Given a brief, the researcher:

1. Fetches 5-8 open-web snippets via Tavily (when ``TAVILY_API_KEY``
   is set; gracefully no-op otherwise — mirrors the I2 web-searcher).
2. Pulls the 5 most semantically-similar courses from Lumen's own
   catalog so the outliner can avoid duplicating existing material.
3. (Optionally) hands the raw bundle to a small LLM call that
   compresses it into a ~200-token research summary for the
   outliner's prompt. The compression call is gated behind a
   ``compress=True`` parameter; the test path skips it to keep the
   scripted-provider queue tight.

**No DB writes here.** This is a read-only sub-agent. Trace rows
are written by the orchestrator (it owns the ``CourseDraftTrace``
sequencing) so the researcher returns a pure :class:`ResearchBundle`
and lets the caller record the step.

**Graceful degradation.** Every external dependency (Tavily, embedding
provider, catalog query) is wrapped so an outage produces an empty
list with a note rather than failing the whole drafting run. The
orchestrator's contract is "never raise to the API edge for
sub-agent failures" — same trade-off the I2 web-searcher makes.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.course import Course, Lesson, Module
from app.models.lesson_chunk import LessonChunk
from app.services.embeddings import (
    EmbeddingProvider,
)
from app.services.embeddings import (
    get_provider as get_embedding_provider,
)
from app.services.visibility import retrieval_acl_clause

log = get_logger(__name__)

# Snippet content truncation — keeps the research bundle under
# control. Tavily returns ~1KB per result; 240 chars per snippet ×
# 5-8 snippets ≈ a 1.5KB context block which the outliner prompt
# can absorb without running over the model's context window.
SNIPPET_MAX_CHARS = 240

# Default snippet count requested from Tavily. The spec says 5-8;
# we default to 6 (the midpoint) and let the caller override.
DEFAULT_WEB_SNIPPETS = 6

# Default catalog-neighbour count. Five lets the outliner see what
# Lumen already covers without dominating the prompt.
DEFAULT_CATALOG_NEIGHBOURS = 5

# How many lesson chunks we scan before grouping by course. More
# chunks → better course ranking on small catalogs (one course
# might only contribute a handful of chunks). 80 is enough for the
# ~50-course catalogs the v1 deploy expects without being slow
# enough to matter — the index is on ``embedding``.
_CHUNK_SCAN_TOP_K = 80

# Same env-var name the I2 web-searcher uses, so the operator
# enables both surfaces with one key.
TAVILY_API_KEY_ENV = "TAVILY_API_KEY"


class ResearchWebSnippet(BaseModel):
    """One open-web result included in the bundle."""

    model_config = ConfigDict(frozen=True)

    title: str
    url: str
    content_first_240: str


class ResearchCatalogNeighbour(BaseModel):
    """One catalog course relevant to the brief."""

    model_config = ConfigDict(frozen=True)

    slug: str
    title: str


class ResearchBundle(BaseModel):
    """Output of :func:`run_researcher` — fed to the outliner."""

    model_config = ConfigDict(frozen=True)

    web_snippets: list[ResearchWebSnippet] = Field(default_factory=list)
    catalog_neighbours: list[ResearchCatalogNeighbour] = Field(default_factory=list)
    note: str = ""

    def to_prompt_block(self) -> str:
        """Render the bundle as a compact context block for the outliner.

        Stays under ~200 tokens for a typical 5-snippet / 5-neighbour
        bundle. The outliner consumes this verbatim — it's already
        labelled with ``WEB:`` / ``CATALOG:`` prefixes so the model
        can tell what's what.
        """
        if not self.web_snippets and not self.catalog_neighbours:
            return self.note or "(no research context available)"
        parts: list[str] = []
        if self.web_snippets:
            web_lines = "\n".join(
                f"- {s.title} ({s.url}): {s.content_first_240}" for s in self.web_snippets
            )
            parts.append(f"WEB:\n{web_lines}")
        if self.catalog_neighbours:
            cat_lines = "\n".join(f"- {n.slug}: {n.title}" for n in self.catalog_neighbours)
            parts.append(f"CATALOG (existing Lumen courses — avoid duplicating):\n{cat_lines}")
        if self.note:
            parts.append(f"NOTE: {self.note}")
        return "\n\n".join(parts)


def _has_api_key() -> str | None:
    """Return the configured Tavily key, or ``None`` if disabled."""
    raw = os.environ.get(TAVILY_API_KEY_ENV, "").strip()
    return raw or None


def _tavily_search_sync(api_key: str, query: str, max_results: int) -> dict[str, Any]:
    """Invoke the Tavily SDK synchronously (run via :func:`asyncio.to_thread`).

    The SDK is sync; we hop off the event loop so a slow upstream
    doesn't stall the orchestrator. Mirrors the I2 web-searcher's
    pattern exactly — kept duplicated rather than imported because
    the two sub-agents will diverge as authoring grows (the
    researcher may move to ``search_depth="advanced"`` later, for
    instance, while the tutor stays on basic).
    """
    from tavily import TavilyClient  # type: ignore[import-not-found]

    client = TavilyClient(api_key=api_key)
    return client.search(
        query=query,
        max_results=max_results,
        search_depth="basic",
    )


async def _fetch_web_snippets(
    *,
    query: str,
    max_results: int,
) -> tuple[list[ResearchWebSnippet], str]:
    """Tavily call wrapped in the graceful-degradation pattern.

    Returns ``(snippets, note)``. ``note`` is empty on success, a
    human-readable explanation otherwise (missing key / Tavily
    failure / no results).
    """
    api_key = _has_api_key()
    if api_key is None:
        return [], "web search disabled (no TAVILY_API_KEY)"
    try:
        raw = await asyncio.to_thread(_tavily_search_sync, api_key, query, max_results)
    except Exception as exc:
        kind = type(exc).__name__
        log.warning(
            "authoring_researcher_tavily_failed",
            error_kind=kind,
            query_head=query[:120],
        )
        return [], f"web search failed ({kind})"

    snippets: list[ResearchWebSnippet] = []
    for entry in (raw.get("results") or [])[:max_results]:
        title = str(entry.get("title") or "").strip() or "(untitled)"
        url = str(entry.get("url") or "").strip()
        content = str(entry.get("content") or "").strip()
        if len(content) > SNIPPET_MAX_CHARS:
            content = content[:SNIPPET_MAX_CHARS].rstrip() + "…"
        snippets.append(
            ResearchWebSnippet(
                title=title,
                url=url,
                content_first_240=content,
            )
        )
    return snippets, ""


async def _set_catalog_ef_search(db: AsyncSession) -> None:
    """Raise ``hnsw.ef_search`` for the upcoming cross-catalog vector SELECT.

    ADR-0029 D5.2 — see ``learning_path._set_catalog_ef_search`` for the full
    rationale. ``SET LOCAL`` is transaction-scoped (a no-op outside one), so we
    ensure a live transaction first. The value is a validated ``int`` from
    settings, so interpolating it is injection-safe (the GUC setter takes no
    bind parameters).
    """
    if not db.in_transaction():
        await db.begin()
    ef = int(get_settings().rag_hnsw_ef_search_catalog)
    await db.execute(text(f"SET LOCAL hnsw.ef_search = {ef}"))


async def _fetch_catalog_neighbours(
    db: AsyncSession,
    *,
    brief: str,
    top_k: int,
    embedding_provider: EmbeddingProvider | None = None,
    requesting_user_id: str | None = None,
) -> list[ResearchCatalogNeighbour]:
    """Top-K live catalog courses ranked by chunk similarity to the brief.

    Reuses the same cross-catalog retrieval shape that I5's
    ``_condense_catalog`` builds for the learning-path agent: scan
    ``_CHUNK_SCAN_TOP_K`` chunks by cosine distance, group them by
    course, return the top-K by hit count.

    Inlined rather than importing the I5 helper because:

    1. The output shape is smaller (we only need slug + title — no
       difficulty, overview, etc., so the prompt stays compact).
    2. The I5 helper is documented as the learning-path-specific
       digestor; sharing it would couple two unrelated surfaces
       together at the API contract.

    Graceful degradation: if there are no embedded chunks (a brand-
    new catalog, or one that hasn't run the embedding ingest job
    yet), falls back to the most-recently-published live courses.
    """
    if not brief.strip() or top_k <= 0:
        return []
    try:
        prov = embedding_provider or get_embedding_provider()
        [query_vec] = prov.embed([brief])
    except Exception as exc:
        log.warning(
            "authoring_researcher_embed_failed",
            error_kind=type(exc).__name__,
        )
        return []

    # ADR-0029 D5.2: widen the HNSW search frontier on this cross-catalog path
    # so post-filter recall holds when the ACL clause discards most private
    # candidates (mirrors learning_path._condense_catalog).
    await _set_catalog_ef_search(db)

    distance_col = LessonChunk.embedding.cosine_distance(query_vec).label("distance")
    stmt = (
        select(
            distance_col,
            Course.slug,
            Course.title,
            Course.id.label("course_id"),
        )
        .join(Lesson, Lesson.id == LessonChunk.lesson_id)
        .join(Module, Module.id == Lesson.module_id)
        .join(Course, Course.id == Module.course_id)
        .where(
            # Cross-catalog ACL (S2.7 / ADR-0029 §D2): only publicly-listed
            # courses + the requesting author's own — never another user's
            # private course leaks into the authoring research bundle.
            retrieval_acl_clause(requesting_user_id),
            Lesson.deleted_at.is_(None),
        )
        .order_by(distance_col)
        .limit(_CHUNK_SCAN_TOP_K)
    )
    rows = (await db.execute(stmt)).all()

    # Group by course id, preserve first-seen ordering (the cosine
    # order-by already ranks best-chunks-first; first appearance
    # therefore reflects best-chunk-first ranking).
    by_course: dict[str, ResearchCatalogNeighbour] = {}
    hit_counts: dict[str, int] = {}
    for row in rows:
        cid = row.course_id
        hit_counts[cid] = hit_counts.get(cid, 0) + 1
        if cid not in by_course:
            by_course[cid] = ResearchCatalogNeighbour(
                slug=row.slug,
                title=row.title,
            )

    if not by_course:
        # Fallback: the catalog hasn't been embedded yet, but it
        # might still have visible courses. Return the freshest
        # live ones so the outliner has *something* labelled.
        return await _fallback_recent_published(
            db, top_k=top_k, requesting_user_id=requesting_user_id
        )

    # Re-rank by hit count.
    ranked = sorted(
        by_course.items(),
        key=lambda kv: (-hit_counts[kv[0]], kv[1].title),
    )
    return [n for _cid, n in ranked[:top_k]]


async def _fallback_recent_published(
    db: AsyncSession, *, top_k: int, requesting_user_id: str | None = None
) -> list[ResearchCatalogNeighbour]:
    """Last-resort neighbour list when no chunks have been embedded."""
    stmt = (
        select(Course.slug, Course.title)
        .where(retrieval_acl_clause(requesting_user_id))
        .order_by(Course.published_at.desc().nullslast(), Course.created_at.desc())
        .limit(top_k)
    )
    rows = (await db.execute(stmt)).all()
    return [ResearchCatalogNeighbour(slug=r.slug, title=r.title) for r in rows]


async def run_researcher(
    db: AsyncSession,
    *,
    brief: str,
    web_max_results: int = DEFAULT_WEB_SNIPPETS,
    catalog_max_results: int = DEFAULT_CATALOG_NEIGHBOURS,
    embedding_provider: EmbeddingProvider | None = None,
    requesting_user_id: str | None = None,
) -> ResearchBundle:
    """Build a context bundle for the outliner from web + catalog.

    Pure function — no DB writes, no trace records. The orchestrator
    owns the trace sequencing and writes its own ``researcher`` row
    after this call returns.

    Both sources are fetched concurrently via :func:`asyncio.gather`
    so a slow Tavily upstream doesn't block the catalog query.
    """
    brief = brief.strip()
    if not brief:
        return ResearchBundle(note="empty brief")

    web_task = _fetch_web_snippets(query=brief, max_results=web_max_results)
    catalog_task = _fetch_catalog_neighbours(
        db,
        brief=brief,
        top_k=catalog_max_results,
        embedding_provider=embedding_provider,
        requesting_user_id=requesting_user_id,
    )
    (web_snippets, web_note), catalog = await asyncio.gather(web_task, catalog_task)

    note_parts: list[str] = []
    if web_note:
        note_parts.append(web_note)
    if not catalog:
        note_parts.append("catalog has no embedded chunks yet")
    return ResearchBundle(
        web_snippets=web_snippets,
        catalog_neighbours=catalog,
        note=" ; ".join(note_parts),
    )


__all__ = [
    "DEFAULT_CATALOG_NEIGHBOURS",
    "DEFAULT_WEB_SNIPPETS",
    "SNIPPET_MAX_CHARS",
    "TAVILY_API_KEY_ENV",
    "ResearchBundle",
    "ResearchCatalogNeighbour",
    "ResearchWebSnippet",
    "run_researcher",
]
