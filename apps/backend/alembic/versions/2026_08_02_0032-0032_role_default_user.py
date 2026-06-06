"""role_default_user

S1.10 / ADR-0025 §D7. Phase **C** — flip the ``users.role`` column
``server_default`` from ``'student'`` to ``'user'`` so DB-level inserts (and
any code path that doesn't pass an explicit role) default to the canonical
role. Metadata-only on Postgres 17 (no table rewrite); ``String(20)`` column,
so no enum DDL.

Pairs with the ORM-side default flip (``models/user.py``, S1.8) — both land
in the narrowed-enum + normalization release. Reversible: downgrade restores
the old ``'student'`` default.

Phasing (DR-12): Phase C, applied via an explicit ``alembic upgrade 0032``
runbook step (``make migrate.phase``) with the narrowed-enum release — after
the Phase-B 0031 collapse has run.

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0032"
down_revision: str | Sequence[str] | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DR-12 rollout phase annotation.
PHASE = "C"


def upgrade() -> None:
    op.alter_column("users", "role", server_default="user")


def downgrade() -> None:
    op.alter_column("users", "role", server_default="student")
