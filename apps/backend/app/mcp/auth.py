"""OAuth 2.0 client-credentials flow for the Lumen MCP server.

Lumen v2 Phase I1. The MCP authorisation spec recommends OAuth 2.0
client-credentials (RFC 6749 §4.4) for service-to-service callers —
this is what Claude Desktop's HTTP-mode MCP installs use. We surface
two endpoints under the HTTP transport:

* ``POST /oauth/token`` — exchanges ``client_id`` + ``client_secret``
  (form-encoded, per RFC 6749) for a short-lived JWT access token.
* ``GET /.well-known/oauth-authorization-server`` — RFC 8414 metadata
  document advertising the token endpoint, supported grants, and
  the issuer.

The JWT carries:

* ``iss="lumen-mcp"`` — distinct from the main API's ``"lumen"``
  issuer so a mis-routed token (e.g. someone pasting a Lumen API
  access token here) is rejected at the issuer check rather than
  granting silent access.
* ``sub=<client_id>`` — the ``mcp_clients.id`` row.
* ``lumen_user_id=<owner_user_id>`` — denormalised so the principal
  resolver can reject a token whose client was re-assigned.
* ``scopes=[...]`` — the tool names this token may invoke. The
  request can downscope (intersect with the row's full scope list)
  but never upscope.
* ``exp`` — 15 minutes after mint, matching the Lumen API's access-
  token TTL. Clients refresh by re-calling ``/oauth/token`` with
  their stored secret — the same shape as the spec's "no refresh
  token" client-credentials story.

The endpoints are mounted by :mod:`app.mcp.server` on the HTTP
transport's Starlette/FastAPI app. They're deliberately *not*
mounted on the main Lumen API surface — the MCP transport is its
own pipe with its own attack-surface and its own JWT issuer; mixing
the two would muddy the principle-of-least-privilege story we tell
operators.

A note on rate-limiting. The token endpoint isn't itself rate-limited
here (the spec's "treat the token endpoint as cheap" precedent), but
we log every issued token + every rejection so an operator can spot
brute-force attempts in structlog. The argon2 verification is the
real throttle: at ~50ms per check, a malicious client gets ~20
attempts/sec per CPU, which is well below the cost of an effective
brute force against a 32-char secret.
"""

from __future__ import annotations

import secrets
import time
from typing import Any

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnauthorizedError
from app.core.logging import get_logger
from app.core.security import verify_password
from app.models.mcp_client import WILDCARD_SCOPE, MCPClient

log = get_logger(__name__)


# Token TTL — matches the main API's access-token TTL (15 min) per
# Lumen's CLAUDE.md auth conventions. Long enough that a typical
# Claude Desktop session doesn't have to re-mint mid-conversation,
# short enough that a leaked token has a tight blast radius.
TOKEN_TTL_SECONDS = 15 * 60

# JWT issuer for MCP-minted tokens. Deliberately distinct from the
# main API's ``"lumen"`` issuer so a mis-routed token (e.g. someone
# pasting a Lumen API access token into the MCP transport) is
# rejected at the issuer check rather than granting silent access.
ISSUER = "lumen-mcp"


def _intersect_scopes(requested: list[str] | None, granted: list[str]) -> list[str]:
    """Compute the effective scope set for one token mint.

    OAuth client-credentials lets the client request a *narrower*
    scope than the registration allows ("I'm only going to use
    ``list_courses`` and ``ask_tutor`` in this session — don't
    grant me ``create_course_draft`` even though I could"). We honour
    that, but never upscope: if the registration has scopes ``["a",
    "b"]`` and the client requests ``["a", "c"]``, the token gets
    ``["a"]``.

    The wildcard case is symmetric — a registration with ``["*"]``
    and a request for ``["list_courses"]`` mints a token with
    ``["list_courses"]``; a registration with ``["list_courses"]``
    and a request for ``["*"]`` mints a token with ``["list_courses"]``
    (the wildcard request is treated as "give me everything I'm
    entitled to").
    """
    if not requested:
        return list(granted)
    if WILDCARD_SCOPE in requested:
        return list(granted)
    if WILDCARD_SCOPE in granted:
        return list(requested)
    return [s for s in requested if s in granted]


