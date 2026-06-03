"""S0.2 / PR-13 — Alembic revision chain integrity.

Asserts the migration chain is linear: every ``down_revision`` points at a
real revision, no two revisions share a ``down_revision`` (no fork), no
``revision`` is duplicated, and there is exactly one head (no dangling
tips). Run as a REQUIRED check at every wave-merge (not just the terminal
S7.10) so a stream that lands a colliding migration number is caught early.

Pure-unit: parses the migration modules off disk via Alembic's
``ScriptDirectory``; no DB required.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def script_dir() -> ScriptDirectory:
    cfg = Config(str(_BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND / "alembic"))
    return ScriptDirectory.from_config(cfg)


def test_single_head(script_dir):
    heads = script_dir.get_heads()
    assert len(heads) == 1, f"expected exactly one head, found {heads}"


def test_no_duplicate_revisions(script_dir):
    revs = [s.revision for s in script_dir.walk_revisions()]
    dupes = {r for r in revs if revs.count(r) > 1}
    assert not dupes, f"duplicate revision ids: {dupes}"


def test_no_forked_down_revisions(script_dir):
    """No two revisions may declare the same single down_revision (a fork)."""
    seen: dict[str, str] = {}
    forks: list[tuple[str, str, str]] = []
    for s in script_dir.walk_revisions():
        down = s.down_revision
        if isinstance(down, (tuple, list)):
            # Merge points legitimately have multiple parents; skip — none
            # are expected in this linear chain, but don't false-positive.
            continue
        if down is None:
            continue
        if down in seen:
            forks.append((down, seen[down], s.revision))
        else:
            seen[down] = s.revision
    assert not forks, f"forked down_revisions (same parent, two children): {forks}"


def test_chain_is_linear_and_walkable(script_dir):
    """Walking the full history touches every revision exactly once and every
    down_revision resolves to a known revision (no dangling pointer)."""
    walked = [s.revision for s in script_dir.walk_revisions()]
    all_revs = set(walked)
    assert len(walked) == len(all_revs), "a revision was visited twice (cycle/fork)"
    # Every down_revision is either None (base) or a real revision id.
    for s in script_dir.walk_revisions():
        down = s.down_revision
        if down is None or isinstance(down, (tuple, list)):
            continue
        assert down in all_revs, f"{s.revision} points at unknown down_revision {down!r}"
    # Exactly one base (down_revision is None).
    bases = [s.revision for s in script_dir.walk_revisions() if s.down_revision is None]
    assert len(bases) == 1, f"expected exactly one base revision, found {bases}"


def test_0030_is_in_chain(script_dir):
    """The S7-pre foundation migration is present and chains off 0029."""
    by_rev = {s.revision: s for s in script_dir.walk_revisions()}
    assert "0030" in by_rev
    assert by_rev["0030"].down_revision == "0029"


def test_quarantine_phase_a_precedes_notnull_phase_d_boundary(script_dir):
    """Codex P1 / Gate-C: the Phase-A quarantine column (0044) must come BEFORE
    the Phase-D NOT-NULL boundary (0043) so a ``migrate.safe``-only deploy lands
    the column the visibility SQL references instead of stopping at the gated
    0043 with quarantine code running against a missing column. Pinned linear
    order: 0041 -> 0042 -> 0044 -> 0043 -> 0045 (head)."""
    by_rev = {s.revision: s for s in script_dir.walk_revisions()}
    for rev in ("0041", "0042", "0043", "0044", "0045"):
        assert rev in by_rev, f"{rev} missing from chain"
    assert by_rev["0042"].down_revision == "0041"
    assert by_rev["0044"].down_revision == "0042"  # Phase-A quarantine before...
    assert by_rev["0043"].down_revision == "0044"  # ...the Phase-D NOT-NULL boundary
    assert by_rev["0045"].down_revision == "0043"  # 0045 is the head
    # The boundary is still 0043 (Phase D); it just moved to the chain's end.
    assert by_rev["0043"].module.PHASE == "D"
    assert by_rev["0044"].module.PHASE == "A"
    assert by_rev["0045"].module.PHASE == "A"
