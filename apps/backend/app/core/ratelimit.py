"""Rate limiting via slowapi.

In production / staging we point ``storage_uri`` at Redis so multiple API
replicas share a single token bucket. In tests we route to an in-memory
backend (``memory://``) so the suite doesn't depend on a running Redis.
Tests reset state between cases via ``reset_for_tests()``.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import Environment, get_settings


def _storage_uri() -> str:
    s = get_settings()
    return "memory://" if s.env == Environment.test else s.redis_url


limiter: Limiter = Limiter(
    key_func=get_remote_address,
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
        try:
            storage.reset()
        except Exception:  # noqa: BLE001 — be tolerant if the backend lacks reset()
            pass
