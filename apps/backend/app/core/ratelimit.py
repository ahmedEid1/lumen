"""Rate limiting via slowapi.

In production / staging we point ``storage_uri`` at Redis so multiple API
replicas share a single token bucket. In tests we route to an in-memory
backend (``memory://``) so the suite doesn't depend on a running Redis.
Tests reset state between cases via ``reset_for_tests()``.

Key derivation prefers a stable user identity (``sub`` from a valid
JWT Authorization header, or a hash of the auth cookie) over the
remote IP. This means a NAT'd network of legitimate learners
(office, coffee shop) doesn't share a single bucket — one noisy
neighbour can't lock out everyone behind the gateway. Anonymous
requests still key on IP because that's the best identity we have.
"""

from __future__ import annotations

import contextlib
import hashlib

import jwt
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import Environment, get_settings


def _storage_uri() -> str:
    s = get_settings()
    return "memory://" if s.env == Environment.test else s.redis_url


def _identity_key(request: Request) -> str:
    """User-aware key with IP fallback.

    Tries (in order):
      1. JWT ``sub`` decoded from the Authorization header. We accept
         signature failures silently — anything not-a-valid-token
         degrades to the IP fallback rather than raising mid-request.
      2. SHA-256 prefix of the auth cookie. We don't decode the cookie
         (it's the raw JWT under the hood); hashing is enough to bucket
         sessions consistently without needing the secret here.
      3. The remote address. Old behaviour.
    """
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth.split(None, 1)[1]
        try:
            s = get_settings()
            payload = jwt.decode(
                token,
                s.jwt_secret.get_secret_value(),
                algorithms=[s.jwt_algorithm],
            )
            sub = str(payload.get("sub", "")).strip()
            if sub:
                return f"user:{sub}"
        except jwt.PyJWTError:
            pass
    cookie = (
        request.cookies.get("__Host-access")
        or request.cookies.get("access")
        or ""
    )
    if cookie:
        return "sess:" + hashlib.sha256(cookie.encode()).hexdigest()[:16]
    return f"ip:{get_remote_address(request)}"


limiter: Limiter = Limiter(
    key_func=_identity_key,
    storage_uri=_storage_uri(),
    headers_enabled=True,
)


def reset_for_tests() -> None:
    """Clear the limiter's storage so buckets don't leak across tests.

    We mutate the existing limiter rather than rebuilding it because
    ``@limiter.limit(...)`` decorators captured the original instance at
    import time.
    """
    storage = getattr(limiter, "_storage", None)
    if storage is not None and hasattr(storage, "reset"):
        # be tolerant if the backend lacks reset()
        with contextlib.suppress(Exception):
            storage.reset()
