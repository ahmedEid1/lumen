"""Golden-dataset loaders + typed item shapes.

Lumen v2 Phase H2. The three suites (`tutor`, `authoring`, `ingest`)
each have their own JSONL dataset under ``apps/backend/evals/<suite>/``.
This module defines the on-disk schema for each suite, exposes
typed dataclasses the runner consumes, and provides a single
``load_dataset(suite)`` entrypoint that returns a list of items.

The shapes are intentionally narrow — anything the runner needs is
typed; anything the judge needs is typed; everything else stays in
JSONL where a researcher can edit it by hand without a migration.

JSONL was picked over JSON-array for one reason: a malformed line
fails *that line* and not the whole suite. Researchers iterate on
these files; making the file robust to in-progress edits matters
more than gaining ``json.load`` ergonomics.

A note on lesson identifiers in the tutor dataset
=================================================
Lesson primary keys in Lumen are 21-char nanoid strings minted at
INSERT time (see ``app.db.base.IdMixin``). That means a lesson id
is not stable across seed runs and cannot be embedded in a static
golden dataset by hand. We resolve this by using **lesson titles**
in the ``must_cite_lessons`` field — titles ARE stable across seed
runs because they live verbatim in the seed source. The runner
looks each title up against the live DB at run time and translates
to the real lesson id before invoking the tutor. If a title can't
be resolved (because the course wasn't seeded), the item is
skipped with ``status="skipped_course_missing"`` so the report
still has a row but the judge isn't invoked on a vacuous answer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# Suite identifiers — also used as directory names under ``evals/``
# and as the ``suite`` query parameter on the admin API.
SuiteName = Literal["tutor", "authoring", "ingest"]
SUITES: tuple[SuiteName, ...] = ("tutor", "authoring", "ingest")

# Resolve the ``apps/backend/evals/`` root relative to this file so the
# loader works regardless of cwd. ``app/evals/golden.py`` →
# ``app/`` → ``apps/backend/`` → ``apps/backend/evals``.
_DATASETS_ROOT = Path(__file__).resolve().parent.parent.parent / "evals"


@dataclass(frozen=True, slots=True)
class TutorItem:
    """One question against one seed course.

    ``must_cite_lessons`` carries lesson **titles** (not ids — see the
    module docstring). The runner resolves titles to ids per-run.
    """

    id: str
    course_slug: str
    question: str
    ideal_answer: str
    must_cite_lessons: list[str]


@dataclass(frozen=True, slots=True)
class OutlineLessonSpec:
    title: str


@dataclass(frozen=True, slots=True)
class OutlineModuleSpec:
    title: str
    lessons: list[OutlineLessonSpec]


@dataclass(frozen=True, slots=True)
class OutlineSpec:
    modules: list[OutlineModuleSpec]


@dataclass(frozen=True, slots=True)
class AuthoringItem:
    """One brief + the ideal outline the AI should produce."""

    id: str
    brief: str
    ideal_outline: OutlineSpec


@dataclass(frozen=True, slots=True)
class IngestItem:
    """One URL + the chapter / key-phrase expectations."""

    id: str
    url: str
    kind: Literal["youtube", "notion", "google_docs"]
    expected_chapter_count: int
    expected_key_phrases: list[str] = field(default_factory=list)


GoldenItem = TutorItem | AuthoringItem | IngestItem


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    """Yield parsed lines from a JSONL file.

    Comment lines (leading ``#``) and blank lines are skipped so a
    researcher can leave breadcrumb annotations in the dataset
    without breaking the loader.
    """
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                out.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path.name}:{lineno}: invalid JSON — {exc.msg}"
                ) from exc
    return out


def _coerce_outline(payload: dict[str, Any]) -> OutlineSpec:
    modules_raw = payload.get("modules") or []
    modules: list[OutlineModuleSpec] = []
    for m in modules_raw:
        lessons = [
            OutlineLessonSpec(title=str(l.get("title", "")))
            for l in (m.get("lessons") or [])
        ]
        modules.append(OutlineModuleSpec(title=str(m.get("title", "")), lessons=lessons))
    return OutlineSpec(modules=modules)


def _dataset_path(suite: SuiteName) -> Path:
    return _DATASETS_ROOT / suite / "dataset.jsonl"


def load_dataset(suite: SuiteName) -> list[GoldenItem]:
    """Load and validate a suite dataset.

    The loader is intentionally tolerant on optional fields — a
    dataset row with no ``expected_key_phrases`` is fine — but
    strict on the type-discriminator and the suite-specific
    required fields.
    """
    path = _dataset_path(suite)
    if not path.exists():
        raise FileNotFoundError(f"dataset not found: {path}")

    rows = _iter_jsonl(path)
    out: list[GoldenItem] = []
    for r in rows:
        if suite == "tutor":
            out.append(
                TutorItem(
                    id=str(r["id"]),
                    course_slug=str(r["course_slug"]),
                    question=str(r["question"]),
                    ideal_answer=str(r["ideal_answer"]),
                    must_cite_lessons=list(r.get("must_cite_lessons") or []),
                )
            )
        elif suite == "authoring":
            out.append(
                AuthoringItem(
                    id=str(r["id"]),
                    brief=str(r["brief"]),
                    ideal_outline=_coerce_outline(r.get("ideal_outline") or {}),
                )
            )
        elif suite == "ingest":
            out.append(
                IngestItem(
                    id=str(r["id"]),
                    url=str(r["url"]),
                    kind=r["kind"],
                    expected_chapter_count=int(r["expected_chapter_count"]),
                    expected_key_phrases=list(r.get("expected_key_phrases") or []),
                )
            )
        else:  # pragma: no cover — Literal-typed, but defensive.
            raise ValueError(f"unknown suite: {suite}")
    return out


def dataset_path(suite: SuiteName) -> Path:
    """Public accessor — useful for the admin API's `count` rollup."""
    return _dataset_path(suite)


def reports_dir() -> Path:
    """Where the runner writes report JSONL files."""
    return _DATASETS_ROOT / "reports"


__all__ = [
    "SUITES",
    "AuthoringItem",
    "GoldenItem",
    "IngestItem",
    "OutlineLessonSpec",
    "OutlineModuleSpec",
    "OutlineSpec",
    "SuiteName",
    "TutorItem",
    "dataset_path",
    "load_dataset",
    "reports_dir",
]
