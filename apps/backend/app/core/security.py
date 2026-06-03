"""Password hashing + JWT helpers."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any

import jwt
from passlib.context import CryptContext

from app.core.config import get_settings
from app.models.user import Role

_pwd = CryptContext(schemes=["argon2"], deprecated="auto")

# The lowest-privilege non-admin role. S7-pre runs before the S1 enum
# collapse, so ``Role.user`` may not exist yet; fall back to ``student``.
# Once S1 widens the enum, ``normalize_role`` automatically resolves
# legacy/unknown strings to ``user`` with no code change here.
_NON_ADMIN_ROLE: Role = getattr(Role, "user", None) or Role.student


def normalize_role(raw: object) -> Role:
    """Map any legacy/unknown role string → ``Role`` for *display only*.

    ADR-0025 §D6 / FR-MIG-04. Authorization NEVER trusts this — the deps
    path re-reads the live ``User.role`` from the DB per request
    (``deps.py``). This helper exists so a straggler ``student``/
    ``instructor`` claim or ORM string renders as a known role in the UI
    without crashing serialization, and so no legacy/unknown value can ever
    normalize to ``admin``.

    * ``"admin"`` (case/space-insensitive) → ``Role.admin``
    * anything else (incl. ``None``, ``""``, ``"student"``, ``"instructor"``,
      garbage) → the lowest-privilege non-admin role
    """
    if isinstance(raw, Role):
        return Role.admin if raw == Role.admin else _coerce_non_admin(raw)
    text = str(raw).strip().lower() if raw is not None else ""
    if text == "admin":
        return Role.admin
    return _NON_ADMIN_ROLE


def _coerce_non_admin(role: Role) -> Role:
    """A known non-admin ``Role`` keeps its identity if it is still a valid
    enum member; otherwise collapses to the canonical non-admin role."""
    return role if role in Role.__members__.values() else _NON_ADMIN_ROLE


def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd.verify(plain, hashed)
    except ValueError:
        return False


def needs_rehash(hashed: str) -> bool:
    return _pwd.needs_update(hashed)


@dataclass(slots=True)
class TokenPair:
    access_token: str
    access_expires_at: int
    refresh_token: str
    refresh_expires_at: int


def create_access_token(
    *,
    subject: str,
    role: str,
    extra: dict[str, Any] | None = None,
    expires_in: int | None = None,
) -> tuple[str, int]:
    s = get_settings()
    now = int(time.time())
    exp = now + (expires_in or s.access_token_ttl_seconds)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "iat": now,
        "exp": exp,
        "jti": secrets.token_urlsafe(12),
        "iss": "lumen",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm=s.jwt_algorithm), exp


def decode_token(token: str) -> dict[str, Any]:
    s = get_settings()
    return jwt.decode(
        token, s.jwt_secret.get_secret_value(), algorithms=[s.jwt_algorithm], issuer="lumen"
    )


def new_refresh_token() -> tuple[str, str]:
    """Returns (plaintext_token, sha256_hash)."""
    import hashlib

    raw = secrets.token_urlsafe(48)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return raw, digest


def hash_refresh_token(token: str) -> str:
    import hashlib

    return hashlib.sha256(token.encode()).hexdigest()


def pwh_fingerprint(password_hash: str) -> str:
    """Stable short identifier derived from the argon2 hash tail.

    Used in single-use tokens (password reset, email change) to bind
    the token to the password that was current at mint time — rotating
    the password rotates the salt+digest tail, invalidating any
    outstanding token without needing server-side state.

    16 chars of an argon2 digest is still ~96 bits of entropy; collision
    with a different hash is implausible at any realistic user count.
    """
    return password_hash[-16:]
