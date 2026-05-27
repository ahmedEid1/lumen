"""Public eval surface (L41).

`GET /api/v1/eval/public` — read-only, no auth — returns the
*promoted* eval-report summary the public `/eval` page renders.

Promotion is explicit: the operator runs
``python -m app.cli promote-eval --suite <suite> --report <id>``
which writes the report id into ``apps/backend/evals/reports/PROMOTED.json``.
Until a suite is promoted, this endpoint returns `null` for it and
the public `/eval` page stays in honest-empty state.

The summary fields exposed here are deliberately narrow — just the
axis means + judge metadata + counts. Raw per-item answers stay in
the admin-only `/admin/evals/reports/<id>` endpoint so a learner's
test data + the LLM-as-judge rationales don't accidentally ship to
the public surface.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.evals.golden import SUITES, reports_dir
from app.evals.reports import list_reports

router = APIRouter()


PROMOTED_FILE_NAME = "PROMOTED.json"


def _promoted_file() -> Path:
    return reports_dir() / PROMOTED_FILE_NAME


def get_promoted_report_ids() -> dict[str, str]:
    """Read the promotion ledger. Missing file → empty dict."""
    f = _promoted_file()
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str)}


def set_promoted(suite: str, report_id: str) -> None:
    """Mark `report_id` as the public-surfaced report for `suite`.

    Idempotent — re-promoting the same id is a no-op. Promoting a
    different id swaps the public number. The operator CLI calls
    this; no admin HTTP endpoint exposes it (intentional — promotion
    is a deliberate, deploy-cadence action, not a webapp toggle).
    """
    if suite not in SUITES:
        raise ValueError(f"suite must be one of {list(SUITES)}")
    current = get_promoted_report_ids()
    current[suite] = report_id
    out = _promoted_file()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")


def clear_promoted(suite: str) -> None:
    """Remove `suite` from the promotion ledger. The public `/eval`
    page returns to honest-empty for that suite."""
    current = get_promoted_report_ids()
    if suite in current:
        del current[suite]
        out = _promoted_file()
        out.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")


class PublicSuiteSummary(BaseModel):
    """Narrow summary fields exposed on the public `/eval` page."""

    suite: str
    mean_overall: float | None = None
    axes: dict[str, float] = Field(default_factory=dict)
    items_judged: int | None = None
    finished_at: str | None = None
    judge_provider: str | None = None
    judge_model: str | None = None
    report_id: str


class PublicEvalResponse(BaseModel):
    """Whole-page payload — one summary per suite (null when not
    promoted)."""

    suites: dict[str, PublicSuiteSummary | None]


@router.get(
    "/eval/public",
    response_model=PublicEvalResponse,
    summary="Public eval summary (latest promoted per suite)",
    tags=["public-eval"],
)
async def public_eval_summary() -> PublicEvalResponse:
    """Return the promoted summary per suite, or `null` if not
    promoted. Used by the public `/eval` page; honest-empty until
    the operator promotes a real run."""
    promoted = get_promoted_report_ids()
    out: dict[str, PublicSuiteSummary | None] = {}
    for suite in SUITES:
        report_id = promoted.get(suite)
        if not report_id:
            out[suite] = None
            continue
        # Find the matching report from list_reports — it already
        # extracts the summary fields cleanly. We don't re-parse the
        # JSONL file here; list_reports is the source of truth.
        rows: list[dict[str, Any]] = list_reports(suite=suite)
        matching = next((r for r in rows if r.get("report_id") == report_id), None)
        if matching is None:
            # Promoted-but-missing → fall back to honest-empty. An
            # operator who deleted the JSONL file without updating
            # PROMOTED.json sees /eval go back to null for that
            # suite, which is the safe degrade.
            out[suite] = None
            continue
        out[suite] = PublicSuiteSummary(
            suite=suite,
            mean_overall=matching.get("mean_overall"),
            axes=matching.get("axes", {}),
            items_judged=matching.get("items_judged"),
            finished_at=matching.get("finished_at"),
            judge_provider=matching.get("judge_provider"),
            judge_model=matching.get("judge_model"),
            report_id=report_id,
        )
    return PublicEvalResponse(suites=out)
