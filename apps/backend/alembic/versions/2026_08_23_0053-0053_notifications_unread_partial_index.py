"""notifications unread partial index

Notifications feature-completeness batch. Phase A (additive, zero-downtime).

``CREATE INDEX ix_notifications_user_unread ON notifications (user_id)
WHERE read_at IS NULL`` — serves the two new ``read_at IS NULL`` predicates
this batch introduces:

* ``GET /me/notifications/unread-count`` (the badge's 60s poll — one COUNT
  instead of hydrating 50 full rows per tick), and
* ``GET /me/notifications/inbox?unread=true`` (server-side unread filter).

This is NOT a return of the full ``(user_id, read_at)`` index that 0008
deliberately dropped: that one was dropped because *no query filtered on
read_at at all*. These new endpoints do — and a partial index over unread
rows only is a fraction of the size (read rows, the vast majority at steady
state, aren't indexed) while matching the predicate exactly.

Down: ``drop_index`` — additive ⇒ reversible.

Chain note: first revision AFTER the 2.0.0 release window (0033…0043);
``_RELEASE_ANCHOR`` in ``tests/test_migration_chain.py`` moves to 0053 with
this revision. Chains off 0043 (the prior head/boundary, applied to prod in
the 2.0.0 stop-the-world deploy, c212b3c).
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053"
down_revision: str | Sequence[str] | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PHASE = "A"


def upgrade() -> None:
    op.create_index(
        "ix_notifications_user_unread",
        "notifications",
        ["user_id"],
        postgresql_where=sa.text("read_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_user_unread", table_name="notifications")
