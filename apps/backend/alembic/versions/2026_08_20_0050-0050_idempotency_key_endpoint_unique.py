"""idempotency_key_endpoint_unique

S4 gate (Codex-C2 / Gate-B B3). Phase A (additive — drop+recreate a unique
constraint on a brand-new, still-empty-in-prod table). Aligns the
``idempotency_keys`` unique constraint with the lookup/reserve key.

Why: the reserve-then-materialize idempotency path keys on
``(user_id, idempotency_key, endpoint)``. The original 0049 constraint was the
narrower ``(user_id, idempotency_key)`` — so the SAME opaque ``Idempotency-Key``
reused by a client across two different endpoints would collide on the narrower
pair and the second endpoint would replay the first endpoint's unrelated result.
This replaces ``uq_idem_user_key`` with ``uq_idem_user_key_endpoint`` over
``(user_id, idempotency_key, endpoint)``.

What it does: DROP CONSTRAINT uq_idem_user_key, then ADD CONSTRAINT
uq_idem_user_key_endpoint UNIQUE (user_id, idempotency_key, endpoint).

Down: reverse — drop the 3-col constraint, recreate the 2-col one.

Phase: A (additive). The table is net-new (0049) and the clone flag ships OFF, so
no live rows depend on either constraint; lands BEFORE the gated 0043 NOT-NULL
boundary (HOUSE RULES / test_migration_chain — boundary stays LAST).

Chain position: 0048 -> 0049 -> 0050 -> 0043 (head). 0043's down_revision is
re-pointed to 0050 so the gated boundary stays LAST.

Revision ID: 0050
Revises: 0049
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0050"
down_revision: str | Sequence[str] | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PHASE = "A"


def upgrade() -> None:
    op.drop_constraint("uq_idem_user_key", "idempotency_keys", type_="unique")
    op.create_unique_constraint(
        "uq_idem_user_key_endpoint",
        "idempotency_keys",
        ["user_id", "idempotency_key", "endpoint"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_idem_user_key_endpoint", "idempotency_keys", type_="unique")
    op.create_unique_constraint(
        "uq_idem_user_key",
        "idempotency_keys",
        ["user_id", "idempotency_key"],
    )
