"""Have I Been Pwned breach-list check via k-anonymity.

Sends only the first 5 hex chars of the password's SHA-1 to HIBP and
checks the returned suffix list locally — the full hash and the
password itself never leave the process. Gated by
``settings.hibp_enabled``; disabled by default so a fresh checkout
doesn't perform third-party callouts during ``make test``.

Failure mode is *fail-open*: a HIBP outage or timeout returns False
(don't block the password) and logs a warning. Refusing to let users
register because an external API is down would be its own incident,
and the rest of the password policy (length + character classes,
iter 39) is still enforced.
"""

from __future__ import annotations

import hashlib

import httpx

from app.core.config import get_settings
from app.core.errors import ValidationAppError
from app.core.logging import get_logger

log = get_logger(__name__)


async def is_pwned(password: str) -> bool:
    """Return True iff HIBP reports this exact password in any breach.

    The call is short-circuited when ``hibp_enabled`` is False, so test
    runs and air-gapped deployments never touch the network.
    """
    settings = get_settings()
    if not settings.hibp_enabled:
        return False

    # k-anonymity: hash → split into 5-char prefix + 35-char suffix.
    digest = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    url = f"{settings.hibp_api_base.rstrip('/')}/range/{prefix}"

    try:
        async with httpx.AsyncClient(timeout=settings.hibp_timeout_seconds) as client:
            res = await client.get(url, headers={"Add-Padding": "true"})
        if res.status_code != 200:
            log.warning("hibp_unexpected_status", status=res.status_code)
            return False
        # Each line is "<suffix>:<count>". Padding entries have count=0
        # — those exist only to defeat traffic analysis and must be
        # ignored when checking whether *our* password is present.
        for line in res.text.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            candidate, _, count_str = line.partition(":")
            if candidate.strip().upper() != suffix:
                continue
            try:
                count = int(count_str.strip())
            except ValueError:
                continue
            return count > 0
        return False
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        # Fail open: don't make our login flow brittle on a third-party
        # outage. The structural strength checks still apply.
        log.warning("hibp_request_failed", error=str(exc))
        return False


async def assert_not_pwned(password: str) -> None:
    """Raise if the password is in the HIBP breach list.

    No-op when ``hibp_enabled=False`` (the underlying check returns
    False without hitting the network), so callers don't need their
    own feature-flag branch — they get a clean "policy enforced" or
    "policy disabled" outcome without leaking the gate detail.
    """
    if await is_pwned(password):
        raise ValidationAppError(
            "This password has appeared in a known data breach. "
            "Please choose a different one.",
            code="auth.password_breached",
        )
