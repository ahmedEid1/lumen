"""Phase-guard for the release-gated Alembic chain (S7pre.9 / PR-11).

The two-role rebuild introduced a *phased* migration chain (DR-12 /
design-spec §2.6). Each revision declares a rollout ``PHASE``:

* **A** — additive, zero-downtime, safe to apply on *any* deploy.
* **B** — irreversible data-collapse (e.g. 0031 ``role_collapse_backfill``),
  release-gated; must only run while the fleet already tolerates the wider
  data (no-op downgrade, R-C4).
* **C** — metadata flip on the narrowed-enum release (e.g. 0032
  ``role_default_user``).
* **D** — evidence-gated NOT-NULL tighten (e.g. 0043).

A blind ``alembic upgrade head`` would happily march across a phase
boundary and apply the IRREVERSIBLE 0031 out of band — the historical
foot-gun. This module is the guard:

* ``classify_phase`` / ``is_phase_gated`` are **pure classifiers** over a
  loaded revision module's ``PHASE`` / ``IRREVERSIBLE`` attributes — fully
  unit-testable with no database.
* ``select_safe_target`` walks an ordered list of *pending* revisions and
  returns the newest revision reachable without crossing a phase boundary
  (or raises :class:`PhaseGatedMigrationError` in strict mode).
* ``main`` is the CLI the ``Makefile`` calls — it builds the pending list
  from the live Alembic ``ScriptDirectory`` + DB head and either runs the
  safe upgrade or, with ``ALLOW_PHASE_MIGRATION=1`` (``migrate.phase``),
  runs all the way to head.

The split keeps the policy testable in a worktree that has no stack: the
classifier + target-selection logic carry the correctness load; the thin
CLI wiring is exercised by the integrator against a real chain.
"""

from __future__ import annotations

import enum
import os
import sys
from collections.abc import Iterable, Sequence
from typing import Any


class RevisionPhase(enum.StrEnum):
    """Rollout phase of a single migration (DR-12)."""

    A = "A"  # additive — safe any deploy
    B = "B"  # irreversible data-collapse — release-gated
    C = "C"  # metadata flip — narrowed-enum release
    D = "D"  # NOT-NULL tighten — evidence-gated


#: Phases that must NOT be crossed by a routine ``make migrate``. Only the
#: additive phase A is auto-applied; everything else needs the explicit
#: ``ALLOW_PHASE_MIGRATION=1`` operator acknowledgement.
GATED_PHASES: frozenset[RevisionPhase] = frozenset(
    {RevisionPhase.B, RevisionPhase.C, RevisionPhase.D}
)

#: The environment flag that unlocks ``migrate.phase`` (one explicit operator
#: acknowledgement per phased step, encoded in the deploy runbook).
ALLOW_FLAG = "ALLOW_PHASE_MIGRATION"


class PhaseGatedMigrationError(RuntimeError):
    """Raised when a phase-gated revision would be applied without the flag."""


def classify_phase(module: Any) -> RevisionPhase:
    """Return the rollout phase declared by a revision module.

    Unannotated revisions (the historical 0001-0029 chain) default to
    :attr:`RevisionPhase.A` — they are long-applied additive migrations and
    must never trip the guard on a routine upgrade.
    """
    raw = getattr(module, "PHASE", None)
    if raw is None:
        return RevisionPhase.A
    text = str(raw).strip().upper()
    try:
        return RevisionPhase(text)
    except ValueError:
        # Unknown annotation — treat conservatively as gated by reporting the
        # most restrictive class so a typo never silently downgrades to A.
        return RevisionPhase.D


def is_phase_gated(module: Any) -> bool:
    """True if applying this revision must be operator-acknowledged.

    A revision is gated when its phase is B/C/D **or** it explicitly declares
    ``IRREVERSIBLE = True`` (defence-in-depth for 0031 even if its PHASE tag
    were ever dropped — R-C4).
    """
    if bool(getattr(module, "IRREVERSIBLE", False)):
        return True
    return classify_phase(module) in GATED_PHASES


