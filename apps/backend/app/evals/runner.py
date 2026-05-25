"""Eval-suite runner — calls the live feature and the judge per item.

Lumen v2 Phase H2. The runner is the only module that knows how to
glue the three pieces together: load a golden dataset, dispatch
each item to the right feature service, call the judge on the
result, and append the scored row to the JSONL report.

Architectural posture
=====================
The runner is **synchronous-from-the-CLI but async-internally**.
``main()`` opens its own event loop and DB session; it does not
import FastAPI's request lifecycle. That keeps the eval runnable
from a Celery task, a CI job, or the admin "kick off a run"
endpoint without three different code paths.

Every LLM call inside the runner is routed through the H1
``call_logged`` wrapper so eval traffic shows up in the cost meter
under ``feature="eval.tutor"``, ``"eval.authoring"``, ``"eval.judge"``.
The wrapper might not be importable yet in a CI build that runs
before H1 lands; we fall back to a no-op pass-through so the
runner exercise its own code path either way.

Skip / failure semantics
========================
- ``status="ok"`` — feature ran, judge ran (or judge_errored), row
  has scores.
- ``status="skipped"`` — feature couldn't run for a data-shape
  reason (course not seeded for tutor; no DB context for authoring
  is **not** skip — authoring runs without DB).
- ``status="error"`` — feature raised; we record the exception
  class and message and move on. The run as a whole always
  completes.
"""

from __future__ import annotations

import time
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.db.base import get_sessionmaker
from app.evals import judge as judge_mod
from app.evals.golden import (
    AuthoringItem,
    IngestItem,
    SuiteName,
    TutorItem,
    load_dataset,
)
from app.evals.reports import (
    compute_summary,
    latest_previous_report,
    new_report_path,
    read_report,
    write_item,
)
from app.models.course import Course, Module
from app.services.llm import ChatMessage, get_provider

log = get_logger(__name__)


# H1 ``call_logged`` is the cost-meter wrapper. It records tokens,
# cost, latency, and the per-user budget guard around each LLM call.
# The tutor + AI authoring services already route their main LLM
# call through ``call_logged`` internally (see ``tutor.ask(user_id=...,
# feature=...)``), so the runner doesn't have to wrap those — it
# just passes ``feature="eval.tutor"`` etc. so the rows are
# attributable in the cost meter.
#
# The JUDGE call is the runner's own LLM hop and is metered via
# ``call_logged`` directly. We import defensively so a build where
# H1 hasn't landed yet still exercises the runner code path — the
# fallback bypasses the meter and calls ``provider.chat`` directly.
try:  # pragma: no cover — imported in a real build
    from app.models.llm_call import SYSTEM_USER_ID
    from app.services.llm_call_log import call_logged as _real_call_logged

    async def _judge_call(provider: Any, messages: list[ChatMessage], *, session: Any) -> str:
        response = await _real_call_logged(
            provider,
            messages,
            user_id=SYSTEM_USER_ID,
            feature="eval.judge",
            session=session,
            temperature=0.0,
        )
        return response.text

except Exception:  # pragma: no cover — H1 not landed yet
    SYSTEM_USER_ID = "__system__"  # type: ignore[assignment]

    async def _judge_call(  # type: ignore[no-redef]
        provider: Any, messages: list[ChatMessage], *, session: Any
    ) -> str:
        return await provider.chat(messages, temperature=0.0)


# ---------- Tutor suite ----------


