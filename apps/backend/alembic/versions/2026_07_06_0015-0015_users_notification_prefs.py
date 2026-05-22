"""users.notification_prefs JSONB

Rebuild Phase D4: per-kind email notification preferences. Adds a
JSONB column on ``users`` keyed by ``NotificationKind`` to record the
learner's dispatch choice per kind. Empty default ({}) preserves
today's bell-only behaviour because the resolution layer in
:mod:`app.services.notification_prefs` treats any missing key as
``"in_app"``.

Shape: ``{ "<kind>": "off" | "in_app" | "email_immediate" | "digest_daily" }``.

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-06
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "notification_prefs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "notification_prefs")
