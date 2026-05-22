"""Report writer + summary computer.

Lumen v2 Phase H2. The runner appends one JSON object per item to
``reports/<suite>-<ISO-timestamp>.jsonl`` and a final summary row
keyed by ``"_summary": true`` at the end. The admin dashboard
reads the summary directly off the last line; per-item drill-down
reads every other line.

Why JSONL over a single JSON object: the runner is happiest when
it can flush after every item — a long suite that crashes mid-run
should still leave behind a partial report rather than lose
everything. JSONL gives us append-after-flush for free.

Summary shape
=============
::

    {
      "_summary": true,
      "suite": "tutor",
      "started_at": "2026-05-22T10:30:00Z",
      "finished_at": "2026-05-22T10:34:21Z",
      "judge_model": "llama-3.3-70b-versatile",
      "judge_provider": "openai",
      "items_total": 30,
      "items_judged": 28,
      "items_skipped": 1,
      "items_judge_error": 1,
      "axes": {"faithfulness": 4.21, "citation_correctness": 3.97, ...},
      "mean_overall": 4.06,
      "regression_vs_previous": {"mean_overall": -0.12, "axes": {...}}
    }
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from app.evals.golden import reports_dir


# Marker key that identifies the summary line in a report file.
SUMMARY_KEY = "_summary"


def new_report_path(suite: str, when: datetime | None = None) -> Path:
    """Mint a timestamped report path.

    The filename pattern is ``<suite>-<YYYYMMDDTHHMMSSZ>.jsonl``.
    A colon-free, file-system-safe ISO-8601 basic form is used so
    the file lists cleanly on Windows hosts too.
    """
    ts = (when or datetime.utcnow()).strftime("%Y%m%dT%H%M%SZ")
    out_dir = reports_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{suite}-{ts}.jsonl"


def write_item(path: Path, payload: dict[str, Any]) -> None:
    """Append one item line to the report.

    Opens in append mode each call so an external reader can
    safely tail the file while the runner is still writing.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_report(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Return ``(item_rows, summary_row_or_None)`` from a report file."""
    items: list[dict[str, Any]] = []
    summary: dict[str, Any] | None = None
    if not path.exists():
        return items, summary
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get(SUMMARY_KEY) is True:
                summary = row
            else:
                items.append(row)
    return items, summary


def compute_summary(
    *,
    suite: str,
    items: Iterable[dict[str, Any]],
    started_at: datetime,
    finished_at: datetime,
    judge_provider: str,
    judge_model: str,
    previous_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Roll item-level scores into per-axis means + overall mean."""
    items_list = list(items)
    items_total = len(items_list)
    items_skipped = sum(1 for r in items_list if r.get("status") == "skipped")
    items_judge_error = sum(
        1 for r in items_list if (r.get("judge") or {}).get("judge_error") is True
    )
    items_judged = sum(
        1
        for r in items_list
        if r.get("status") == "ok"
        and not (r.get("judge") or {}).get("judge_error", False)
        and (r.get("judge") or {}).get("scores")
    )

    # Per-axis accumulator. We index by axis name so the same code
    # serves all three suites.
    bucket: dict[str, list[float]] = defaultdict(list)
    for r in items_list:
        if r.get("status") != "ok":
            continue
        judge = r.get("judge") or {}
        if judge.get("judge_error"):
            continue
        scores = judge.get("scores") or {}
        for axis, value in scores.items():
            try:
                bucket[axis].append(float(value))
            except (TypeError, ValueError):
                continue

    axes_mean: dict[str, float] = {axis: round(mean(vals), 4) for axis, vals in bucket.items() if vals}
    mean_overall = round(mean(axes_mean.values()), 4) if axes_mean else 0.0

    regression: dict[str, Any] | None = None
    if previous_summary is not None:
        prev_axes = previous_summary.get("axes") or {}
        prev_overall = previous_summary.get("mean_overall")
        axis_deltas: dict[str, float] = {}
        for axis, score in axes_mean.items():
            prev = prev_axes.get(axis)
            if isinstance(prev, (int, float)):
                axis_deltas[axis] = round(score - float(prev), 4)
        regression = {
            "mean_overall": (
                round(mean_overall - float(prev_overall), 4)
                if isinstance(prev_overall, (int, float))
                else None
            ),
            "axes": axis_deltas,
            "previous_run": previous_summary.get("run_id"),
        }

    return {
        SUMMARY_KEY: True,
        "suite": suite,
        "started_at": started_at.isoformat() + "Z" if started_at.tzinfo is None else started_at.isoformat(),
        "finished_at": finished_at.isoformat() + "Z" if finished_at.tzinfo is None else finished_at.isoformat(),
        "judge_provider": judge_provider,
        "judge_model": judge_model,
        "items_total": items_total,
        "items_judged": items_judged,
        "items_skipped": items_skipped,
        "items_judge_error": items_judge_error,
        "axes": axes_mean,
        "mean_overall": mean_overall,
        "regression_vs_previous": regression,
    }


def latest_previous_report(suite: str, exclude: Path | None = None) -> Path | None:
    """Find the most recent earlier report file for ``suite``.

    Sorts by filename, which carries the ISO timestamp basic form, so
    the lexicographic order matches the chronological order. The
    optional ``exclude`` lets the current in-progress run skip its
    own file when looking for a baseline.
    """
    out_dir = reports_dir()
    if not out_dir.exists():
        return None
    candidates = sorted(
        (p for p in out_dir.iterdir() if p.suffix == ".jsonl" and p.name.startswith(f"{suite}-")),
        reverse=True,
    )
    for p in candidates:
        if exclude is not None and p.resolve() == exclude.resolve():
            continue
        return p
    return None


def list_reports(suite: str | None = None) -> list[dict[str, Any]]:
    """Return a list of report metadata rows for the admin API.

    Each entry: ``{report_id, suite, finished_at, mean_overall,
    axes, items_judged, items_total}``. ``report_id`` is the
    filename without extension — opaque to the UI, used as the
    path component for the drill-down route.
    """
    out_dir = reports_dir()
    if not out_dir.exists():
        return []
    rows: list[dict[str, Any]] = []
    for p in sorted(out_dir.iterdir(), reverse=True):
        if p.suffix != ".jsonl":
            continue
        # Filename pattern: ``<suite>-<ISO>.jsonl`` — extract the
        # leading suite token so the listing can be filtered.
        stem = p.stem
        file_suite = stem.split("-", 1)[0]
        if suite and file_suite != suite:
            continue
        _, summary = read_report(p)
        rows.append(
            {
                "report_id": stem,
                "suite": file_suite,
                "finished_at": (summary or {}).get("finished_at"),
                "started_at": (summary or {}).get("started_at"),
                "mean_overall": (summary or {}).get("mean_overall"),
                "axes": (summary or {}).get("axes") or {},
                "items_total": (summary or {}).get("items_total"),
                "items_judged": (summary or {}).get("items_judged"),
                "judge_provider": (summary or {}).get("judge_provider"),
                "judge_model": (summary or {}).get("judge_model"),
            }
        )
    return rows


def read_report_by_id(report_id: str) -> dict[str, Any] | None:
    """Resolve a ``report_id`` (= filename stem) to its full contents."""
    path = reports_dir() / f"{report_id}.jsonl"
    if not path.exists():
        return None
    items, summary = read_report(path)
    return {
        "report_id": report_id,
        "summary": summary,
        "items": items,
    }


__all__ = [
    "SUMMARY_KEY",
    "compute_summary",
    "latest_previous_report",
    "list_reports",
    "new_report_path",
    "read_report",
    "read_report_by_id",
    "write_item",
]
