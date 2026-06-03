"""Principal — the authenticated identity behind an MCP tool call.

Lumen v2 Phase I1. The MCP tool implementations in :mod:`app.mcp.tools`
never see a raw FastAPI ``CurrentUser`` — the MCP transport is its
own pipe with its own authentication shape (OAuth client-credentials
for HTTP, env-token bearer for stdio). To keep the tools clean we
funnel both shapes through a single :class:`Principal` dataclass
that carries everything a tool implementation needs to enforce role
+ ownership + scope checks:

* ``user_id`` — the Lumen user this call acts as. For client-
  credentials this is ``MCPClient.owner_user_id``; for the stdio
  Bearer token this is the user whose row owns the matching
  ``LUMEN_MCP_AUTH_TOKEN`` (looked up the same way).
* ``role`` — denormalised from ``users.role`` at resolve time so
  the tool dispatcher can do its role check without a DB round-trip.
* ``scopes`` — list of MCP tool names this principal may invoke,
  or ``["*"]`` for unrestricted. ``has_scope(name)`` is the canonical
  check; it short-circuits ``True`` on wildcard.
* ``client_id`` — the ``mcp_clients.id`` row, surfaced so the LLM
  cost meter + agent trace can attribute traffic to a specific
  registration (useful when one user has multiple Claude Desktop
  installs).

The resolver is split in two so unit tests can swap one half without
touching the other:

* :func:`resolve_from_jwt` — validates the OAuth-minted JWT, looks
  up the ``MCPClient`` row, joins to the ``User``, returns a
  principal. Raises :class:`UnauthorizedError` on any failure
  (expired token, revoked client, missing user). Used by the HTTP
  transport.
* :func:`resolve_from_static_token` — looks up an active
  ``MCPClient`` row by ``client_secret`` directly. This is the
  stdio-mode shortcut: the operator pastes a single secret into
  ``LUMEN_MCP_AUTH_TOKEN`` and Claude Desktop launches the server
  with that env var; no token round-trip needed.

Both code paths converge on :func:`_principal_from_client_row` so
the resolved shape is identical regardless of how the caller
authenticated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnauthorizedError
from app.core.security import verify_password
from app.models.mcp_client import WILDCARD_SCOPE, MCPClient
from app.models.user import Role, User


@dataclass(frozen=True, slots=True)
class Principal:
    """Authenticated identity behind one MCP tool call.

    Immutable on purpose — once the dispatcher has resolved a
    principal, downstream tools should never mutate it. The cost
    meter + agent tracer attribute their rows by ``user_id``;
    swapping out underneath would split a single tool call's
    audit trail across two identities.
    """

    user_id: str
    role: Role
    scopes: list[str]
    client_id: str | None
    # The underlying ORM ``User`` row. Tools that need ownership
    # checks (instructor-scoped writes, course-enrollment lookups)
    # use this directly rather than re-querying by ``user_id``.
    user: User

    def has_scope(self, tool_name: str) -> bool:
        """Is this principal allowed to invoke ``tool_name``?

        Short-circuits ``True`` on the wildcard scope so the
        admin / self-installed case doesn't pay a list-walk per
        tool call.
        """
        if WILDCARD_SCOPE in self.scopes:
            return True
        return tool_name in self.scopes

    @property
    def is_admin(self) -> bool:
        return self.role == Role.admin

    @property
    def is_instructor(self) -> bool:
        """DEPRECATED (ADR-0025 §D5). Kept only so the legacy
        ``auth=="instructor"`` server branch can resolve a stale `instructor`
        principal during the R1–R2 collapse window. Write-gating now uses
        :attr:`can_author`. Removed in the Phase-D cut (S1.13)."""
        return self.role in (Role.instructor, Role.admin)

    @property
    def can_author(self) -> bool:
        """Capability gate for MCP writes — mirrors
        :func:`app.services.capabilities.can_author`. Any active user (the
        underlying ``User`` row, re-read live at resolve time) may author;
        suspension is the single revocation axis (R-CAP)."""
        return self.user is not None and bool(self.user.is_active)

    def can_use_mcp_authoring(self, settings: Any) -> bool:
        """Active principal AND the global ``mcp_authoring_enabled`` flag —
        mirrors :func:`app.services.capabilities.can_use_mcp_authoring`."""
        return self.can_author and bool(getattr(settings, "mcp_authoring_enabled", False))

    def can_ingest_url(self, settings: Any) -> bool:
        """Active AND admin AND the global ``ingest_url_enabled`` flag (default
        OFF) — mirrors :func:`app.services.capabilities.can_ingest_url`.
        URL ingest is NOT auto-opened by the role collapse (DR-M12)."""
        return (
            self.can_author
            and self.is_admin
            and bool(getattr(settings, "ingest_url_enabled", False))
        )


def _principal_from_client_row(
    *, client: MCPClient, user: User, scopes: list[str] | None = None
) -> Principal:
    """Build a :class:`Principal` from a resolved ``(client, user)`` pair.

    ``scopes`` overrides the row's ``scopes`` when the OAuth token
    minted a narrower set than the registration allows (the
    OAuth ``scope`` request param can downscope, never upscope).
    Defaults to the row's full scope list.
    """
    return Principal(
        user_id=user.id,
        role=user.role,
        scopes=list(scopes or client.scopes),
        client_id=client.id,
        user=user,
    )


async def resolve_from_jwt(
    db: AsyncSession, token: str, *, jwt_secret: str, jwt_algorithm: str
) -> Principal:
    """Decode an OAuth-minted JWT and resolve it to a :class:`Principal`.

    The token payload must carry ``sub`` (the ``mcp_clients.id``),
    ``lumen_user_id`` (the owner's user id, denormalised so we can
    reject a token whose client has been re-assigned to a different
    user since mint time), and ``scopes`` (a list of MCP tool names).

    Failure modes — all collapse to ``UnauthorizedError`` so a
    probing caller can't tell why the token was rejected:

    * malformed / expired / wrong-signature JWT
    * client row missing or revoked
    * owner user missing or deactivated
    * client's ``owner_user_id`` no longer matches the token's
      ``lumen_user_id`` (re-assigned post-mint)
    """
    try:
        payload: dict[str, Any] = jwt.decode(
            token, jwt_secret, algorithms=[jwt_algorithm], issuer="lumen-mcp"
        )
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Invalid MCP access token", code="mcp.invalid_token") from exc

    client_id = str(payload.get("sub") or "")
    expected_user_id = str(payload.get("lumen_user_id") or "")
    scopes = list(payload.get("scopes") or [])
    if not client_id or not expected_user_id:
        raise UnauthorizedError("Malformed MCP access token", code="mcp.invalid_token")

    client = await db.get(MCPClient, client_id)
    if client is None or client.revoked_at is not None:
        raise UnauthorizedError("MCP client revoked or missing", code="mcp.client_revoked")
    if client.owner_user_id != expected_user_id:
        # Defence-in-depth: if an admin re-assigned the client to a
        # different user after the token was minted, refuse to honour
        # the now-stale ``lumen_user_id`` claim. The client must
        # re-authenticate with /oauth/token to pick up the new
        # mapping.
        raise UnauthorizedError("MCP token user mismatch", code="mcp.user_mismatch")

    user = await db.get(User, client.owner_user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("MCP client owner inactive", code="mcp.owner_inactive")

    return _principal_from_client_row(client=client, user=user, scopes=scopes)


async def resolve_from_static_token(db: AsyncSession, secret: str) -> Principal:
    """Resolve a stdio-mode static Bearer token to a :class:`Principal`.

    Walks live (non-revoked) ``mcp_clients`` rows and verifies the
    secret against each ``client_secret_hash``. Argon2 verification
    is constant-time per row, so the linear scan is fine at the
    scale we expect (a single Lumen instance plausibly has < 100
    registered MCP clients ever).

    The trade-off vs the JWT path: no expiry, no scope-narrowing,
    one fewer round-trip. Acceptable for the local-machine stdio
    case the env-token shape exists to serve; the HTTP transport
    always uses the JWT path.
    """
    if not secret:
        raise UnauthorizedError("Missing MCP auth token", code="mcp.token_required")

    res = await db.execute(select(MCPClient).where(MCPClient.revoked_at.is_(None)))
    for client in res.scalars().all():
        if verify_password(secret, client.client_secret_hash):
            user = await db.get(User, client.owner_user_id)
            if user is None or not user.is_active:
                raise UnauthorizedError("MCP client owner inactive", code="mcp.owner_inactive")
            # Best-effort ``last_used_at`` stamp. We don't commit here
            # — the caller owns the session lifecycle.
            client.last_used_at = datetime.now(UTC)
            return _principal_from_client_row(client=client, user=user)

    raise UnauthorizedError("Invalid MCP auth token", code="mcp.invalid_token")


__all__ = [
    "Principal",
    "resolve_from_jwt",
    "resolve_from_static_token",
]
