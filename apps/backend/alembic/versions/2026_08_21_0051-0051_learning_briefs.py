"""learning_briefs + reserved Personal/Self-directed subject seed

S3.1 + S3.5 / FR-DEFINE-03 / FR-PRIV-01 / FR-DEFINE-12 / DR-22. Phase A
(additive, zero-downtime).

What it does:

1. ``create_table learning_briefs`` — the server-owned, immutable-once-finalized
   goal artifact. ``source_goal_enc`` (BYTEA) holds the field-encrypted raw goal
   (``secrets_crypto`` envelope, a key independent of the BYOK KEK — DR-22). All
   structured fields nullable / JSONB-defaulted (filled across elicitation
   turns). ``owner_id`` FK→users ``ON DELETE CASCADE`` (the brief is the owner's
   private content; self-serve deletion is anonymize-in-place per ADR-0030, so
   the cascade rarely fires). Composite index ``(owner_id, created_at)`` backs
   the owner-scoped listing + the per-window session-quota COUNT (R-M10).
2. Seed the reserved ``personal-self-directed`` Subject (S3.5 / FR-DEFINE-12) —
   the escape hatch so a self-serve build never hard-fails on the admin-only
   subject taxonomy (``authoring.subject_not_found``). ``INSERT … ON CONFLICT
   (slug) DO NOTHING`` makes it idempotent (``Subject.slug`` is unique). A fresh
   nanoid + timestamps are supplied because the table has no DB-side defaults
   for those columns.

Down: ``DELETE`` the reserved Subject only when no live course references it
(the subject FK is RESTRICT), then ``drop_table learning_briefs`` (the index
drops with the table). Additive ⇒ reversible (DR-21).

Phase: A (additive). A net-new table + an idempotent data row — invisible to
old pods (no code reads ``learning_briefs`` until the S3 image ships). Lands
BEFORE the gated 0043 NOT-NULL boundary (HOUSE RULES / test_migration_chain):
chain is ``… -> 0049 -> 0050 -> 0051 -> 0043`` (head, boundary LAST).

Revision ID: 0051
Revises: 0050
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.ids import new_id

revision: str = "0051"
# HOUSE RULES: chain BETWEEN the newest Phase-A rev (0050) and the gated 0043
# boundary. 0051 chains off 0050; 0043's down_revision is re-pointed to 0051 so
# the gated boundary stays LAST (chain: 0049 -> 0050 -> 0051 -> 0043).
down_revision: str | Sequence[str] | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PHASE = "A"

# Must match Settings.personal_subject_slug (S3.5). The reserved subject is the
# FR-DEFINE-12 escape from authoring.subject_not_found for self-serve builds.
_PERSONAL_SLUG = "personal-self-directed"
_PERSONAL_TITLE = "Personal / Self-directed"


def upgrade() -> None:
    op.create_table(
        "learning_briefs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        # Bounded assistant-turn count (R-M10 / FR-DEFINE-02).
        sa.Column("turns_used", sa.Integer(), server_default=sa.text("0"), nullable=False),
        # The only sensitive field — field-encrypted ciphertext (DR-22).
        sa.Column("source_goal_enc", sa.LargeBinary(), nullable=False),
        # Structured (non-sensitive) fields, filled across elicitation turns.
        sa.Column("goal_summary", sa.Text(), nullable=True),
        sa.Column("level", sa.String(length=20), nullable=True),
        sa.Column("prior_knowledge", sa.Text(), nullable=True),
        sa.Column("time_budget_hours", sa.Integer(), nullable=True),
        sa.Column("sessions_per_week", sa.Integer(), nullable=True),
        sa.Column(
            "desired_outcomes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "format_prefs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("suggested_subject", sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_learning_briefs_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learning_briefs")),
    )
    op.create_index(
        "ix_learning_briefs_owner_created",
        "learning_briefs",
        ["owner_id", "created_at"],
        unique=False,
    )

    # S3.5 — idempotent seed of the reserved Personal/Self-directed subject.
    # Supply a fresh nanoid + timestamps (no DB-side defaults for those cols).
    op.execute(
        sa.text(
            "INSERT INTO subjects (id, title, slug, created_at, updated_at) "
            "VALUES (:id, :title, :slug, now(), now()) "
            "ON CONFLICT (slug) DO NOTHING"
        ).bindparams(id=new_id(), title=_PERSONAL_TITLE, slug=_PERSONAL_SLUG)
    )


def downgrade() -> None:
    # Remove the reserved subject only if no live course references it (the
    # subject FK is RESTRICT — a guarded delete, never orphans a course).
    op.execute(
        sa.text(
            "DELETE FROM subjects s WHERE s.slug = :slug "
            "AND NOT EXISTS (SELECT 1 FROM courses c WHERE c.subject_id = s.id)"
        ).bindparams(slug=_PERSONAL_SLUG)
    )
    op.drop_index("ix_learning_briefs_owner_created", table_name="learning_briefs")
    op.drop_table("learning_briefs")
