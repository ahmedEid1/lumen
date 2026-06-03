"""S7pre.9 / PR-11 — migration phase-guard unit tests.

The phased migration chain (DR-12 / design-spec §2.6) tags every revision
with a rollout phase: **A** = additive (safe any deploy), **B** = irreversible
data-collapse (release-gated), **C** = metadata flip on a narrowed-enum
release, **D** = evidence-gated NOT-NULL tighten. A blind ``alembic upgrade
head`` could silently cross a phase boundary and apply the IRREVERSIBLE 0031
collapse out of band — the historical foot-gun PR-11 closes.

The guard is a pure classifier over revision metadata so it is testable
without a database (this worktree has no stack). ``make migrate`` /
``migrate.safe`` call the CLI wrapper; the integrator exercises that path
against a live Alembic chain.
"""

from __future__ import annotations

import pytest

from app.db.migration_phase_guard import (
    PhaseGatedMigrationError,
    RevisionPhase,
    classify_phase,
    is_phase_gated,
    select_safe_target,
)


class _FakeModule:
    """Stand-in for a loaded alembic revision module."""

    def __init__(self, revision: str, *, phase: str | None = None, irreversible: bool = False):
        self.revision = revision
        if phase is not None:
            self.PHASE = phase
        if irreversible:
            self.IRREVERSIBLE = True


def test_classify_phase_defaults_to_additive_when_unannotated():
    # Historical migrations (0001-0029) carry no PHASE attribute; they are
    # long-applied additive revisions and must classify as A so the guard
    # never refuses a routine `make migrate` on a legacy chain.
    mod = _FakeModule("0007")
    assert classify_phase(mod) == RevisionPhase.A


def test_classify_phase_reads_explicit_annotation():
    assert classify_phase(_FakeModule("0030", phase="A")) == RevisionPhase.A
    assert classify_phase(_FakeModule("0031", phase="B")) == RevisionPhase.B
    assert classify_phase(_FakeModule("0032", phase="C")) == RevisionPhase.C
    assert classify_phase(_FakeModule("0043", phase="D")) == RevisionPhase.D


def test_classify_phase_is_case_and_whitespace_tolerant():
    assert classify_phase(_FakeModule("x", phase=" b ")) == RevisionPhase.B


def test_is_phase_gated_only_a_is_safe():
    assert is_phase_gated(_FakeModule("0030", phase="A")) is False
    assert is_phase_gated(_FakeModule("0031", phase="B")) is True
    assert is_phase_gated(_FakeModule("0032", phase="C")) is True
    assert is_phase_gated(_FakeModule("0043", phase="D")) is True


def test_irreversible_flag_is_gated_even_if_phase_missing():
    # A revision that declares IRREVERSIBLE (0031) must be gated regardless
    # of whether someone forgot the PHASE tag — defence in depth (R-C4).
    mod = _FakeModule("0031", irreversible=True)
    assert is_phase_gated(mod) is True


def test_select_safe_target_stops_before_first_gated_rev():
    # Ordered oldest→newest pending revisions. 0033 is additive but sits
    # *after* the gated 0031/0032, so the safe target is the last additive
    # rev reachable without crossing a boundary: 0030.
    pending = [
        _FakeModule("0030", phase="A"),
        _FakeModule("0031", phase="B", irreversible=True),
        _FakeModule("0032", phase="C"),
        _FakeModule("0033", phase="A"),
    ]
    assert select_safe_target(pending) == "0030"


def test_select_safe_target_returns_head_when_all_additive():
    pending = [
        _FakeModule("0033", phase="A"),
        _FakeModule("0034", phase="A"),
        _FakeModule("0035", phase="A"),
    ]
    assert select_safe_target(pending) == "0035"


def test_select_safe_target_returns_none_when_first_pending_is_gated():
    pending = [
        _FakeModule("0031", phase="B", irreversible=True),
        _FakeModule("0032", phase="C"),
    ]
    assert select_safe_target(pending) is None


def test_select_safe_target_empty_pending_returns_none():
    assert select_safe_target([]) is None


def test_safe_run_refuses_gated_without_flag():
    pending = [_FakeModule("0031", phase="B", irreversible=True)]
    with pytest.raises(PhaseGatedMigrationError) as exc:
        select_safe_target(pending, raise_on_gated=True)
    # The error names the offending revision and the unlock flag so the
    # operator knows exactly what they're about to do.
    assert "0031" in str(exc.value)
    assert "ALLOW_PHASE_MIGRATION" in str(exc.value)
