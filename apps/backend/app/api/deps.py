"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import jwt
from fastapi import Cookie, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, UnauthorizedError
from app.db.session import get_db
from app.models.user import Role, User
from app.repositories import users as users_repo
from app.core.security import decode_token

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
) -> User | None:
    token = _bearer(authorization) or cookie_access
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


def client_ip(request: Request) -> str | None:
    if not request.client:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host


def user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")
