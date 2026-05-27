"""Python wrappers around the L21-Sec Lua scripts.

Each wrapper:

1. Loads the script once at module import time via
   ``redis.Redis.register_script`` so subsequent calls use the
   server-side EVALSHA cache.
2. Exposes a typed async function so callers don't need to know
   Redis-py specifics.
3. Returns the tagged ``(ok, tag)`` shape directly so callers can
   structlog the tag (``user_cap`` vs ``ip_cap`` etc.) for ops
   dashboards.

The orchestrator (L21a) calls ``reserve_cost`` at POST-handler time;
``reconcile_cost`` runs on turn-complete and on sweep; the concurrency
pair brackets the per-turn execution.

L21-Sec ships only the wrappers + tests. The callers land in L21a.
"""

from __future__ import annotations

from pathlib import Path

import redis.asyncio as redis

# Microcents: USD * 1_000_000. Integer math throughout to dodge the
# IEEE-754 drift INCRBYFLOAT would introduce.
USD_TO_MICROCENTS = 1_000_000

_HERE = Path(__file__).parent / "lua"


def _load_script(name: str) -> str:
    return (_HERE / name).read_text(encoding="utf-8")


RESERVE_COST_LUA = _load_script("reserve_cost.lua")
RECONCILE_COST_LUA = _load_script("reconcile_cost.lua")
CHECK_CONCURRENCY_LUA = _load_script("check_concurrency.lua")
RELEASE_CONCURRENCY_LUA = _load_script("release_concurrency.lua")


async def reserve_cost(
    client: redis.Redis,
    *,
    user_key: str,
    ip_key: str,
    global_key: str,
    estimate_microcents: int,
    max_user_microcents: int,
    max_ip_microcents: int,
    max_global_microcents: int,
    ttl_seconds: int = 86400,
) -> tuple[bool, str]:
    """Attempt to reserve ``estimate_microcents`` against the three buckets.

    Returns ``(ok, tag)`` where ``tag`` is "ok" on success or one of
    "user_cap" / "ip_cap" / "global_cap" / "invalid_estimate" on
    rejection. Caller maps the tag to a 4xx + ``error_code``.
    """
    res = await client.eval(
        RESERVE_COST_LUA,
        3,
        user_key,
        ip_key,
        global_key,
        estimate_microcents,
        max_user_microcents,
        max_ip_microcents,
        max_global_microcents,
        ttl_seconds,
    )
    ok, tag = res
    tag_str = tag.decode() if isinstance(tag, bytes) else str(tag)
    return bool(int(ok)), tag_str


async def reconcile_cost(
    client: redis.Redis,
    *,
    user_key: str,
    ip_key: str,
    global_key: str,
    delta_microcents: int,
    max_delta_magnitude_microcents: int = 100_000_000,
) -> tuple[bool, str]:
    """Adjust a prior reservation by ``delta_microcents``.

    Positive delta = the turn spent more than it reserved; negative
    delta = release the unspent portion. The magnitude cap defends
    against caller bugs (e.g. passing dollars instead of microcents
    would otherwise blow the bucket by 6 orders of magnitude).
    """
    res = await client.eval(
        RECONCILE_COST_LUA,
        3,
        user_key,
        ip_key,
        global_key,
        delta_microcents,
        max_delta_magnitude_microcents,
    )
    ok, tag = res
    tag_str = tag.decode() if isinstance(tag, bytes) else str(tag)
    return bool(int(ok)), tag_str


async def check_concurrency(
    client: redis.Redis,
    *,
    user_key: str,
    max_concurrent: int = 3,
    ttl_seconds: int = 300,
) -> tuple[bool, int]:
    """Acquire one slot on the per-user concurrent-streams counter.

    Returns ``(ok, current_count)``. ``ok=True`` means a slot was
    acquired and the caller must eventually call ``release_concurrency``.
    """
    res = await client.eval(
        CHECK_CONCURRENCY_LUA,
        1,
        user_key,
        max_concurrent,
        ttl_seconds,
    )
    ok, current = res
    return bool(int(ok)), int(current)


async def release_concurrency(
    client: redis.Redis,
    *,
    user_key: str,
) -> int:
    """Release a per-user slot. Returns the new counter value.

    Safe to call multiple times — the script floors at zero.
    """
    res = await client.eval(RELEASE_CONCURRENCY_LUA, 1, user_key)
    return int(res[0])
