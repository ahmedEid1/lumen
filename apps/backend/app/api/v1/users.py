"""User profile, password change, GDPR export/delete."""

from __future__ import annotations

from pydantic import BaseModel, Field

from fastapi import APIRouter, Request

from app.api.deps import CurrentUser, DBSession, client_ip, user_agent
from app.core.errors import UnauthorizedError, ValidationAppError
from app.core.security import hash_password, verify_password
from app.repositories import audit as audit_repo
from app.repositories import users as users_repo
from app.schemas.common import OkResponse
from app.schemas.user import UserOut, UserUpdate

router = APIRouter()


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class DeleteAccountRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


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
    from sqlalchemy import select, func
    from app.models.course import Enrollment, Review
    from app.models.chat import ChatMessage

    enrollments = int(
        (await db.execute(select(func.count(Enrollment.id)).where(Enrollment.user_id == user.id))).scalar_one()
    )
    reviews = int(
        (await db.execute(select(func.count(Review.id)).where(Review.author_id == user.id))).scalar_one()
    )
    messages = int(
        (
            await db.execute(select(func.count(ChatMessage.id)).where(ChatMessage.author_id == user.id))
        ).scalar_one()
    )
    return {
        "profile": UserOut.model_validate(user).model_dump(mode="json"),
        "counts": {
            "enrollments": enrollments,
            "reviews": reviews,
            "chat_messages": messages,
        },
    }


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
