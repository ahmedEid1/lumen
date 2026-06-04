"""clone_provenance

S4.2 / ADR-0028 §"Data model changes". Phase A (additive, zero-downtime). Adds
the 6 clone-provenance columns to ``courses`` + ``enrollments.is_self`` + the 2
clone-lineage indexes.

What it does:

1. ``ADD COLUMN`` ×6 on ``courses`` — all nullable, no default, no table rewrite
   (Postgres adds nullable metadata-only). The three FK columns
   (``origin_course_id``/``root_origin_course_id`` -> courses,
   ``origin_owner_id`` -> users) are ``ondelete="SET NULL"`` so an offline-admin
   physical purge of an origin course/owner nulls the pointer while the snapshot
   text persists (lineage survives — ADR-0028 §"Reconciliation note"). Normal
   self-serve account deletion is anonymize-in-place (ADR-0030): the pointer
   stays valid and the read-time serializer (DR-19) renders "a deleted user".
2. ``ADD COLUMN enrollments.is_self boolean NOT NULL DEFAULT false`` — instant on
   PG17 (constant default; existing rows = false, correct — no historical
   enrollment was a clone self-enroll).
3. ``CREATE INDEX CONCURRENTLY`` ×2 (``ix_courses_origin_course_id``,
   ``ix_courses_root_origin``) inside an ``autocommit_block`` with
   ``DROP INDEX IF EXISTS`` for re-runnability (the migration 0014 GIN pattern),
   so the index builds run outside the migration txn and never lock the catalog.

Down: drop the 2 indexes (CONCURRENTLY), then the 3 FKs (auto-dropped with the
columns), then all 7 columns. Additive ⇒ reversible (DR-21).

Phase: A (additive). Net-new nullable columns + an instant-default boolean +
concurrent indexes — invisible to old pods (clone code is flag-gated OFF until
the column-bearing image is fleet-confirmed), so safe on any deploy and lands
BEFORE the gated 0043 NOT-NULL boundary (HOUSE RULES / test_migration_chain).

Chain position: new Phase-A revisions chain BETWEEN the current last Phase-A
revision (0047 review_flagged_at) and the gated 0043 boundary, so the boundary
stays LAST. Chain: 0046 -> 0047 -> 0048 -> 0049 -> 0043 (head).

Revision ID: 0048
Revises: 0047
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0048"
# HOUSE RULES: chain BETWEEN 0047 and the gated 0043 boundary. 0048 chains off
# 0047; 0049 chains off 0048; 0043's down_revision is re-pointed to 0049 so the
# gated boundary stays LAST (chain: 0046 -> 0047 -> 0048 -> 0049 -> 0043).
down_revision: str | Sequence[str] | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PHASE = "A"

_ORIGIN_IDX = "ix_courses_origin_course_id"
_ROOT_IDX = "ix_courses_root_origin"


def upgrade() -> None:
    # 1) Six provenance columns — all nullable, additive, instant on PG17.
    # FK id columns are plain VARCHAR (the IdMixin PK type) — match it.
    op.add_column(
        "courses",
        sa.Column("origin_course_id", sa.String(), nullable=True),
    )
    op.add_column(
        "courses",
        sa.Column("origin_owner_id", sa.String(), nullable=True),
    )
    op.add_column(
        "courses",
        sa.Column("root_origin_course_id", sa.String(), nullable=True),
    )
    op.add_column(
        "courses",
        sa.Column("origin_title_snapshot", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "courses",
        sa.Column("origin_owner_name_snapshot", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "courses",
        sa.Column("cloned_at", sa.DateTime(timezone=True), nullable=True),
    )

    # FKs are SET NULL so a hard purge of an origin course/owner nulls the
    # pointer without blocking the purge (ADR-0028). Small additive constraints.
    op.create_foreign_key(
        op.f("fk_courses_origin_course_id_courses"),
        "courses",
        "courses",
        ["origin_course_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_courses_origin_owner_id_users"),
        "courses",
        "users",
        ["origin_owner_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_courses_root_origin_course_id_courses"),
        "courses",
        "courses",
        ["root_origin_course_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 2) enrollments.is_self — NOT NULL with a constant default (instant).
    op.add_column(
        "enrollments",
        sa.Column(
            "is_self",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # 3) Two clone-lineage indexes, built CONCURRENTLY outside the migration txn
    # (the migration 0014 GIN pattern). DROP IF EXISTS first so a failed prior
    # CONCURRENTLY build (INVALID index) is cleaned up before the rebuild.
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_ORIGIN_IDX}")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_ORIGIN_IDX} ON courses (origin_course_id)"
        )
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_ROOT_IDX}")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_ROOT_IDX} "
            "ON courses (root_origin_course_id)"
        )


def downgrade() -> None:
    # Drop the concurrent indexes first (outside the txn).
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_ORIGIN_IDX}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_ROOT_IDX}")

    op.drop_column("enrollments", "is_self")

    # FK constraints drop with their columns; name them explicitly for clarity.
    op.drop_constraint(
        op.f("fk_courses_root_origin_course_id_courses"), "courses", type_="foreignkey"
    )
    op.drop_constraint(op.f("fk_courses_origin_owner_id_users"), "courses", type_="foreignkey")
    op.drop_constraint(op.f("fk_courses_origin_course_id_courses"), "courses", type_="foreignkey")

    op.drop_column("courses", "cloned_at")
    op.drop_column("courses", "origin_owner_name_snapshot")
    op.drop_column("courses", "origin_title_snapshot")
    op.drop_column("courses", "root_origin_course_id")
    op.drop_column("courses", "origin_owner_id")
    op.drop_column("courses", "origin_course_id")
