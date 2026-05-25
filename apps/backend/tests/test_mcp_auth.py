"""OAuth client-credentials flow for the Lumen MCP server.

Lumen v2 Phase I1. Covers:

* :func:`app.mcp.auth.issue_token` happy path — secret verifies,
  scopes intersect, JWT carries the right claims.
* Revoked client → ``UnauthorizedError`` with ``mcp.invalid_client``.
* Bad secret → same error code (we collapse "unknown client" and
  "wrong secret" so a probing caller can't enumerate client_ids).
* Scope narrowing — registration grants ``["*"]``, request asks for
  ``["list_courses"]``, minted token has ``["list_courses"]``.
* Scope upscoping refused — registration grants ``["list_courses"]``,
  request asks for ``["ask_tutor"]``, minted token mints with an
  empty intersection (rejected as ``mcp.scope_empty``).

The principal resolver round-trip — JWT → ``MCPClient`` → ``User``
→ :class:`Principal` — is covered here too: we mint a token, then
hand it to ``resolve_from_jwt`` and assert on the shape.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.core.ids import new_id
from app.core.security import hash_password
from app.mcp import auth as mcp_auth
from app.mcp.principal import resolve_from_jwt, resolve_from_static_token
from app.models.mcp_client import MCPClient
from app.models.user import Role

# ---------- Helpers ----------


async def _mint_client(
    db: AsyncSession,
    owner_user_id: str,
    *,
    scopes: list[str] | None = None,
    revoked: bool = False,
) -> tuple[MCPClient, str]:
    """Persist a fresh ``mcp_clients`` row and return ``(row, plaintext_secret)``.

    The plaintext is hashed before persistence; tests pass it back
    to ``issue_token`` to exercise the verify path with realistic
    inputs.
    """
    plaintext = new_id()
    row = MCPClient(
        client_secret_hash=hash_password(plaintext),
        owner_user_id=owner_user_id,
        name="Test client",
        scopes=scopes or ["*"],
        revoked_at=(datetime.now(UTC) if revoked else None),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row, plaintext


def _settings_keys() -> tuple[str, str]:
    """Return ``(jwt_secret, jwt_algorithm)`` for token mint + decode tests."""
    s = get_settings()
    return s.jwt_secret.get_secret_value(), s.jwt_algorithm


# ---------- issue_token ----------


@pytest.mark.asyncio
async def test_issue_token_happy_path(db_session: AsyncSession, make_user) -> None:
    user = await make_user(role=Role.instructor)
    client, secret = await _mint_client(db_session, user.id)

    secret_key, algo = _settings_keys()
    payload = await mcp_auth.issue_token(
        db_session,
        client_id=client.id,
        client_secret=secret,
        requested_scopes=None,
        jwt_secret=secret_key,
        jwt_algorithm=algo,
    )
    assert payload["token_type"] == "Bearer"
    assert payload["expires_in"] == mcp_auth.TOKEN_TTL_SECONDS
    # Decode the minted JWT and assert on its claims directly.
    decoded = jwt.decode(
        payload["access_token"],
        secret_key,
        algorithms=[algo],
        issuer=mcp_auth.ISSUER,
    )
    assert decoded["sub"] == client.id
    assert decoded["lumen_user_id"] == user.id
    assert decoded["scopes"] == ["*"]


@pytest.mark.asyncio
async def test_issue_token_revoked_client_rejected(db_session: AsyncSession, make_user) -> None:
    user = await make_user(role=Role.instructor)
    client, secret = await _mint_client(db_session, user.id, revoked=True)

    secret_key, algo = _settings_keys()
    with pytest.raises(UnauthorizedError):
        await mcp_auth.issue_token(
            db_session,
            client_id=client.id,
            client_secret=secret,
            requested_scopes=None,
            jwt_secret=secret_key,
            jwt_algorithm=algo,
        )


@pytest.mark.asyncio
async def test_issue_token_bad_secret_rejected(db_session: AsyncSession, make_user) -> None:
    user = await make_user(role=Role.instructor)
    client, _ = await _mint_client(db_session, user.id)

    secret_key, algo = _settings_keys()
    with pytest.raises(UnauthorizedError):
        await mcp_auth.issue_token(
            db_session,
            client_id=client.id,
            client_secret="definitely-not-the-right-secret",
            requested_scopes=None,
            jwt_secret=secret_key,
            jwt_algorithm=algo,
        )


@pytest.mark.asyncio
async def test_issue_token_unknown_client_rejected(
    db_session: AsyncSession,
) -> None:
    """Missing-client and bad-secret collapse to the same error code."""
    secret_key, algo = _settings_keys()
    with pytest.raises(UnauthorizedError):
        await mcp_auth.issue_token(
            db_session,
            client_id="no-such-client-row",
            client_secret="anything",
            requested_scopes=None,
            jwt_secret=secret_key,
            jwt_algorithm=algo,
        )


# ---------- Scope intersection ----------


@pytest.mark.asyncio
async def test_request_narrows_scopes(db_session: AsyncSession, make_user) -> None:
    """Registration grants ``["*"]``; request asks for a narrower set."""
    user = await make_user(role=Role.instructor)
    client, secret = await _mint_client(db_session, user.id, scopes=["*"])

    secret_key, algo = _settings_keys()
    payload = await mcp_auth.issue_token(
        db_session,
        client_id=client.id,
        client_secret=secret,
        requested_scopes=["list_courses", "ask_tutor"],
        jwt_secret=secret_key,
        jwt_algorithm=algo,
    )
    decoded = jwt.decode(
        payload["access_token"],
        secret_key,
        algorithms=[algo],
        issuer=mcp_auth.ISSUER,
    )
    assert set(decoded["scopes"]) == {"list_courses", "ask_tutor"}


@pytest.mark.asyncio
async def test_request_cannot_upscope(db_session: AsyncSession, make_user) -> None:
    """Registration grants only ``list_courses``; request asks for
    ``ask_tutor`` (which the row never had). Intersection is empty
    → ``mcp.scope_empty``.
    """
    user = await make_user(role=Role.instructor)
    client, secret = await _mint_client(db_session, user.id, scopes=["list_courses"])

    secret_key, algo = _settings_keys()
    with pytest.raises(UnauthorizedError):
        await mcp_auth.issue_token(
            db_session,
            client_id=client.id,
            client_secret=secret,
            requested_scopes=["ask_tutor"],
            jwt_secret=secret_key,
            jwt_algorithm=algo,
        )


# ---------- Principal resolution ----------


@pytest.mark.asyncio
async def test_resolve_from_jwt_round_trips_principal(db_session: AsyncSession, make_user) -> None:
    user = await make_user(role=Role.instructor)
    client, secret = await _mint_client(db_session, user.id, scopes=["list_courses", "ask_tutor"])

    secret_key, algo = _settings_keys()
    payload = await mcp_auth.issue_token(
        db_session,
        client_id=client.id,
        client_secret=secret,
        requested_scopes=None,
        jwt_secret=secret_key,
        jwt_algorithm=algo,
    )

    principal = await resolve_from_jwt(
        db_session,
        payload["access_token"],
        jwt_secret=secret_key,
        jwt_algorithm=algo,
    )
    assert principal.user_id == user.id
    assert principal.role == Role.instructor
    assert principal.client_id == client.id
    assert set(principal.scopes) == {"list_courses", "ask_tutor"}
    # has_scope honours the explicit list (no wildcard).
    assert principal.has_scope("list_courses") is True
    assert principal.has_scope("create_course_draft") is False


@pytest.mark.asyncio
async def test_resolve_from_jwt_rejects_revoked_client(db_session: AsyncSession, make_user) -> None:
    user = await make_user(role=Role.instructor)
    client, secret = await _mint_client(db_session, user.id)
    secret_key, algo = _settings_keys()

    payload = await mcp_auth.issue_token(
        db_session,
        client_id=client.id,
        client_secret=secret,
        requested_scopes=None,
        jwt_secret=secret_key,
        jwt_algorithm=algo,
    )

    # Revoke between mint and resolve.
    client.revoked_at = datetime.now(UTC)
    await db_session.commit()

    with pytest.raises(UnauthorizedError):
        await resolve_from_jwt(
            db_session,
            payload["access_token"],
            jwt_secret=secret_key,
            jwt_algorithm=algo,
        )


@pytest.mark.asyncio
async def test_resolve_from_jwt_rejects_expired_token(db_session: AsyncSession, make_user) -> None:
    """Hand-craft a JWT with an ``exp`` already in the past; the
    decoder must reject it before any DB work happens.
    """
    user = await make_user(role=Role.instructor)
    client, _ = await _mint_client(db_session, user.id)
    secret_key, algo = _settings_keys()

    expired_payload = {
        "iss": mcp_auth.ISSUER,
        "sub": client.id,
        "lumen_user_id": user.id,
        "scopes": ["*"],
        "iat": int((datetime.now(UTC) - timedelta(hours=2)).timestamp()),
        "exp": int((datetime.now(UTC) - timedelta(hours=1)).timestamp()),
    }
    expired_token = jwt.encode(expired_payload, secret_key, algorithm=algo)

    with pytest.raises(UnauthorizedError):
        await resolve_from_jwt(
            db_session,
            expired_token,
            jwt_secret=secret_key,
            jwt_algorithm=algo,
        )


@pytest.mark.asyncio
async def test_resolve_from_static_token_happy_path(db_session: AsyncSession, make_user) -> None:
    """Stdio-mode resolver: the env-token is the plaintext client_secret.

    Linear scan over live ``mcp_clients`` rows + argon2 verify each.
    """
    user = await make_user(role=Role.instructor)
    client, secret = await _mint_client(db_session, user.id)

    principal = await resolve_from_static_token(db_session, secret)
    assert principal.user_id == user.id
    assert principal.client_id == client.id


@pytest.mark.asyncio
async def test_resolve_from_static_token_rejects_revoked(
    db_session: AsyncSession, make_user
) -> None:
    user = await make_user(role=Role.instructor)
    _client, secret = await _mint_client(db_session, user.id, revoked=True)

    with pytest.raises(UnauthorizedError):
        await resolve_from_static_token(db_session, secret)


@pytest.mark.asyncio
async def test_resolve_from_static_token_rejects_empty(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(UnauthorizedError):
        await resolve_from_static_token(db_session, "")


# ---------- Metadata document ----------


def test_authorization_server_metadata_shape() -> None:
    md = mcp_auth.authorization_server_metadata(base_url="https://lumen-mcp.example.com")
    assert md["issuer"] == "lumen-mcp"
    assert md["token_endpoint"] == "https://lumen-mcp.example.com/oauth/token"
    assert "client_credentials" in md["grant_types_supported"]
    # All nine tool names appear in the scope vocab.
    from app.mcp.tools import all_tool_names

    for tool_name in all_tool_names():
        assert tool_name in md["scopes_supported"]
