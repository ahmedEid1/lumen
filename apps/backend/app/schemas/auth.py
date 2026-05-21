from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.core.email_type import Email

from app.schemas.user import UserOut

PASSWORD_MIN = 12


def validate_password_strength(v: str) -> str:
    """Shared password policy applied to every endpoint that accepts a new
    password (register, reset-confirm, change-password). Keeping the check
    in one place stops a downgrade path where an attacker (or careless
    user) could bypass the registration policy via the reset/change flow.
    Cheap structural check; HIBP / breach-list lookup is future work.
    """
    if v.isalnum() and v.lower() == v:
        raise ValueError("password must mix character classes")
    return v


class RegisterRequest(BaseModel):
    email: Email
    password: str = Field(min_length=PASSWORD_MIN, max_length=128)
    full_name: str = Field(min_length=1, max_length=120)

    @field_validator("password")
    @classmethod
    def _strength(cls, v: str) -> str:
        return validate_password_strength(v)


class LoginRequest(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class PasswordResetRequest(BaseModel):
    email: Email


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=PASSWORD_MIN, max_length=128)

    @field_validator("password")
    @classmethod
    def _strength(cls, v: str) -> str:
        return validate_password_strength(v)


class EmailVerifyConfirm(BaseModel):
    token: str = Field(min_length=10, max_length=600)
