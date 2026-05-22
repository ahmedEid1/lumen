"""pgvector extension

Rebuild Phase E0: install the pgvector extension so subsequent
migrations can declare ``vector`` columns and the embedding pipeline
can persist sentence-transformer outputs. The compose ``db`` image
must be ``pgvector/pgvector:pg17`` (or any Postgres build that bundles
pgvector); the bare ``postgres:17-alpine`` image we used before
A9-and-prior does *not* ship the extension and this migration will
fail loudly there — which is the intended fast-failure.

We intentionally do **not** run ``DROP EXTENSION vector`` on
downgrade. Other migrations downstream of this one declare
``Vector(...)`` columns; dropping the extension under live tables
would cascade-drop those columns and silently destroy embeddings.
The downgrade is a no-op — bring the extension up; never tear it
down except by manual DBA action on an empty DB.

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-07
"""

from __future__ import annotations

from typing import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # Deliberately a no-op — see module docstring.
    pass
