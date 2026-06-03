"""account_lifecycle_users_deleted_at

S7-pre.8 / ADR-0030 §"Data model changes". Phase A (additive, zero-downtime,
reversible). Adds the ``users.deleted_at`` tombstone marker that
distinguishes a *deleted* (anonymize-in-place) account from a *suspended*
one — both share ``is_active=False``; ``deleted_at IS NOT NULL`` is the
single discriminator.

What it does:

* ``ADD COLUMN users.deleted_at TIMESTAMPTZ NULL`` — metadata-only on
  Postgres 17 (no table rewrite, no default).
* ``CREATE INDEX CONCURRENTLY ix_users_deleted_at ... WHERE deleted_at IS
  NOT NULL`` — a small partial index for the admin "deleted accounts" view
  that never takes an ACCESS EXCLUSIVE lock on the live ``users`` table.
  Built inside an ``autocommit_block`` because CONCURRENTLY cannot run in a
  transaction.
* **Idempotent legacy backfill:** the OLD ``delete_me`` wrote tombstone
  emails ``deleted-{id}@lumen.invalid`` + ``is_active=False`` but had no
  ``deleted_at`` column, so those rows would read as "suspended" (and thus
  reinstateable) under the new discriminator. Backfill
  ``deleted_at = updated_at`` for exactly those rows so historical
  deletions correctly read as tombstones. Touches only already-anonymized
  rows; safe to re-run (the ``deleted_at IS NULL`` guard makes it a no-op
  on a second pass).

Down: drop the index (CONCURRENTLY) then the column — reversible; no PII is
destroyed (the scrub itself lives in already-deployed columns).

Phase: A (additive). Apply with any deploy; confirm API + worker boot.

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0030"
down_revision: str | Sequence[str] | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DR-12 rollout phase annotation (S7.7 guard reads this).
PHASE = "A"

_INDEX = "ix_users_deleted_at"

_BACKFILL_SQL = """
UPDATE users
SET deleted_at = updated_at
WHERE email LIKE 'deleted-%@lumen.invalid'
  AND is_active = false
  AND deleted_at IS NULL
"""


def upgrade() -> None:
    # 1) Additive nullable column — instant, no rewrite, no default.
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    # 2) Idempotent legacy-tombstone backfill (runs in the migration txn).
    op.execute(_BACKFILL_SQL)

    # 3) Partial index, built CONCURRENTLY outside the transaction so the
    #    live ``users`` table is never ACCESS-EXCLUSIVE locked. DROP IF
    #    EXISTS first so a failed prior CONCURRENTLY build (which leaves an
    #    INVALID index) is cleaned up and the build is re-runnable.
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} "
            "ON users (deleted_at) WHERE deleted_at IS NOT NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
    op.drop_column("users", "deleted_at")
