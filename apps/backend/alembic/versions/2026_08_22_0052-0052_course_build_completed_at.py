"""courses.build_completed_at — honest build-completion marker

S3.7 hardening (Codex confirm-round P1#1/P1#2). Phase A (additive,
zero-downtime).

What it does:

``add_column courses.build_completed_at TIMESTAMPTZ NULL`` — the durable,
honest marker that a self-serve build finished. It REPLACES the fragile
">=1 module" success heuristic in ``build._is_successfully_built``: with the
shell-first build now committing per-phase (the outline phase commits BEFORE
the lesson-drafting loop, to release the parent-row write lock so a concurrent
cancel/failure-flip is never blocked), a crashed-mid-loop course HAS modules
yet is NOT a successful build. ``build_completed_at IS NOT NULL`` is set only
at the very end of a successful pipeline, so a crashed/cancelled mid-build
draft (NULL) is correctly re-buildable rather than replayed as success.

The column is orthogonal to ``status``/``visibility`` — the visibility
authorizer and ``retrieval_acl_clause`` are unaffected (a mid-build empty or
partial draft stays owner-visible with zero/partial chunks, never indexed
until publish — no leak). NULL on every existing row is exactly right: only a
fresh successful build stamps it.

Down: ``drop_column`` — additive ⇒ reversible (DR-21).

Phase: A (additive). A net-new nullable column — invisible to old pods (no
code reads ``build_completed_at`` until the S3-hardening image ships). Lands
BEFORE the gated 0043 NOT-NULL boundary (HOUSE RULES / test_migration_chain):
chain is ``… -> 0050 -> 0051 -> 0052 -> 0043`` (head, boundary LAST).

Revision ID: 0052
Revises: 0051
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0052"
# HOUSE RULES: chain BETWEEN the newest Phase-A rev (0051) and the gated 0043
# boundary. 0052 chains off 0051; 0043's down_revision is re-pointed to 0052 so
# the gated boundary stays LAST (chain: 0050 -> 0051 -> 0052 -> 0043).
down_revision: str | Sequence[str] | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PHASE = "A"


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column("build_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Backfill (Codex confirm-round): _is_successfully_built consults this
    # marker IMMEDIATELY for replay decisions — a deployment carrying
    # pre-marker successful builds would see them all as "not built"
    # (re-submits could overwrite or even flip them to build_failed on a
    # failing re-run). Stamp every course the OLD heuristic considered
    # built: non-failed, live, with >=1 module. Over-covering studio
    # courses is harmless — only brief-linked courses ever reach the
    # replay check. Idempotent (build_completed_at IS NULL guard).
    op.execute(
        sa.text(
            """
            UPDATE courses SET build_completed_at = updated_at
            WHERE build_completed_at IS NULL
              AND status != 'build_failed'
              AND deleted_at IS NULL
              AND EXISTS (SELECT 1 FROM modules m WHERE m.course_id = courses.id)
            """
        )
    )


def downgrade() -> None:
    op.drop_column("courses", "build_completed_at")