async def _load_course_with_lessons(db: AsyncSession, slug: str) -> Course | None:
    """Eager-load a course + its modules + lessons by slug.

    Returns ``None`` if the course isn't seeded — the runner
    converts that into a ``status="skipped"`` row.
    """
    stmt = (
        select(Course)
        .where(Course.slug == slug, Course.deleted_at.is_(None))
        .options(selectinload(Course.modules).selectinload(Module.lessons))
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def _resolve_lesson_titles(course: Course, titles: list[str]) -> tuple[list[str], list[str]]:
    """Map lesson titles to lesson ids.

    Returns ``(resolved_ids, unresolved_titles)``. The runner
    surfaces the unresolved set on the report row so a reviewer
    can see immediately when a dataset references a lesson the
    seed doesn't contain.
    """
    by_title: dict[str, str] = {}
    for module in course.modules or []:
        for lesson in module.lessons or []:
            if lesson.title and lesson.title not in by_title:
                by_title[lesson.title] = lesson.id
    resolved: list[str] = []
    unresolved: list[str] = []
    for title in titles:
        lid = by_title.get(title)
        if lid:
            resolved.append(lid)
        else:
            unresolved.append(title)
    return resolved, unresolved


async def _run_tutor_item(db: AsyncSession, item: TutorItem) -> dict[str, Any]:
    """Run the tutor service against one golden item."""
    from app.services import tutor as tutor_service

    course = await _load_course_with_lessons(db, item.course_slug)
    if course is None:
        return {
            "status": "skipped",
            "reason": "course_not_seeded",
            "course_slug": item.course_slug,
        }

    resolved_lesson_ids, unresolved_titles = _resolve_lesson_titles(course, item.must_cite_lessons)

    started = time.perf_counter()
    try:
        # H1 wires ``tutor.ask`` through ``call_logged`` internally;
        # we just pass the eval feature tag + the system sentinel
        # user id so the row attributes correctly in the cost meter.
        result = await tutor_service.ask(
            db,
            course=course,
            user_message=item.question,
            user_id=SYSTEM_USER_ID,
            feature="eval.tutor",
        )
    except Exception as exc:
        return {
            "status": "error",
            "error_kind": exc.__class__.__name__,
            "error_message": str(exc)[:500],
        }
    latency_ms = int((time.perf_counter() - started) * 1000)

    cited_ids = [c.lesson_id for c in result.citations]
    must_cite_hits = sum(1 for lid in resolved_lesson_ids if lid in cited_ids)
    return {
        "status": "ok",
        "course_slug": item.course_slug,
        "course_id": course.id,
        "answer": result.answer,
        "citations": [c.to_dict() for c in result.citations],
        "refused": result.refused,
        "must_cite_resolved_ids": resolved_lesson_ids,
        "must_cite_unresolved_titles": unresolved_titles,
        "must_cite_hit_count": must_cite_hits,
        "must_cite_expected_count": len(resolved_lesson_ids),
        "latency_ms": latency_ms,
    }


# ---------- Authoring suite ----------


def _outline_to_dict(outline: Any) -> dict[str, Any]:
    """Serialise an outline (pydantic model OR plain dict) for the report."""
    if outline is None:
        return {"modules": []}
    if isinstance(outline, dict):
        return outline
    # Pydantic v2 model
    if hasattr(outline, "model_dump"):
        return outline.model_dump()
    if is_dataclass(outline):
        return asdict(outline)
    return {"modules": []}


async def _run_authoring_item(item: AuthoringItem, db: AsyncSession) -> dict[str, Any]:
    """Run the AI-authoring outline generator against one brief."""
    from app.services import ai_authoring

    started = time.perf_counter()
    try:
        # H1's ``ai_authoring.generate_outline`` accepts an optional
        # session + user_id and routes through ``call_logged`` when
        # both are supplied. The system sentinel keeps the eval
        # traffic out of any user's budget while still attributing
        # cost in the meter.
        outline = await ai_authoring.generate_outline(
            item.brief, session=db, user_id=SYSTEM_USER_ID
        )
    except Exception as exc:
        return {
            "status": "error",
            "error_kind": exc.__class__.__name__,
            "error_message": str(exc)[:500],
        }
    latency_ms = int((time.perf_counter() - started) * 1000)

    actual_outline = _outline_to_dict(outline)
    actual_module_count = len(actual_outline.get("modules") or [])
    ideal_module_count = len(item.ideal_outline.modules if item.ideal_outline else [])
    return {
        "status": "ok",
        "outline": actual_outline,
        "module_count": actual_module_count,
        "ideal_module_count": ideal_module_count,
        "latency_ms": latency_ms,
    }


# ---------- Ingest suite ----------


def _payload_to_chapters(payload: Any) -> list[dict[str, Any]]:
    """Extract a chapter-shaped list from an IngestPayload (for the judge)."""
    if payload is None:
        return []
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    modules = (payload or {}).get("modules") or []
    out: list[dict[str, Any]] = []
    for m in modules:
        out.append(
            {
                "title": m.get("title", ""),
                "lesson_titles": [l.get("title", "") for l in (m.get("lessons") or [])],
            }
        )
    return out


async def _run_ingest_item(item: IngestItem) -> dict[str, Any]:
    """Run the ingest service against one URL.

    The ingest service is synchronous (no DB I/O on the extract
    path), but it does network work — and that's the part most
    likely to fail intermittently in CI. The runner catches the
    network exception and records ``status="error"`` so the suite
    keeps going.
    """
    from app.services import content_ingest

    started = time.perf_counter()
    try:
        payload = content_ingest.ingest(item.url)
    except Exception as exc:
        return {
            "status": "error",
            "error_kind": exc.__class__.__name__,
            "error_message": str(exc)[:500],
        }
    latency_ms = int((time.perf_counter() - started) * 1000)

    payload_dict = payload.model_dump() if hasattr(payload, "model_dump") else {}
    chapters = _payload_to_chapters(payload)
    # The judge wants a flat list of phrases / titles to check against
    # the expected list — we hand it the chapter titles + lesson
    # titles concatenated, which is what the ingest output actually
    # exposes to a learner.
    key_phrases: list[str] = []
    for ch in chapters:
        key_phrases.append(ch["title"])
        key_phrases.extend(ch.get("lesson_titles", []))

    return {
        "status": "ok",
        "url": item.url,
        "kind": item.kind,
        "payload": payload_dict,
        "chapters": chapters,
        "key_phrases": key_phrases,
        "actual_chapter_count": len(chapters),
        "expected_chapter_count": item.expected_chapter_count,
        "latency_ms": latency_ms,
    }


# ---------- Per-suite dispatch ----------


async def _run_one_item(suite: SuiteName, item: Any, db: AsyncSession) -> dict[str, Any]:
    """Dispatch to the right per-suite runner."""
    if suite == "tutor":
        return await _run_tutor_item(db, item)
    if suite == "authoring":
        return await _run_authoring_item(item, db)
    if suite == "ingest":
        return await _run_ingest_item(item)
    raise ValueError(f"unknown suite: {suite}")


def _item_to_dict(item: Any) -> dict[str, Any]:
    """Serialise a golden item dataclass for the judge prompt."""
    if is_dataclass(item):
        d = asdict(item)
        # Convert the OutlineSpec dataclass tree into a plain
        # ``{modules: [{title, lessons: [{title}]}]}`` dict the judge
        # prompt can serialise directly.
        if "ideal_outline" in d and isinstance(d["ideal_outline"], dict):
            d["ideal_outline"] = {
                "modules": [
                    {
                        "title": m.get("title", ""),
                        "lessons": [{"title": l.get("title", "")} for l in m.get("lessons", [])],
                    }
                    for m in d["ideal_outline"].get("modules", [])
                ]
            }
        return d
    return dict(item)


# ---------- Public entrypoint ----------


async def run_suite(
    suite: SuiteName,
    *,
    limit: int | None = None,
    out_path: Path | None = None,
    judge_provider_name: str | None = None,
    judge_model: str | None = None,
) -> Path:
    """Run a full suite, writing a JSONL report to ``out_path``.

    Returns the path written. The caller (CLI or admin API) prints
    or returns the path so the run can be inspected.
    """
    dataset = load_dataset(suite)
    if limit is not None and limit > 0:
        dataset = dataset[:limit]

    out_path = out_path or new_report_path(suite)
    log.info(
        "eval_run_starting",
        suite=suite,
        items=len(dataset),
        out_path=str(out_path),
    )

    # Discover what provider+model the judge is about to run on so
    # the summary row records it. We resolve here once rather than
    # per-item.
    judge_provider = judge_provider_name or getattr(get_provider(), "name", "unknown")
    if judge_model is None:
        from app.core.config import get_settings

        s = get_settings()
        judge_model = getattr(s, "llm_model", None) or "default"

    started_at = datetime.utcnow()
    Session = get_sessionmaker()

    rows: list[dict[str, Any]] = []
    async with Session() as db:
        for item in dataset:
            actual = await _run_one_item(suite, item, db)
            row: dict[str, Any] = {
                "id": getattr(item, "id", "unknown"),
                "suite": suite,
                "status": actual.get("status", "ok"),
                "actual": actual,
            }

            if actual.get("status") == "ok":
                # Judge the result. Errors during judging are recorded
                # on the row but never re-raised — the suite must
                # finish so the admin can see the partial picture.
                async def _metered_judge_chat(prov: Any, msgs: list[ChatMessage]) -> str:
                    return await _judge_call(prov, msgs, session=db)

                try:
                    judge_result = await judge_mod.judge_item(
                        suite,
                        item=_item_to_dict(item),
                        actual=actual,
                        chat_fn=_metered_judge_chat,
                    )
                    row["judge"] = {
                        "scores": judge_result.scores,
                        "rationale": judge_result.rationale,
                        "judge_error": judge_result.judge_error,
                    }
                except Exception as exc:
                    log.warning(
                        "eval_judge_exception",
                        suite=suite,
                        item=row["id"],
                        error=str(exc)[:200],
                    )
                    row["judge"] = {
                        "scores": {},
                        "rationale": f"judge raised: {exc.__class__.__name__}",
                        "judge_error": True,
                    }

            write_item(out_path, row)
            rows.append(row)

    finished_at = datetime.utcnow()

    # Look up the previous report (if any) to compute regression deltas.
    previous_path = latest_previous_report(suite, exclude=out_path)
    previous_summary: dict[str, Any] | None = None
    if previous_path is not None:
        _, previous_summary = read_report(previous_path)

    summary = compute_summary(
        suite=suite,
        items=rows,
        started_at=started_at,
        finished_at=finished_at,
        judge_provider=judge_provider,
        judge_model=str(judge_model),
        previous_summary=previous_summary,
    )
    summary["run_id"] = out_path.stem
    write_item(out_path, summary)

    log.info(
        "eval_run_complete",
        suite=suite,
        items=len(rows),
        mean_overall=summary.get("mean_overall"),
        out_path=str(out_path),
    )
    return out_path


__all__ = [
    "run_suite",
]