async def issue_token(
    db: AsyncSession,
    *,
    client_id: str,
    client_secret: str,
    requested_scopes: list[str] | None,
    jwt_secret: str,
    jwt_algorithm: str,
) -> dict[str, Any]:
    """Verify client credentials and mint a short-lived access token.

    Returns the RFC 6749 §5.1 token response shape:

    .. code-block:: json

        {
          "access_token": "<JWT>",
          "token_type": "Bearer",
          "expires_in": 900,
          "scope": "list_courses ask_tutor"
        }

    Raises :class:`UnauthorizedError` on any failure — the handler
    layer converts that to the spec's ``invalid_client`` /
    ``invalid_grant`` response. We don't differentiate between the
    two on the wire so a probing caller can't tell whether the
    ``client_id`` exists.
    """
    client = await db.get(MCPClient, client_id)
    # Always run a constant-time verify against *something* even on
    # missing-client so the timing channel is closed. Argon2's
    # ``verify`` against a known-bad hash is the same cost as a real
    # verify; the dummy hash here is the canonical zero-secret
    # argon2 digest.
    if client is None:
        # The cheapest constant-time-ish check: verify against a
        # known-bad hash so we always pay one argon2 call, then fail.
        _ = verify_password(
            client_secret,
            "$argon2id$v=19$m=65536,t=3,p=4$"
            "ZHVtbXktc2FsdC1mb3ItdGltaW5n$"
            "ZHVtbXktaGFzaC1mb3ItdGltaW5n",
        )
        raise UnauthorizedError("Invalid MCP client credentials", code="mcp.invalid_client")
    if client.revoked_at is not None:
        raise UnauthorizedError("Invalid MCP client credentials", code="mcp.invalid_client")
    if not verify_password(client_secret, client.client_secret_hash):
        log.warning(
            "mcp_oauth_bad_secret",
            client_id=client_id,
        )
        raise UnauthorizedError("Invalid MCP client credentials", code="mcp.invalid_client")

    effective_scopes = _intersect_scopes(requested_scopes, list(client.scopes))
    if not effective_scopes:
        raise UnauthorizedError(
            "No scopes granted by this MCP client",
            code="mcp.scope_empty",
        )

    now = int(time.time())
    payload = {
        "iss": ISSUER,
        "sub": client.id,
        "lumen_user_id": client.owner_user_id,
        "scopes": effective_scopes,
        "iat": now,
        "exp": now + TOKEN_TTL_SECONDS,
        "jti": secrets.token_urlsafe(12),
    }
    access_token = jwt.encode(payload, jwt_secret, algorithm=jwt_algorithm)

    # Stamp ``last_used_at`` so the admin surface can identify
    # dormant clients. The caller is responsible for the commit.
    from datetime import UTC
    from datetime import datetime as _dt

    client.last_used_at = _dt.now(UTC)
    await db.flush()

    log.info(
        "mcp_oauth_token_issued",
        client_id=client.id,
        owner_user_id=client.owner_user_id,
        scopes=effective_scopes,
    )

    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": TOKEN_TTL_SECONDS,
        "scope": " ".join(effective_scopes),
    }


def authorization_server_metadata(*, base_url: str) -> dict[str, Any]:
    """Return the RFC 8414 authorisation-server metadata document.

    Mounted at ``/.well-known/oauth-authorization-server`` on the MCP
    HTTP transport. MCP clients (and any RFC 8414-aware OAuth client)
    fetch this to learn where the token endpoint is and which grants
    are supported — same shape OIDC providers expose, modulo the
    OIDC-specific fields.

    ``base_url`` should be the externally-reachable origin of the
    MCP HTTP transport (e.g. ``https://lumen-mcp.fly.dev``); the
    server module passes it down from the CLI's ``--public-url`` flag
    (or the request's own ``Host`` header in dev).
    """
    return {
        "issuer": ISSUER,
        "token_endpoint": f"{base_url.rstrip('/')}/oauth/token",
        "token_endpoint_auth_methods_supported": [
            "client_secret_post",
            "client_secret_basic",
        ],
        "grant_types_supported": ["client_credentials"],
        "response_types_supported": ["token"],
        "scopes_supported": [
            "list_courses",
            "get_course",
            "search_lesson_content",
            "ask_tutor",
            "list_my_due_reviews",
            "grade_review_card",
            "create_course_draft",
            "ingest_url_to_draft",
            "list_my_progress",
            WILDCARD_SCOPE,
        ],
        "service_documentation": "https://github.com/ahmedEid1/E-Learning-Platform/blob/Rewrite/docs/mcp.md",
    }


async def lookup_active_client(db: AsyncSession, *, client_id: str) -> MCPClient | None:
    """Convenience lookup used by the admin endpoints.

    Returns ``None`` if the row is missing or revoked. Doesn't touch
    ``last_used_at`` — that's the OAuth handler's job, not a read.
    """
    res = await db.execute(
        select(MCPClient).where(
            MCPClient.id == client_id,
            MCPClient.revoked_at.is_(None),
        )
    )
    return res.scalar_one_or_none()


__all__ = [
    "ISSUER",
    "TOKEN_TTL_SECONDS",
    "authorization_server_metadata",
    "issue_token",
    "lookup_active_client",
]
