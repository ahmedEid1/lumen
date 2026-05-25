"""Smoke test for the eval runner.

Lumen v2 Phase H2. Runs the tutor suite end-to-end against
``LLM_PROVIDER=noop`` with ``--limit 1`` and asserts the report
file is well-formed: one item row + one summary row, JSON shape
matches the report contract.

The runner depends on a seeded ``fastapi-from-zero`` course in
the database so the first dataset item ("What is FastAPI's role
in this course?") can actually run. We seed minimally inline so
the test owns its data and doesn't depend on test ordering or
the seed CLI being run first.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.evals.runner import run_suite
from app.models.course import Course, CourseStatus, Difficulty, Lesson, LessonType, Module, Subject
from app.models.user import Role


@pytest.mark.asyncio
async def test_tutor_smoke_writes_well_formed_report(
    db_session: AsyncSession,
    make_user,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Force noop on both the chat provider AND the embeddings
    # provider so the suite is deterministic + offline. The local
    # embedding provider would otherwise try to import
    # sentence_transformers and a CI without the wheel cached
    # would either hang or fail.
    monkeypatch.setenv("LLM_PROVIDER", "noop")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "noop")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    # Seed the minimum-viable course the first tutor item references.
    # The runner resolves lessons by title against the live DB, so
    # we need at least the "Welcome" lesson to exist for t-001.
    instructor = await make_user(role=Role.instructor)
    subj = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db_session.add(subj)
    await db_session.flush()

    course = Course(
        owner_id=instructor.id,
        subject_id=subj.id,
        title="FastAPI from Zero",
        slug="fastapi-from-zero",
        overview="Test seed",
        difficulty=Difficulty.beginner,
        status=CourseStatus.published,
    )
    db_session.add(course)
    await db_session.flush()
    module = Module(course_id=course.id, title="Getting started", order=0)
    db_session.add(module)
    await db_session.flush()
    db_session.add(
        Lesson(
            module_id=module.id,
            title="Welcome",
            type=LessonType.text,
            order=0,
            data={"type": "text", "body_markdown": "Welcome lesson body."},
        )
    )
    await db_session.commit()

    out_path = tmp_path / "tutor-smoke.jsonl"
    written = await run_suite(suite="tutor", limit=1, out_path=out_path)
    assert written == out_path
    assert out_path.exists()

    lines = [json.loads(l) for l in out_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    # Exactly one item row + one summary row.
    assert len(lines) == 2

    item_row, summary_row = lines[0], lines[1]
    assert item_row.get("_summary") is not True
    assert item_row["suite"] == "tutor"
    assert item_row["id"] == "t-001"
    assert "actual" in item_row
    # Status is either "ok" (course was found, retrieval may have
    # been empty → refused but still "ok") or "skipped" (course not
    # found — but we seeded one, so this branch shouldn't fire).
    assert item_row["status"] in {"ok", "skipped"}

    assert summary_row.get("_summary") is True
    assert summary_row["suite"] == "tutor"
    assert summary_row["items_total"] == 1
    # axes is a dict keyed by axis name — may be empty if the suite's
    # one item was skipped (e.g. no embeddings = empty retrieval =
    # tutor refusal → judge still runs, but the answer may produce
    # judge_error under the noop judge). The contract is just "the
    # field is present and is a dict".
    assert isinstance(summary_row.get("axes"), dict)
    assert "mean_overall" in summary_row
    assert summary_row.get("judge_provider") == "noop"
