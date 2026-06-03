"""course_visibility_moderation

S2.2 / ADR-0026 §"Numbered migrations" + DR-3-R2/DR-12/DR-15. Phase A
(additive, zero-downtime, reversible, flag-OFF behaviour-identical). The first
of Stream S2's migration chain (0033 -> 0041 -> 0042 -> 0043 -> 0044).

What it does, in order (each a discrete op against the LIVE prod DB):

1. ``ADD COLUMN courses.visibility VARCHAR(20) NULL`` +
   ``courses.moderation_state VARCHAR(20) NULL`` — nullable first, no default
   rewrite, instant on PG17.
2. **Batched one-way backfill** (separate autocommit txns, ``LIMIT`` loop to
   avoid a long lock on a live ``courses`` table, DR-15): a live-published
   course (``status=published AND deleted_at IS NULL``) ->
   ``(public, approved)``; everything else -> ``(private, none)``. This makes
   ``is_publicly_listed`` identical to the old ``status==published`` rule for
   every existing row (R-S8' step 1) so old-fleet readers and the new
   authorizer agree — the public catalog is unchanged, nothing delists.
3. ``CREATE TABLE moderation_events`` + its
   ``ix_moderation_events_course_id_created_at`` index.
4. **Synthetic approval events**: one ``to_state='approved'`` row per
   backfilled-approved course (``actor_id=NULL``) so R-M9's "did this course
   ever get approved with no later reject/delist?" query is well-defined.
5. ``ALTER COLUMN ... SET DEFAULT`` (private/none) then ``SET NOT NULL`` — set
   AFTER the backfill so in-flight old-fleet INSERTs (which omit the columns)
   are covered by the default and never fail.
6. ``CREATE INDEX CONCURRENTLY ix_courses_listed`` — the consolidated
   catalog/ACL index (design-spec §2.5 folds ADR-0029's ix_courses_acl into
   this by appending owner_id). Built in an autocommit block (CONCURRENTLY
   cannot run inside a transaction); DROP IF EXISTS first so a failed prior
   build (which leaves an INVALID index) is cleaned up and re-runnable.

Note: ``ix_courses_status_subject`` is deliberately KEPT (DR-15) — drop it only
in a follow-on once an EXPLAIN on prod-scale data confirms ix_courses_listed is
used by the catalog query.

Down: drop ``ix_courses_listed`` + the two columns. **Never drops
moderation_events** (R-C2/R-M9 — the audit history survives a column rollback).

Phase: A (additive). Apply with the authorizer-bearing release,
``FEATURE_PRIVATE_PUBLISH_ENABLED=false``; verify catalog unchanged (R-S8').

Revision ID: 0033
Revises: 0030
Create Date: 2026-07-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0033"
# INTEGRATION: re-point at merge. This worktree branched from the foundation
# rev 0030 (S7-pre) because S1's 0031 (role data-collapse) + 0032 (default
# flip) had not yet merged. The consolidated linear chain (DESIGN-RESOLUTIONS /
# IMPLEMENTATION-PLAN §Part 2) puts 0033 AFTER 0032 — at integration, rebase
# ``down_revision`` to "0032" and run ``test_migration_chain`` (S7.10) to
# confirm the chain is linear with no dangling/duplicate down_revisions.
down_revision: str | Sequence[str] | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DR-12 rollout phase annotation (S7.7 guard reads this).
PHASE = "A"

_LISTED_INDEX = "ix_courses_listed"
_BACKFILL_BATCH = 1000


def _backfill_visibility() -> None:
    """Batched one-way backfill in short autocommit transactions (DR-15).

    Live-published -> (public, approved); else -> (private, none). Each batch
    touches at most ``_BACKFILL_BATCH`` rows so the live ``courses`` table is
    never locked for long. Tune the batch size to the prod catalog size before
    a real run (verify ``SELECT count(*) FROM courses``).
    """
    bind = op.get_bind()

    # Approved branch: live-published rows.
    while True:
        res = bind.execute(
            sa.text(
                """
                WITH batch AS (
                    SELECT id FROM courses
                    WHERE visibility IS NULL
                      AND status = 'published'
                      AND deleted_at IS NULL
                    LIMIT :lim
                )
                UPDATE courses c
                SET visibility = 'public', moderation_state = 'approved'
                FROM batch
                WHERE c.id = batch.id
                RETURNING c.id
                """
            ),
            {"lim": _BACKFILL_BATCH},
        )
        ids = [row[0] for row in res.fetchall()]
        if not ids:
            break
        # One synthetic approval event per backfilled-approved course so the
        # R-M9 re-approval query is well-defined. ``actor_id`` NULL = system.
        bind.execute(
            sa.text(
                """
                INSERT INTO moderation_events
                    (id, course_id, actor_id, from_state, to_state, reason_code,
                     note, classifier_signal, created_at, updated_at)
                SELECT
                    substr(md5(random()::text || clock_timestamp()::text), 1, 21),
                    c.id, NULL, 'none', 'approved', NULL, NULL, NULL, now(), now()
                FROM courses c
                WHERE c.id = ANY(:ids)
                """
            ),
            {"ids": ids},
        )

    # Everything else -> (private, none); no synthetic event.
    while True:
        res = bind.execute(
            sa.text(
                """
                WITH batch AS (
                    SELECT id FROM courses WHERE visibility IS NULL LIMIT :lim
                )
                UPDATE courses c
                SET visibility = 'private', moderation_state = 'none'
                FROM batch
                WHERE c.id = batch.id
                RETURNING c.id
                """
            ),
            {"lim": _BACKFILL_BATCH},
        )
        if not res.fetchall():
            break


def upgrade() -> None:
    # 1) Additive nullable columns — instant, no rewrite, no default.
    op.add_column("courses", sa.Column("visibility", sa.String(length=20), nullable=True))
    op.add_column("courses", sa.Column("moderation_state", sa.String(length=20), nullable=True))

    # 3) moderation_events table FIRST (the backfill inserts synthetic rows).
    op.create_table(
        "moderation_events",
        sa.Column("id", sa.String(length=21), nullable=False),
        sa.Column("course_id", sa.String(length=21), nullable=False),
        sa.Column("actor_id", sa.String(length=21), nullable=True),
        sa.Column("from_state", sa.String(length=20), nullable=True),
        sa.Column("to_state", sa.String(length=20), nullable=False),
        sa.Column("reason_code", sa.String(length=40), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("classifier_signal", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_moderation_events_course_id_created_at",
        "moderation_events",
        ["course_id", "created_at"],
    )

    # 2) + 4) Batched backfill + synthetic approval events.
    _backfill_visibility()

    # 5) Defaults + NOT NULL — AFTER the backfill (old-fleet INSERTs covered).
    op.alter_column("courses", "visibility", server_default="private", nullable=False)
    op.alter_column("courses", "moderation_state", server_default="none", nullable=False)

    # 6) Consolidated catalog/ACL index, CONCURRENTLY (no write lock). DROP IF
    #    EXISTS first so a failed prior build (INVALID index) is re-runnable.
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_LISTED_INDEX}")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_LISTED_INDEX} "
            "ON courses (visibility, moderation_state, status, subject_id, owner_id) "
            "WHERE deleted_at IS NULL"
        )


def downgrade() -> None:
    # Drop the index + the two columns ONLY. moderation_events is append-only
    # audit and survives a column rollback (R-C2/R-M9) — re-up backfill needs
    # the prior approval/reject/delist history.
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_LISTED_INDEX}")
    op.drop_column("courses", "moderation_state")
    op.drop_column("courses", "visibility")
