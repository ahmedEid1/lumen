"""moderation_events_timestamp_defaults

Gate-C live finding. Phase A (additive, zero-downtime, instant on PG17 —
``ALTER COLUMN ... SET DEFAULT`` is a catalog-only change, it does NOT rewrite
existing rows).

Why this exists: ``app/models/base.py`` ``TimestampMixin`` declares
``created_at``/``updated_at`` with ``server_default=func.now()``, so the ORM
sends NO timestamp values on INSERT — it relies on the DB default to fill them.
But 0033 created ``moderation_events`` with both columns ``NOT NULL`` and **no**
server default. A ``metadata.create_all`` test DB (which materialises the
mixin's ``server_default``) papers over the gap, so the unit suite passes; every
MIGRATION-built DB (dev / staging / prod) has the column with NO default, so the
first ``POST /share`` (which appends a moderation_events row via the ORM) 500s
with ``NotNullViolation`` on ``created_at``.

This migration aligns the migration-built schema with the ORM contract:

  ``ALTER TABLE moderation_events ALTER COLUMN created_at SET DEFAULT now()``
  ``ALTER TABLE moderation_events ALTER COLUMN updated_at SET DEFAULT now()``

Down: drop the two defaults (``DROP DEFAULT``) — back to the 0033 shape.

Phase: A (additive). Safe on any deploy; lands ahead of the 0043 NOT-NULL
boundary order-wise it is the head, but it carries no data rewrite or lock of
note (catalog-only).

Revision ID: 0045
Revises: 0044
Create Date: 2026-08-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0045"
# Chains off the new head 0043 (post-reorder chain:
# 0033 -> 0041 -> 0042 -> 0044 -> 0043 -> 0045, head).
down_revision: str | Sequence[str] | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PHASE = "A"


def upgrade() -> None:
    op.alter_column("moderation_events", "created_at", server_default=sa.text("now()"))
    op.alter_column("moderation_events", "updated_at", server_default=sa.text("now()"))


def downgrade() -> None:
    op.alter_column("moderation_events", "updated_at", server_default=None)
    op.alter_column("moderation_events", "created_at", server_default=None)
