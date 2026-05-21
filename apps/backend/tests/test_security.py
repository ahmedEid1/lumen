"""Security primitives."""

from __future__ import annotations

import jwt
import pytest

from app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    h = hash_password("Password!1234")
    assert verify_password("Password!1234", h)
    assert not verify_password("Password!1235", h)


def test_password_verify_handles_garbage() -> None:
    assert not verify_password("anything", "not-a-hash")


def test_jwt_roundtrip() -> None:
    token, exp = create_access_token(subject="abc", role="student")
    payload = decode_token(token)
    assert payload["sub"] == "abc"
    assert payload["role"] == "student"
    assert payload["exp"] == exp
    assert payload["iss"] == "lumen"


def test_jwt_rejects_tampered() -> None:
    token, _ = create_access_token(subject="abc", role="student")
    parts = token.split(".")
    bad = parts[0] + "." + parts[1] + ".invalid"
    with pytest.raises(jwt.PyJWTError):
        decode_token(bad)


def test_refresh_token_hash_is_stable() -> None:
    raw, digest = new_refresh_token()
    assert digest == hash_refresh_token(raw)
    assert len(raw) >= 32
