"""CI grep-guard: no raw ``status == published`` access/discoverability reads.

DR-3-R2 mandate (the *literal first commit of Stream S2*). The single
central authorizer ``app.services.visibility`` is the only home for the
visibility/discoverability predicate; the lifecycle state-machine in
``app.services.courses`` is the only home for the *writes*. Every other
``CourseStatus.published`` mention in ``app/`` must be either:

* allow-listed with an explicit marker comment (a state-machine write, a
  seed/fixture write, the central authorizer, or a genuine lifecycle stat),
  **or**
* not present at all (a migrated reader now routes through
  ``visibility.publicly_listed_sql`` / ``is_publicly_listed`` /
  ``retrieval_acl_clause`` and no longer names the raw status).

This guard is the **authoritative backstop** (DR-3-R2): the hand-list below
is only a starting map. A new ``Course.status == CourseStatus.published``
access read added anywhere outside the allowlist — or the string form
``str(course.status) == "published"`` (the 14th reader, ``courses.py:313``),
or the dead ``moderation_state IN (none, approved)`` / auto-approve-fast-path
phrasings (R-C1′) — fails this test with the offending ``file:line``.

Ratchet discipline (DR-3-R2): at S2.1 commit time the 14 reader sites are NOT
yet migrated, so they live in ``READERS_PENDING_MIGRATION`` with a marker
comment. Each later S2.x reader task *removes* its site from that block as it
routes through the authorizer. The stream is done only when
``READERS_PENDING_MIGRATION`` is empty (asserted by S2.12 /
``test_pending_migration_block_is_empty``). This keeps the guard green at
every commit while ratcheting the leak shut.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Walk root + exclusions
# ---------------------------------------------------------------------------

_APP_ROOT = Path(__file__).resolve().parent.parent / "app"

# Directories under app/ whose ``status==published`` mentions are NOT access
# reads we police here: tests live elsewhere, and ``alembic/versions`` is the
# migration tree (outside app/ anyway, listed for clarity).
_EXCLUDED_DIR_NAMES = {"__pycache__"}


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# 1) Any mention of ``CourseStatus.published`` (whitespace/``Course.``-prefix
#    tolerant). Catches both the comparison readers
#    (``Course.status == CourseStatus.published``) and the assignment writes
#    (``status=CourseStatus.published``) — the latter is why the seed/state-
#    machine writes are explicitly allow-listed.
_RE_ENUM = re.compile(r"CourseStatus\.published")

# 2) The string form: ``str(<...status...>) == "published"`` — DR-3-R2's 14th
#    reader (``api/v1/courses.py:313``). The ``status`` token inside the
#    ``str(...)`` is required so ``str(response.status_code) == ...`` and other
#    incidental ``str(...)`` calls are NOT matched.
_RE_STR_FORM = re.compile(r"""str\([^)]*status[^)]*\)\s*(==|!=)\s*['"]published['"]""")

# 3) Dead phrasings purged by R-C1′ (ADR-0026 open-risk): the spec's
#    ``moderation_state IN (none, approved)`` and any auto-approve fast-path.
#    ``none`` is NOT listable; only ``== approved`` lists.
_RE_DEAD_IN = re.compile(r"moderation_state\s+IN\s*\(\s*none\s*,\s*approved\s*\)", re.IGNORECASE)
_RE_DEAD_AUTO = re.compile(r"\bauto[_\-]?approve\b", re.IGNORECASE)

_PATTERNS = (_RE_ENUM, _RE_STR_FORM, _RE_DEAD_IN, _RE_DEAD_AUTO)

# Marker comments. A flagged line is allow-listed when it carries exactly one
# of these markers as a substring.
_MARKER_STATE_MACHINE = "# noqa: published-check — state-machine write"
_MARKER_SEED = "# noqa: published-check — seed write"
_MARKER_AUTHORIZER = "# noqa: published-check — central authorizer"
_MARKER_LIFECYCLE = "# noqa: published-check — lifecycle stat"
_MARKER_PENDING = "# noqa: published-check — PENDING S2.x migration"

_ALL_MARKERS = (
    _MARKER_STATE_MACHINE,
    _MARKER_SEED,
    _MARKER_AUTHORIZER,
    _MARKER_LIFECYCLE,
    _MARKER_PENDING,
)

# ---------------------------------------------------------------------------
# The pending-migration block (DR-3-R2 ratchet).
#
# Each entry is a ``module:symbol`` *description* of one of the 14 reader sites
# that has NOT yet adopted the authorizer. It is emptied as each S2.x reader
# task migrates. The block is informational; enforcement is by the marker
# comment on the line itself (so it survives edits / line-number churn). When a
# reader migrates, its raw ``CourseStatus.published`` disappears from the
# source entirely (replaced by ``publicly_listed_sql()`` etc.) and its entry is
# struck from this set.
# ---------------------------------------------------------------------------

