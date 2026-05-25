"""notifications.digested_at

Rebuild Phase D4: daily digest worker marker. When the digest task
emails a bundled summary it stamps each included row with
``digested_at`` so subsequent runs skip them. Nullable because the
overwhelming majority of notifications never enter the digest pipeline
(``in_app`` default, ``email_immediate`` for opted-in kinds).

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-06
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("digested_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("notifications", "digested_at")
