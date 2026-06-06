"""tutor_turn_credential_id — carry the BYOK foreground-locus token to the worker.

S5.5 / ADR-0027 §"Data model changes". Phase A (additive, zero-downtime,
reversible). Adds ``tutor_turn_jobs.credential_id VARCHAR(21) NULL`` + an FK
to ``user_llm_credentials.id`` ON DELETE SET NULL.

The streaming tutor runs in a Celery worker; the worker holds ``turn.user_id``
and now ``turn.credential_id`` (the foreground-resolved credential id), so it
can re-resolve + decrypt the user's key INSIDE ``byok.build_provider``
(FR-BYOK-26: the Celery payload never carries the raw key). SET NULL (not
CASCADE) so a removed credential never orphans turn/audit history — the turn
row survives with ``credential_id IS NULL``.

Depends on 0038 (the FK target ``user_llm_credentials`` must exist first).

Phase: A (additive). Apply with any deploy, after 0038.

down_revision: "0039" (S5 internal chain).

Revision ID: 0040
Revises: 0039
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0040"
down_revision: str | Sequence[str] | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PHASE = "A"

_FK = "fk_tutor_turn_jobs_credential_id"


def upgrade() -> None:
    op.add_column(
        "tutor_turn_jobs",
        sa.Column("credential_id", sa.String(length=21), nullable=True),
    )
    op.create_foreign_key(
        _FK,
        "tutor_turn_jobs",
        "user_llm_credentials",
        ["credential_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(_FK, "tutor_turn_jobs", type_="foreignkey")
    op.drop_column("tutor_turn_jobs", "credential_id")
