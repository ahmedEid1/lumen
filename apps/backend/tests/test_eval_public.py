"""Public /api/v1/eval/public endpoint + promote/clear ledger (L41)."""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient


async def test_public_eval_returns_null_per_suite_when_nothing_promoted(
    client: AsyncClient, tmp_path, monkeypatch
) -> None:
    """Honest-empty: until the operator runs `promote-eval`, the
    public surface returns `null` for every suite."""
    from app.api.v1 import eval_public

    monkeypatch.setattr(eval_public, "reports_dir", lambda: tmp_path)
    r = await client.get("/api/v1/eval/public")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "suites" in body
    for suite_name, summary in body["suites"].items():
        assert summary is None, f"suite={suite_name} expected null but got {summary!r}"


async def test_public_eval_returns_promoted_summary(
    client: AsyncClient, tmp_path, monkeypatch
) -> None:
    """After promoting a real-shape report, the public endpoint
    exposes its summary axes + judge metadata."""
    from app.api.v1 import eval_public
    from app.evals import reports as reports_module

    # Write a fake report file + a PROMOTED.json marker.
    report_id = "tutor-test-1"
    report_path = tmp_path / f"{report_id}.jsonl"
    report_path.write_text(
        json.dumps({"item_id": "a", "primary": {}, "baseline": {}, "deltas": {}})
        + "\n"
        + json.dumps(
            {
                "_summary": True,
                "report_id": report_id,
                "suite": "tutor",
                "mean_overall": 4.2,
                "axes": {"grounding": 1.0, "accuracy": 0.5, "style": 0.2},
                "items_judged": 30,
                "judge_provider": "openai-compat",
                "judge_model": "llama-3.1-8b-instant",
                "finished_at": "2026-05-27T12:00:00Z",
            }
        )
        + "\n"
    )

    monkeypatch.setattr(eval_public, "reports_dir", lambda: tmp_path)
    monkeypatch.setattr(reports_module, "reports_dir", lambda: tmp_path)
    eval_public.set_promoted("tutor", report_id)

    r = await client.get("/api/v1/eval/public")
    assert r.status_code == 200, r.text
    body = r.json()
    tutor = body["suites"]["tutor"]
    assert tutor is not None
    assert tutor["mean_overall"] == 4.2
    assert tutor["axes"]["grounding"] == 1.0
    assert tutor["report_id"] == report_id
    assert tutor["judge_model"] == "llama-3.1-8b-instant"
    # Other suites stay null.
    assert body["suites"]["authoring"] is None


async def test_promoted_but_missing_report_falls_back_to_null(
    client: AsyncClient, tmp_path, monkeypatch
) -> None:
    """L41 — if PROMOTED.json names a report_id whose JSONL was
    deleted, the public endpoint silently degrades to honest-empty
    for that suite. Better than 500-ing or showing stale data."""
    from app.api.v1 import eval_public
    from app.evals import reports as reports_module

    monkeypatch.setattr(eval_public, "reports_dir", lambda: tmp_path)
    monkeypatch.setattr(reports_module, "reports_dir", lambda: tmp_path)
    eval_public.set_promoted("tutor", "tutor-nonexistent")

    r = await client.get("/api/v1/eval/public")
    assert r.status_code == 200
    assert r.json()["suites"]["tutor"] is None


def test_set_and_clear_promoted_round_trip(tmp_path, monkeypatch) -> None:
    """The ledger writes are idempotent; clear_promoted removes a
    suite without touching unrelated entries."""
    from app.api.v1 import eval_public

    monkeypatch.setattr(eval_public, "reports_dir", lambda: tmp_path)
    eval_public.set_promoted("tutor", "tutor-x")
    eval_public.set_promoted("authoring", "auth-y")
    assert eval_public.get_promoted_report_ids() == {
        "tutor": "tutor-x",
        "authoring": "auth-y",
    }
    eval_public.set_promoted("tutor", "tutor-x")  # idempotent
    assert eval_public.get_promoted_report_ids()["tutor"] == "tutor-x"
    eval_public.clear_promoted("tutor")
    assert eval_public.get_promoted_report_ids() == {"authoring": "auth-y"}


def test_set_promoted_rejects_unknown_suite(tmp_path, monkeypatch) -> None:
    from app.api.v1 import eval_public

    monkeypatch.setattr(eval_public, "reports_dir", lambda: tmp_path)
    with pytest.raises(ValueError, match="suite must be one of"):
        eval_public.set_promoted("not-a-real-suite", "x")