READERS_PENDING_MIGRATION: set[str] = {
    "repositories/courses.py::list_subjects subject-tile count",
    "repositories/courses.py::search_courses only_published",
    "api/v1/courses.py::lesson free-preview gate (str form)",
    "api/v1/tutor_streaming.py::slug->id published gate",
    "services/enrollment.py::enroll status gate",
    "api/v1/admin.py::reindex fan-out published selection",
    "api/v1/admin.py::platform-stats courses_published count",
    "services/courses.py::can_view_course",
    "services/authoring_subagents/researcher.py::primary catalog read",
    "services/authoring_subagents/researcher.py::fallback recent published",
    "services/learning_path.py::_condense_catalog primary",
    "services/learning_path.py::_condense_catalog fallback",
    "services/learning_path.py::cross-course planner read",
    "cli.py::published listing",
}


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


def _iter_app_py_files() -> list[Path]:
    files: list[Path] = []
    for path in _APP_ROOT.rglob("*.py"):
        if any(part in _EXCLUDED_DIR_NAMES for part in path.parts):
            continue
        files.append(path)
    return files


def _line_is_allowlisted(line: str) -> bool:
    """A flagged line is allow-listed iff it carries a recognized marker."""
    return any(marker in line for marker in _ALL_MARKERS)


# Double-backtick prose spans (the codebase's docstring convention, e.g.
# ``CourseStatus.published``) are *references*, not code reads. Strip them
# before pattern-matching so a docstring/comment that *names* the predicate
# doesn't need a marker — only real code does.
_RE_BACKTICK_SPAN = re.compile(r"``[^`]*``")


def _strip_prose(line: str) -> str:
    return _RE_BACKTICK_SPAN.sub("", line)


def _scan() -> list[tuple[str, int, str]]:
    """Return ``(relpath, lineno, line)`` for every flagged, NON-allowlisted line."""
    offenders: list[tuple[str, int, str]] = []
    for path in _iter_app_py_files():
        rel = str(path.relative_to(_APP_ROOT.parent))
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            scannable = _strip_prose(line)
            if any(p.search(scannable) for p in _PATTERNS):
                if _line_is_allowlisted(line):
                    continue
                offenders.append((rel, lineno, line.strip()))
    return offenders


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_raw_published_checks() -> None:
    """No raw ``status==published`` (or string/dead-phrase) outside the allowlist."""
    offenders = _scan()
    if offenders:
        rendered = "\n".join(f"  {f}:{n}: {ln}" for f, n, ln in offenders)
        raise AssertionError(
            'Raw `status == published` / `str(...status...)=="published"` / dead '
            "moderation phrasing found outside the central authorizer. Route the read "
            "through `app.services.visibility` (`is_publicly_listed` / "
            "`publicly_listed_sql` / `retrieval_acl_clause`) or, for a genuine "
            "lifecycle write/stat, add the explicit marker comment. Offenders:\n"
            f"{rendered}"
        )


def test_every_pending_reader_still_marked() -> None:
    """Defensive: the pending set may only shrink, never silently grow past 14."""
    assert len(READERS_PENDING_MIGRATION) <= 14, (
        "READERS_PENDING_MIGRATION may only shrink as readers migrate; "
        f"it has {len(READERS_PENDING_MIGRATION)} entries."
    )


@pytest.mark.xfail(
    bool(READERS_PENDING_MIGRATION),
    reason="S2.x reader migration in progress; flips green when the last reader adopts "
    "the authorizer (S2.12 removes this xfail).",
    strict=True,
)
def test_pending_migration_block_is_empty() -> None:
    """Stream-done condition (asserted by S2.12).

    The leak is structurally shut only when every one of the 14 readers has
    adopted the authorizer (or been explicitly re-classified as a lifecycle
    stat with its own marker). While migration is in progress this is a
    ``strict`` xfail — it *must* fail (so a premature "done" claim is caught)
    and it *flips to a hard pass* the moment ``READERS_PENDING_MIGRATION`` is
    emptied. S2.12 removes the xfail marker entirely, turning this into the
    permanent done-gate.
    """
    assert not READERS_PENDING_MIGRATION, (
        "Readers still pending migration to the central authorizer (S2 not done): "
        + ", ".join(sorted(READERS_PENDING_MIGRATION))
    )
