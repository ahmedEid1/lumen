"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Cookie, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import Role, User
from app.repositories import users as users_repo
from app.services import capabilities as cap

DBSession = Annotated[AsyncSession, Depends(get_db)]


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


async def get_current_user_optional(
    db: DBSession,
    authorization: str | None = Header(default=None),
    cookie_access: str | None = Cookie(default=None, alias="__Host-access"),
    # in dev (`is_prod=False`) auth.py sets the cookie as
    # `access`, but only `__Host-access` was being read here, so
    # every cookie-authenticated browser request silently 401'd.
    # The `__Host-*` prefix is browser-enforced (requires Secure +
    # no Domain), so dev (HTTP) can't use it; production keeps
    # `__Host-access` as the strict-prefix cookie name.
    cookie_access_dev: str | None = Cookie(default=None, alias="access"),
) -> User | None:
    token = _bearer(authorization) or cookie_access or cookie_access_dev
    if not token:
        return None
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        return None
    user = await users_repo.get_by_id(db, str(payload.get("sub", "")))
    if not user or not user.is_active:
        return None
    return user


async def get_current_user(
    user: Annotated[User | None, Depends(get_current_user_optional)],
) -> User:
    if not user:
        raise UnauthorizedError("Authentication required", code="auth.required")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_current_user_optional)]


def require_role(*roles: Role):
    async def _dep(user: CurrentUser) -> User:
        if user.role not in roles and not user.is_admin():
            raise ForbiddenError("Insufficient permissions", code="auth.role")
        return user

    return _dep


RequireInstructor = Annotated[User, Depends(require_role(Role.instructor, Role.admin))]
RequireAdmin = Annotated[User, Depends(require_role(Role.admin))]


def RequireCapability(predicate: Callable[..., bool], *, name: str | None = None):
    """Build a dependency that enforces a capability predicate.

    ADR-0025 §D3. The wrapped ``predicate`` is one of the pure functions in
    ``app.services.capabilities``. Predicates come in two arities —
    ``fn(user)`` (e.g. ``can_author``) and ``fn(user, settings)`` (e.g.
    ``can_ingest_url`` / ``can_use_mcp_authoring``) — both are supported;
    the factory passes the global ``Settings`` when the predicate needs it.

    Denial uses the standard ``{error:{code,message,details,request_id}}``
    envelope with ``code="auth.capability"`` and ``details.capability=<name>``.
    Anonymous callers are rejected upstream by ``get_current_user`` with
    ``401 auth.required``; a suspended/inactive user is dropped by
    ``get_current_user_optional`` (also 401), and the predicate denies in any
    case — both paths leave the door shut.
    """
    import inspect

    cap_name = name or getattr(predicate, "__name__", "capability")
    # Predicates that need Settings as a second positional argument.
    needs_settings = len(inspect.signature(predicate).parameters) >= 2

    async def _dep(user: CurrentUser) -> User:
        granted = predicate(user, get_settings()) if needs_settings else predicate(user)
        if not granted:
            raise ForbiddenError(
                "Capability required",
                code="auth.capability",
                details={"capability": cap_name},
            )
        return user

    return Depends(_dep)


RequireAuthor = Annotated[User, RequireCapability(cap.can_author, name="can_author")]
RequireClone = Annotated[User, RequireCapability(cap.can_clone, name="can_clone")]
RequireIngestUrl = Annotated[User, RequireCapability(cap.can_ingest_url, name="can_ingest_url")]


def client_ip(request: Request) -> str | None:
    if not request.client:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host


def user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")
