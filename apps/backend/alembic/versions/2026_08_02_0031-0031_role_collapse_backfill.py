"""role_collapse_backfill

S1.10 / ADR-0025 §D7. Phase **B** — the IRREVERSIBLE data-collapse step of the
two-role rebuild. Backfills every legacy ``role`` value to the canonical
``user``:

    UPDATE users SET role='user' WHERE role IN ('student','instructor')

``users.role`` is a ``String(20)`` column (NOT a Postgres ``ENUM``), so this
is a pure data ``UPDATE`` — no ``ALTER TYPE``, no DDL lock beyond brief row
locks on ``users``. At seeded prod scale it is sub-second.

Phasing (DR-12): this revision runs **only while the fleet is in Phase A**
(the app enum still accepts all four values). It is applied by an explicit
``alembic upgrade 0031`` runbook step (``make migrate.phase`` /
``ALLOW_PHASE_MIGRATION=1``), never a blind ``make migrate`` to head — the
phase-guard (S7pre.9) refuses to cross this boundary automatically.

**IRREVERSIBLE (R-C4):** ``downgrade`` is a deliberate no-op. Once collapsed,
``user`` cannot be split back into ``student`` vs ``instructor`` — the
distinction is gone. Rollback is image-rollback to a release that accepts the
wider set, never ``alembic downgrade`` past 0031.

Idempotent: re-running is a no-op (no rows match the legacy filter on a second
pass). The applied row-count is logged for the operator.

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0031"
down_revision: str | Sequence[str] | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DR-12 rollout phase annotation (the phase-guard + S7-post chain test read
# these). Phase B is release-gated; IRREVERSIBLE marks the only no-op-down rev.
PHASE = "B"
IRREVERSIBLE = True

_BACKFILL_SQL = "UPDATE users SET role = 'user' WHERE role IN ('student', 'instructor')"


def upgrade() -> None:
    # Single statement, single txn, forward-only, idempotent. Log the rowcount
    # so the operator can confirm how many legacy rows collapsed.
    res = op.get_bind().execute(sa.text(_BACKFILL_SQL))
    # ``rowcount`` is reliable for an UPDATE on psycopg/asyncpg-sync.
    print(f"[0031] role_collapse_backfill: collapsed {res.rowcount} legacy role rows → 'user'")


def downgrade() -> None:
    # R-C4: IRREVERSIBLE. We cannot recover whether a collapsed `user` was a
    # `student` or an `instructor`. Intentionally a no-op so a `downgrade -1`
    # over the chain does not raise — but it restores nothing.
    pass
