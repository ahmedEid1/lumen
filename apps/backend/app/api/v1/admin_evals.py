"""Admin endpoints for the eval harness.

Lumen v2 Phase H2. Three read endpoints + one write:

* ``GET  /admin/evals/suites``        — what's available + item counts
* ``GET  /admin/evals/reports``       — list past runs (optionally per suite)
* ``GET  /admin/evals/reports/{id}``  — full per-item drill-down
* ``POST /admin/evals/runs``          — synchronously kick off a run

The router is **not** registered in ``app/api/router.py`` here — the
orchestrator wires it. See the H2 task body.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import RequireAdmin
from app.core.errors import NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.evals.golden import SUITES, dataset_path, load_dataset
from app.evals.reports import list_reports, read_report_by_id
from app.evals.runner import run_suite

log = get_logger(__name__)

router = APIRouter()


# ---------- Schemas ----------


class SuiteInfo(BaseModel):
    name: str
    item_count: int
    dataset_path: str


class ReportListItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    report_id: str
    suite: str
    finished_at: str | None = None
    started_at: str | None = None
    mean_overall: float | None = None
    axes: dict[str, float] = Field(default_factory=dict)
    items_total: int | None = None
    items_judged: int | None = None
    judge_provider: str | None = None
    judge_model: str | None = None


class ReportDetail(BaseModel):
    report_id: str
    summary: dict[str, Any] | None
    items: list[dict[str, Any]]


class RunRequest(BaseModel):
    suite: str = Field(min_length=1, max_length=40)
    limit: int | None = Field(default=None, ge=1, le=200)
    judge_model: str | None = Field(default=None, max_length=128)


class RunResponse(BaseModel):
    report_id: str
    suite: str
    mean_overall: float | None = None
    items_total: int


# ---------- Routes ----------


@router.get("/evals/suites", response_model=list[SuiteInfo])
async def list_suites(_: RequireAdmin) -> list[SuiteInfo]:
    """Available eval suites and their item counts.

    The count is read off the dataset file (not cached) — datasets
    are tens-of-items so the file read is cheap, and a fresh
    count means an admin who edited the dataset on disk sees the
    new size on the next refresh.
    """
    out: list[SuiteInfo] = []
    for name in SUITES:
        try:
            items = load_dataset(name)
            count = len(items)
        except FileNotFoundError:
            count = 0
        out.append(
            SuiteInfo(
                name=name,
                item_count=count,
                dataset_path=str(dataset_path(name)),
            )
        )
    return out


@router.get("/evals/reports", response_model=list[ReportListItem])
async def list_eval_reports(
    _: RequireAdmin,
    suite: str | None = Query(default=None, max_length=40),
) -> list[ReportListItem]:
    """List past run summaries, newest first.

    The summary fields are read off the trailing ``_summary`` row of
    each report file. Reports without a summary (an interrupted
    run) still show up with ``mean_overall=null`` so the admin can
    see and delete them.
    """
    if suite is not None and suite not in SUITES:
        raise ValidationAppError(
            f"suite must be one of {list(SUITES)}",
            code="evals.bad_suite",
        )
    rows = list_reports(suite=suite)
    return [ReportListItem.model_validate(r) for r in rows]


@router.get("/evals/reports/{report_id}", response_model=ReportDetail)
async def get_eval_report(report_id: str, _: RequireAdmin) -> ReportDetail:
    """Per-item drill-down for one report.

    ``report_id`` is the filename stem (e.g. ``tutor-20260522T103000Z``).
    Path traversal is prevented by ``read_report_by_id`` resolving
    relative to ``reports_dir()``; we also reject any id with a path
    separator so a curious caller can't poke at the filesystem.
    """
    if "/" in report_id or "\\" in report_id or ".." in report_id:
        raise ValidationAppError("Invalid report id", code="evals.bad_report_id")
    payload = read_report_by_id(report_id)
    if payload is None:
        raise NotFoundError("Report not found", code="evals.report_not_found")
    return ReportDetail.model_validate(payload)


@router.post(
    "/evals/runs",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def kick_off_run(payload: RunRequest, _: RequireAdmin) -> RunResponse:
    """Synchronously run a suite and return the resulting report id.

    "Synchronous" here means the endpoint blocks until the suite
    finishes — fine for the smoke subset (`limit=3`), questionable
    for a full 30-item tutor run. We accept the trade-off in v1
    because the admin can already kick off via the CLI and the
    point of the endpoint is to drive a "run smoke" button from
    the dashboard. The orchestrator can wire this into a Celery
    task later if a full run starts timing out the request.
    """
    if payload.suite not in SUITES:
        raise ValidationAppError(
            f"suite must be one of {list(SUITES)}",
            code="evals.bad_suite",
        )

    out_path = await run_suite(
        suite=payload.suite,  # type: ignore[arg-type]
        limit=payload.limit,
        judge_model=payload.judge_model,
    )

    # Re-read the summary off the file we just wrote so the response
    # carries the rolled-up score the dashboard wants to display.
    detail = read_report_by_id(out_path.stem) or {}
    summary = detail.get("summary") or {}
    return RunResponse(
        report_id=out_path.stem,
        suite=payload.suite,
        mean_overall=summary.get("mean_overall"),
        items_total=summary.get("items_total") or 0,
    )


__all__ = ["router"]
