"""User profile, password change, sessions, GDPR export/delete."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import desc, func, select

from app.api.deps import CurrentUser, DBSession, client_ip, user_agent
from app.core.email_type import Email
from app.core.errors import NotFoundError, UnauthorizedError, ValidationAppError
from app.core.security import hash_password, verify_password
from app.models.course import Enrollment, Review
from app.models.user import RefreshToken
from app.repositories import audit as audit_repo
from app.repositories import users as users_repo
from app.schemas.auth import PASSWORD_MIN, validate_password_strength
from app.schemas.common import OkResponse
from app.schemas.user import UserOut, UserUpdate
from app.services import email_change as email_change_service
from app.services import password_hibp

router = APIRouter()


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=PASSWORD_MIN, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _strength(cls, v: str) -> str:
        return validate_password_strength(v)


class DeleteAccountRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    user_agent: str | None = None
    ip_address: str | None = None


@router.get("/me", response_model=UserOut)
async def get_me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.patch("/me", response_model=UserOut)
async def update_me(payload: UserUpdate, user: CurrentUser, db: DBSession) -> UserOut:
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.bio is not None:
        user.bio = payload.bio
    if payload.avatar_url is not None:
        user.avatar_url = payload.avatar_url
    await db.flush()
    return UserOut.model_validate(user)


@router.post("/me/change-password", response_model=OkResponse)
async def change_password(
    payload: ChangePasswordRequest,
    user: CurrentUser,
    db: DBSession,
    request: Request,
) -> OkResponse:
    if not verify_password(payload.current_password, user.password_hash):
        raise UnauthorizedError("Current password is incorrect", code="auth.invalid_credentials")
    if payload.new_password == payload.current_password:
        raise ValidationAppError("New password must differ", code="auth.password_reused")
    # Same HIBP gate the register / reset flows run, so all three
    # password-setting paths share one policy AND one breach-list lookup.
    await password_hibp.assert_not_pwned(payload.new_password)
    user.password_hash = hash_password(payload.new_password)
    await users_repo.revoke_all_refresh_tokens(db, user.id)
    await audit_repo.record(
        db,
        actor_id=user.id,
        action="auth.password_changed",
        ip_address=client_ip(request),
        user_agent=user_agent(request),
    )
    return OkResponse()


@router.get("/me/export", response_model=dict)
async def export_my_data(user: CurrentUser, db: DBSession) -> dict:
    """Lightweight GDPR export — returns the user's profile + counts.

    A future enhancement will enqueue a Celery job that produces a downloadable
    zip including chat history, reviews, and enrollment data. For v1 we expose
    the profile inline.
    """
    async def _count(stmt) -> int:
        return int((await db.execute(stmt)).scalar_one())

    enrollments = await _count(select(func.count(Enrollment.id)).where(Enrollment.user_id == user.id))
    reviews = await _count(select(func.count(Review.id)).where(Review.author_id == user.id))
    return {
        "profile": UserOut.model_validate(user).model_dump(mode="json"),
        "counts": {
            "enrollments": enrollments,
            "reviews": reviews,
        },
    }


@router.get("/me/sessions", response_model=list[SessionOut])
async def list_my_sessions(user: CurrentUser, db: DBSession) -> list[SessionOut]:
    rows = (
        await db.execute(
            select(RefreshToken)
            .where(RefreshToken.user_id == user.id)
            .order_by(desc(RefreshToken.issued_at))
            .limit(50)
        )
    ).scalars().all()
    return [SessionOut.model_validate(r) for r in rows]


@router.delete("/me/sessions", response_model=OkResponse)
async def revoke_all_my_sessions(user: CurrentUser, db: DBSession) -> OkResponse:
    await users_repo.revoke_all_refresh_tokens(db, user.id)
    return OkResponse()


@router.delete("/me/sessions/{session_id}", response_model=OkResponse)
async def revoke_my_session(session_id: str, user: CurrentUser, db: DBSession) -> OkResponse:
    row = await db.get(RefreshToken, session_id)
    if not row or row.user_id != user.id:
        raise NotFoundError("Session not found", code="session.not_found")
    if row.revoked_at is None:
        await users_repo.revoke_refresh_token(db, row)
    return OkResponse()


class EmailChangeRequest(BaseModel):
    new_email: Email
    current_password: str = Field(min_length=1, max_length=128)


class EmailChangeConfirm(BaseModel):
    token: str = Field(min_length=10, max_length=400)


@router.post("/me/email/request", response_model=OkResponse)
async def request_email_change(
    payload: EmailChangeRequest, user: CurrentUser, db: DBSession
) -> OkResponse:
    """Step 1 of the email-change flow: mint a confirmation token and
    send it to the NEW address. The change doesn't take effect until
    the user clicks through from that mailbox — proves they control it.
    """
    _, token = await email_change_service.request_change(
        db,
        user=user,
        new_email=str(payload.new_email),
        current_password=payload.current_password,
    )
    if token is not None:
        email_change_service.queue_confirmation_email(
            user=user, new_email=str(payload.new_email), token=token
        )
    return OkResponse()


@router.post("/me/email/confirm", response_model=UserOut)
async def confirm_email_change(
    payload: EmailChangeConfirm, db: DBSession
) -> UserOut:
    """Step 2: token from the email link → applies the change, revokes
    all refresh tokens so any parallel session has to re-authenticate
    with the new credentials.
    """
    user = await email_change_service.confirm_change(db, token=payload.token)
    return UserOut.model_validate(user)


@router.delete("/me", response_model=OkResponse)
async def delete_me(
    payload: DeleteAccountRequest, user: CurrentUser, db: DBSession, request: Request
) -> OkResponse:
    if not verify_password(payload.password, user.password_hash):
        raise UnauthorizedError("Password is incorrect", code="auth.invalid_credentials")
    await audit_repo.record(
        db,
        actor_id=user.id,
        action="user.deleted",
        target_type="user",
        target_id=user.id,
        ip_address=client_ip(request),
        user_agent=user_agent(request),
    )
    user.is_active = False
    user.email = f"deleted-{user.id}@lumen.invalid"
    user.password_hash = hash_password("!disabled!" + user.id)
    user.full_name = "Deleted user"
    user.avatar_url = None
    user.bio = None
    await users_repo.revoke_all_refresh_tokens(db, user.id)
    return OkResponse()
