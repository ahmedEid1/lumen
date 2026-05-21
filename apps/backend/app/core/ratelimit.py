"""Rate limiting via slowapi (Redis backend)."""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings

_settings = get_settings()
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_settings.redis_url,
    headers_enabled=True,
)
