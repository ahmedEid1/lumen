"""Admin CRUD for MCP OAuth client-credentials registrations.

Lumen v2 Phase I1. Three read/write endpoints, admin-only:

* ``POST   /api/v1/admin/mcp-clients`` — mint a new
  ``mcp_clients`` row and return the freshly-minted secret. The
  secret is shown **once** in the response; we never persist it
  un-hashed.
* ``GET    /api/v1/admin/mcp-clients`` — list registrations. Filters
  to live (non-revoked) rows by default; pass ``include_revoked=true``
  to see the tombstoned ones too.
* ``DELETE /api/v1/admin/mcp-clients/{id}`` — soft-revoke a row by
  stamping ``revoked_at``. The OAuth handler treats any non-null
  ``revoked_at`` as inactive.

Why no PATCH? The two mutable fields (``scopes``, ``name``) belong
to the operator-mints-on-behalf-of-the-user flow; if the user wants
to change either they revoke + re-mint. Keeping the surface tight
shrinks the attack window and the test matrix.

NOTE: this router is **not** registered in ``app/api/router.py`` —
the orchestrator will mount it after the parallel I-phase agents
land. The expected mount is::

    api_router.include_router(
        admin_mcp_clients.router,
        prefix="/admin",
        tags=["admin-mcp-clients"],
    )
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select

from app.api.deps import DBSession, RequireAdmin
from app.core.errors import NotFoundError, ValidationAppError
from app.core.ids import new_id
from app.core.security import hash_password
from app.models.mcp_client import WILDCARD_SCOPE, MCPClient
from app.repositories import users as users_repo

router = APIRouter()


# ---------- DTOs ----------


class MCPClientCreate(BaseModel):
    """Request body for ``POST /admin/mcp-clients``.

    The admin specifies the Lumen user the secret will act as.
    ``scopes`` is optional; defaults to the wildcard so the typical
    "instructor wants full MCP access" case is one click.
    """

    model_config = ConfigDict(extra="forbid")

    owner_user_id: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=120)
    scopes: list[str] = Field(default_factory=lambda: [WILDCARD_SCOPE])

    @classmethod
    def _validate_scopes(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("scopes must be non-empty")
        # Deduplicate while preserving order so the registered scope
        # list reads predictably for the admin.
        seen: set[str] = set()
        out: list[str] = []
        for item in v:
            stripped = item.strip()
            if not stripped:
                continue
            if stripped not in seen:
                seen.add(stripped)
                out.append(stripped)
        if not out:
            raise ValueError("scopes must contain at least one non-empty token")
        return out


class MCPClientCreatedOut(BaseModel):
    """Response for ``POST /admin/mcp-clients``.

    The ``client_secret`` is plaintext **only on this response**;
    once the admin closes the page they need to mint a new one if
    they lose it. Mirrors the GitHub PAT shape every developer
    already understands.
    """

    model_config = ConfigDict(extra="forbid")

    client_id: str
    client_secret: str
    owner_user_id: str
    name: str
    scopes: list[str]
    created_at: datetime


class MCPClientOut(BaseModel):
    """Response shape for list + delete endpoints — no secret material."""

    model_config = ConfigDict(extra="forbid")

    client_id: str
    owner_user_id: str
    name: str
    scopes: list[str]
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


def _project(row: MCPClient) -> MCPClientOut:
    return MCPClientOut(
        client_id=row.id,
        owner_user_id=row.owner_user_id,
        name=row.name,
        scopes=list(row.scopes),
        revoked_at=row.revoked_at,
        last_used_at=row.last_used_at,
        created_at=row.created_at,
    )


# ---------- Endpoints ----------


@router.post(
    "/mcp-clients",
    response_model=MCPClientCreatedOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_client(
    payload: MCPClientCreate,
    _: RequireAdmin,
    db: DBSession,
) -> MCPClientCreatedOut:
    """Mint a new ``mcp_clients`` row + return its plaintext secret.

    The owner must exist and be active. Scopes are deduplicated;
    the wildcard ``["*"]`` short-circuits the per-tool gate on every
    call this client makes.
    """
    try:
        scopes = MCPClientCreate._validate_scopes(payload.scopes)
    except ValueError as exc:
        raise ValidationAppError(str(exc), code="mcp.client.invalid_scopes") from exc

    owner = await users_repo.get_by_id(db, payload.owner_user_id)
    if owner is None or not owner.is_active:
        raise NotFoundError(
            "Owner user not found or inactive",
            code="user.not_found",
        )

    # ``client_secret`` is a fresh 21-char nanoid (same alphabet the
    # rest of the codebase uses for opaque tokens). We hash it with
    # argon2 (same scheme as ``users.password_hash``) and persist
    # only the hash. The caller sees the plaintext exactly once.
    plaintext_secret = new_id()
    row = MCPClient(
        client_secret_hash=hash_password(plaintext_secret),
        owner_user_id=owner.id,
        name=payload.name,
        scopes=scopes,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)

    return MCPClientCreatedOut(
        client_id=row.id,
        client_secret=plaintext_secret,
        owner_user_id=row.owner_user_id,
        name=row.name,
        scopes=list(row.scopes),
        created_at=row.created_at,
    )


@router.get("/mcp-clients", response_model=list[MCPClientOut])
async def list_clients(
    _: RequireAdmin,
    db: DBSession,
    owner_user_id: Annotated[str | None, Query(max_length=64)] = None,
    include_revoked: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[MCPClientOut]:
    """List MCP client registrations, newest first.

    Filters out revoked rows by default so the typical "show me my
    active integrations" view stays clean. Pass
    ``include_revoked=true`` for the audit view.
    """
    stmt = select(MCPClient).order_by(desc(MCPClient.created_at)).limit(limit)
    if owner_user_id:
        stmt = stmt.where(MCPClient.owner_user_id == owner_user_id)
    if not include_revoked:
        stmt = stmt.where(MCPClient.revoked_at.is_(None))
    rows = (await db.execute(stmt)).scalars().all()
    return [_project(r) for r in rows]


@router.delete("/mcp-clients/{client_id}", response_model=MCPClientOut)
async def revoke_client(
    _: RequireAdmin,
    db: DBSession,
    client_id: Annotated[str, Path(max_length=64)],
) -> MCPClientOut:
    """Soft-revoke a client by stamping ``revoked_at``.

    Re-revoking an already-revoked client is a no-op (we return the
    row unchanged with its original ``revoked_at`` intact). The
    operation is idempotent so a flaky network retry can't bury an
    earlier revoke under a fresh timestamp.
    """
    row = await db.get(MCPClient, client_id)
    if row is None:
        raise NotFoundError("MCP client not found", code="mcp.client.not_found")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
    return _project(row)


# Orchestrator follow-up: register this router in
# ``apps/backend/app/api/router.py`` under the existing admin
# prefix:
#
#     from app.api.v1 import admin_mcp_clients
#     api_router.include_router(
#         admin_mcp_clients.router,
#         prefix="/admin",
#         tags=["admin-mcp-clients"],
#     )
#
# Also add ``MCPClient`` to ``apps/backend/app/models/__init__.py``
# so Alembic autogenerate + the test conftest's ``create_all`` pick
# it up alongside everything else.
