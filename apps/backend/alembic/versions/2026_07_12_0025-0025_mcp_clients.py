"""mcp_clients — OAuth client-credentials registry for the Lumen MCP server.

Lumen v2 Phase I1. One row per third-party MCP client (typically a
user's Claude Desktop / Claude Code install) that has been granted
the right to call Lumen's MCP tools on behalf of a specific Lumen
user. See ``app/models/mcp_client.py`` for the full design notes —
this migration is the schema-only counterpart.

The model uses ``IdMixin``'s ``id`` column as the OAuth ``client_id``
on the wire, so no extra column for that. The secret is argon2-hashed
(same scheme as ``users.password_hash``) and never persisted in
clear text.

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-12

Note: this migration came in alongside I5 (learning_paths, 0024).
We sit on top of I5 in the linear history; the two tables don't
share columns or constraints so the ordering only matters for
``alembic upgrade head`` to apply both deterministically.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_clients",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("client_secret_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "owner_user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False, server_default=""),
        # JSONB list of MCP tool names the client may invoke, or the
        # wildcard ``["*"]`` for unrestricted. The dispatcher enforces
        # the scope check at tool-call time.
        sa.Column(
            "scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default='["*"]',
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # Listing a user's MCP clients is the admin surface's primary
    # read path. Compose with ``revoked_at`` so the "active clients"
    # view stays index-only.
    op.create_index(
        "ix_mcp_clients_owner_revoked",
        "mcp_clients",
        ["owner_user_id", "revoked_at"],
    )
    # ``created_at`` index mirrors what ``TimestampMixin`` declares
    # on every other table (the mixin marks ``created_at`` with
    # ``index=True``). Mirrors the index Alembic autogenerate would
    # have produced from the ORM.
    op.create_index(
        "ix_mcp_clients_created_at",
        "mcp_clients",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_mcp_clients_created_at", table_name="mcp_clients")
    op.drop_index("ix_mcp_clients_owner_revoked", table_name="mcp_clients")
    op.drop_table("mcp_clients")
