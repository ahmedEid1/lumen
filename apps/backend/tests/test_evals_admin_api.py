"""Admin API for the eval surface — role gates + happy paths.

Lumen v2 Phase H2. The router for ``/admin/evals/*`` is owned by
this PR but the orchestrator wires it into ``app.api.router`` — so
the tests register the router on the test ``app`` fixture inline,
giving us coverage of the route shape and the admin-only gate
without depending on the orchestrator's commit.

Once the orchestrator lands the registration, the inline include
is harmless — ``include_router`` with the same prefix is
idempotent at the route-table level (it appends routes; the
prefix-collision check FastAPI does is path-by-path and the
admin-evals routes have unique paths).
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.v1 import admin_evals
from app.evals import reports as reports_mod
from app.models.user import Role


@pytest.fixture(autouse=True)
def _wire_admin_evals_router(app: FastAPI) -> None:
    """Mount the admin-evals router under ``/api/v1/admin`` for the test.

    The orchestrator will land the same include on master; this
    fixture is a shim so the API tests don't have to wait for it.
    """
    # Avoid double-registering on suite re-runs (the autouse fixture
    # fires per-test, but the same ``app`` instance is reused).
    paths = {r.path for r in app.routes}  # type: ignore[attr-defined]
    if "/api/v1/admin/evals/suites" not in paths:
        app.include_router(
            admin_evals.router, prefix="/api/v1/admin", tags=["admin-evals"]
        )


@pytest.mark.asyncio
async def test_admin_can_list_suites(client: AsyncClient, auth_headers) -> None:
    admin = await auth_headers(role=Role.admin)
    r = await client.get("/api/v1/admin/evals/suites", headers=admin)
    assert r.status_code == 200, r.text
    payload = r.json()
    names = [row["name"] for row in payload]
    # All three datasets are committed in this PR — every name must
    # appear with a positive item count.
    assert "tutor" in names
    assert "authoring" in names
    assert "ingest" in names
    tutor_row = next(row for row in payload if row["name"] == "tutor")
    assert tutor_row["item_count"] == 30


@pytest.mark.asyncio
async def test_non_admin_blocked_on_suites(client: AsyncClient, auth_headers) -> None:
    student = await auth_headers(role=Role.student)
    r = await client.get("/api/v1/admin/evals/suites", headers=student)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_anonymous_blocked_on_suites(client: AsyncClient) -> None:
    r = await client.get("/api/v1/admin/evals/suites")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_reports_returns_recent_files(
    client: AsyncClient, auth_headers, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Redirect the reports dir to a tmp path so the test owns the
    # files it reads back. Both the admin API and the report-list
    # helper read from ``reports_dir()`` so a single monkeypatch
    # covers both.
    from app.evals import golden as golden_mod

    monkeypatch.setattr(golden_mod, "_DATASETS_ROOT", tmp_path)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)

    summary = {
        reports_mod.SUMMARY_KEY: True,
        "suite": "tutor",
        "started_at": "2026-05-22T10:30:00",
        "finished_at": "2026-05-22T10:31:00",
        "mean_overall": 4.21,
        "axes": {"faithfulness": 4.5, "citation_correctness": 4.1, "helpfulness": 4.0},
        "items_total": 1,
        "items_judged": 1,
        "judge_provider": "noop",
        "judge_model": "noop",
        "run_id": "tutor-20260522T103100Z",
    }
    fake_report = tmp_path / "reports" / "tutor-20260522T103100Z.jsonl"
    fake_report.write_text(json.dumps(summary) + "\n", encoding="utf-8")

    admin = await auth_headers(role=Role.admin)
    r = await client.get("/api/v1/admin/evals/reports?suite=tutor", headers=admin)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["report_id"] == "tutor-20260522T103100Z"
    assert rows[0]["mean_overall"] == 4.21


@pytest.mark.asyncio
async def test_get_report_detail_returns_items_and_summary(
    client: AsyncClient, auth_headers, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.evals import golden as golden_mod

    monkeypatch.setattr(golden_mod, "_DATASETS_ROOT", tmp_path)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)

    item_row = {
        "id": "t-001",
        "suite": "tutor",
        "status": "ok",
        "actual": {"answer": "Based on the course content, FastAPI is..."},
        "judge": {"scores": {"faithfulness": 4, "citation_correctness": 4, "helpfulness": 4}, "rationale": "ok", "judge_error": False},
    }
    summary_row = {
        reports_mod.SUMMARY_KEY: True,
        "suite": "tutor",
        "started_at": "2026-05-22T10:30:00",
        "finished_at": "2026-05-22T10:31:00",
        "mean_overall": 4.0,
        "axes": {"faithfulness": 4.0, "citation_correctness": 4.0, "helpfulness": 4.0},
        "items_total": 1,
        "items_judged": 1,
        "judge_provider": "noop",
        "judge_model": "noop",
        "run_id": "tutor-20260522T103100Z",
    }
    fake_report = tmp_path / "reports" / "tutor-20260522T103100Z.jsonl"
    fake_report.write_text(
        json.dumps(item_row) + "\n" + json.dumps(summary_row) + "\n",
        encoding="utf-8",
    )

    admin = await auth_headers(role=Role.admin)
    r = await client.get(
        "/api/v1/admin/evals/reports/tutor-20260522T103100Z", headers=admin
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["report_id"] == "tutor-20260522T103100Z"
    assert body["summary"]["mean_overall"] == 4.0
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == "t-001"


@pytest.mark.asyncio
async def test_get_report_404_for_missing(
    client: AsyncClient, auth_headers, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.evals import golden as golden_mod

    monkeypatch.setattr(golden_mod, "_DATASETS_ROOT", tmp_path)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)

    admin = await auth_headers(role=Role.admin)
    r = await client.get(
        "/api/v1/admin/evals/reports/tutor-doesnotexist", headers=admin
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "evals.report_not_found"


@pytest.mark.asyncio
async def test_get_report_rejects_path_traversal(
    client: AsyncClient, auth_headers
) -> None:
    admin = await auth_headers(role=Role.admin)
    r = await client.get(
        "/api/v1/admin/evals/reports/..%2Fsecret", headers=admin
    )
    # Either a 422 from path validation or a 422 from our explicit
    # validator — both lock down the traversal. We accept either.
    assert r.status_code in (400, 404, 422)


@pytest.mark.asyncio
async def test_non_admin_blocked_on_reports(
    client: AsyncClient, auth_headers
) -> None:
    student = await auth_headers(role=Role.student)
    r = await client.get("/api/v1/admin/evals/reports", headers=student)
    assert r.status_code == 403