def select_safe_target(
    pending: Sequence[Any] | Iterable[Any],
    *,
    raise_on_gated: bool = False,
) -> str | None:
    """Pick the newest revision reachable without crossing a phase boundary.

    ``pending`` is the ordered (oldest→newest) list of revisions not yet
    applied to the target database. Returns the revision id of the last
    additive revision before the first gated one, or ``None`` when the very
    first pending revision is already gated (nothing safe to apply) or there
    is nothing pending.

    With ``raise_on_gated=True`` (the ``migrate.safe`` posture when a gated
    rev blocks progress) a :class:`PhaseGatedMigrationError` is raised naming
    the offending revision and the unlock flag instead of returning ``None``.
    """
    pending_list = list(pending)
    safe: str | None = None
    for module in pending_list:
        if is_phase_gated(module):
            if raise_on_gated:
                rev = getattr(module, "revision", "<unknown>")
                phase = classify_phase(module).value
                raise PhaseGatedMigrationError(
                    f"Migration {rev} is phase-gated (phase {phase}/IRREVERSIBLE) and "
                    f"will not be applied by `make migrate`/`migrate.safe`. "
                    f"Apply it explicitly with `make migrate.phase` "
                    f"(requires {ALLOW_FLAG}=1) per the deploy runbook."
                )
            break
        safe = getattr(module, "revision", None)
    return safe


def _pending_modules(config: Any, *, from_rev: str | None) -> list[Any]:  # pragma: no cover
    """Load the ordered pending revision modules from Alembic.

    Lives behind the pure classifiers so the unit tests never need Alembic
    or a database. The integrator's DB-backed harness exercises this path.
    """
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    # ``iterate_revisions(head, from_rev)`` yields newest→oldest; reverse for
    # oldest→newest so ``select_safe_target`` walks in application order.
    revs = list(script.iterate_revisions(head, from_rev))
    revs.reverse()
    return [r.module for r in revs]


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover — CLI wiring
    """Entry point for ``python -m app.db.migration_phase_guard``.

    Subcommands:

    * ``safe`` — upgrade only as far as the additive phase allows; if a
      phase-gated rev blocks further progress, apply what is safe and exit
      non-zero with an explanatory message (so ``make migrate`` surfaces the
      boundary instead of silently crossing it).
    * ``phase`` — upgrade to ``head``, but **only** when ``ALLOW_PHASE_MIGRATION=1``
      is set; otherwise refuse.
    """
    from sqlalchemy import create_engine

    from alembic import command
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from app.core.config import get_settings

    args = list(sys.argv[1:] if argv is None else argv)
    mode = args[0] if args else "safe"

    config = Config("alembic.ini")

    # Alembic is sync; reuse the same sync URL env.py points at.
    engine = create_engine(get_settings().database_url_sync)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        current = ctx.get_current_revision()

    if mode == "phase":
        if os.environ.get(ALLOW_FLAG) != "1":
            sys.stderr.write(
                f"refusing `migrate.phase`: set {ALLOW_FLAG}=1 to apply phase-gated "
                f"(IRREVERSIBLE/B/C/D) revisions — see the deploy runbook.\n"
            )
            return 2
        command.upgrade(config, "head")
        return 0

    # mode == "safe" (default, what `make migrate` calls)
    pending = _pending_modules(config, from_rev=current)
    if not pending:
        return 0
    try:
        target = select_safe_target(pending, raise_on_gated=True)
    except PhaseGatedMigrationError as exc:
        # Apply everything safe up to the boundary first, then report.
        safe_target = select_safe_target(pending)
        if safe_target is not None:
            command.upgrade(config, safe_target)
        sys.stderr.write(str(exc) + "\n")
        return 3
    if target is not None:
        command.upgrade(config, target)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
