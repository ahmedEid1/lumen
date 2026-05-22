"""MCPClient — OAuth client-credentials registration for the Lumen MCP server.

Lumen v2 Phase I1. Each row represents one third-party MCP client
(typically a learner's or instructor's Claude Desktop / Claude Code
install) that has been granted the right to call Lumen's MCP tools
on behalf of a specific Lumen user.

The OAuth dance is the standard *client-credentials* flow recommended
by the MCP authorisation spec for service-to-service callers:

1. The operator (or the user themselves via a future self-serve UI)
   mints a row here with ``make mcp-token`` — that command prints
   ``client_id`` + ``client_secret`` once, hashes the secret with
   argon2 (same scheme as ``users.password_hash``), and persists the
   row with ``owner_user_id`` set to the Lumen user the secret will
   act as.
2. The client POSTs ``client_id`` + ``client_secret`` to
   ``/oauth/token`` (mounted under the MCP HTTP transport). The
   handler verifies the secret against ``client_secret_hash`` and
   mints a short-lived JWT carrying ``sub=client_id``,
   ``lumen_user_id=<owner>``, and ``scopes=[...]``.
3. The MCP tool dispatcher (``app.mcp.principal.resolve_principal``)
   decodes that JWT, loads the ``mcp_clients`` row, joins to ``users``,
   and exposes a :class:`Principal` to the tool implementation.

The split between ``client_id`` (PK, public) and ``client_secret_hash``
(server-side only) mirrors the user / password split — the client
gets the secret once at mint time and never again; if they lose it,
they revoke + re-mint.

``scopes`` is a JSONB list of MCP tool names the client may invoke,
or the wildcard ``["*"]`` for full access. The MCP dispatcher enforces
this at tool-call time. We store the scope vocabulary on the row
itself (rather than in a separate ``mcp_client_scopes`` join table)
because (a) the cardinality is tiny — 9 tools today, plausibly 20-30
ever — and (b) it lets the OAuth token endpoint embed the scope list
in the JWT without an extra round-trip.

``revoked_at`` is a soft-delete-style tombstone — the OAuth handler
treats any row with a non-null ``revoked_at`` as inactive, but we
keep the row so the admin observability surface can still attribute
historical traffic to the (now-revoked) client. ``last_used_at`` gets
stamped on every successful token mint so the operator can identify
dormant clients to clean up.

Schema fields:

* ``id`` — 21-char nanoid; *this is the* ``client_id`` *exposed on
  the wire*. We deliberately reuse the ``IdMixin`` PK rather than
  carrying a second column, because OAuth client ids are themselves
  opaque random strings and ``new_id()``'s alphabet is URL-safe.
* ``client_secret_hash`` — argon2 string; nullable=False. The secret
  itself is never persisted.
* ``owner_user_id`` — FK → ``users.id``. The Lumen user this client
  acts as on every MCP tool call. ``ON DELETE CASCADE`` so deleting
  the user cleans up their registered clients automatically (GDPR).
* ``name`` — human-readable label ("My laptop", "Cursor IDE",
  "Personal Claude Desktop"). Optional but encouraged; lets the
  admin observability surface label sessions by something the
  operator recognises.
* ``scopes`` — JSONB list of strings. ``["*"]`` for unrestricted.
* ``revoked_at`` — tz-aware timestamp; nullable. Non-null = inactive.
* ``last_used_at`` — tz-aware timestamp; nullable. Stamped by the
  OAuth handler on every successful token mint.
* ``created_at`` — inherited from :class:`TimestampMixin`.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


# Sentinel that means "this client may call every MCP tool". Stored
# in the ``scopes`` array as a single-element list ``["*"]``. The
# dispatcher's scope check short-circuits to "allow" when it sees
# this token, which is the same shape Anthropic's own MCP clients
# use for the user-installed-this-themselves case.
WILDCARD_SCOPE = "*"


class MCPClient(IdMixin, TimestampMixin, Base):
    """One OAuth client-credentials registration for the Lumen MCP server.

    See module docstring for the full picture. The class itself is
    deliberately thin — the OAuth handler and the principal resolver
    (``app.mcp.auth`` / ``app.mcp.principal``) own the business logic.
    """

    __tablename__ = "mcp_clients"
    __table_args__ = (
        # Listing a user's MCP clients is the admin surface's primary
        # read path. Compose with ``revoked_at`` so the "active
        # clients" view stays index-only.
        Index("ix_mcp_clients_owner_revoked", "owner_user_id", "revoked_at"),
    )

    client_secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    # JSONB list of MCP tool names. ``["*"]`` for unrestricted. The
    # dispatcher's scope check uses ``WILDCARD_SCOPE`` to detect the
    # wildcard form; otherwise it walks the list for membership.
    scopes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default='["*"]'
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner: Mapped[User] = relationship("User", lazy="joined")


__all__ = ["WILDCARD_SCOPE", "MCPClient"]
