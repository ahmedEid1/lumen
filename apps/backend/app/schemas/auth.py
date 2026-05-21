from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.user import UserOut

PASSWORD_MIN = 12


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=PASSWORD_MIN, max_length=128)
    full_name: str = Field(min_length=1, max_length=120)

    @field_validator("password")
    @classmethod
    def _strength(cls, v: str) -> str:
        # Cheap structural check; full strength enforced server-side (HIBP optional).
        if v.isalnum() and v.lower() == v:
            raise ValueError("password must mix character classes")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=PASSWORD_MIN, max_length=128)


class EmailVerifyConfirm(BaseModel):
    token: str = Field(min_length=10, max_length=600)
