"""Lua cost / concurrency scripts (L21-Sec).

Hits a real Redis (conftest exposes one). Tests are skipped if Redis
isn't reachable so a quick subset run can succeed without docker.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import redis.asyncio as redis

from app.core.config import get_settings
from app.core.cost_scripts import (
    USD_TO_MICROCENTS,
    check_concurrency,
    reconcile_cost,
    release_concurrency,
    reserve_cost,
)


@pytest.fixture()
async def r() -> redis.Redis:
    """Per-test Redis client. Each test gets unique keys so xdist
    workers don't trample each other."""
    client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    yield client
    await client.aclose()


def _keys() -> tuple[str, str, str]:
    """Generate three unique cost-bucket keys."""
    nonce = uuid.uuid4().hex[:8]
    return (
        f"cost:user:{nonce}",
        f"cost:ip:{nonce}",
        f"cost:global:{nonce}",
    )


# ----------------------------------------------------------------
# reserve_cost
# ----------------------------------------------------------------


async def test_reserve_cost_below_cap_succeeds(r: redis.Redis) -> None:
    user_key, ip_key, global_key = _keys()
    ok, tag = await reserve_cost(
        r,
        user_key=user_key,
        ip_key=ip_key,
        global_key=global_key,
        estimate_microcents=10_000,  # 1 cent
        max_user_microcents=USD_TO_MICROCENTS,
        max_ip_microcents=USD_TO_MICROCENTS,
        max_global_microcents=10 * USD_TO_MICROCENTS,
    )
    assert ok is True
    assert tag == "ok"


async def test_reserve_cost_above_user_cap_fails(r: redis.Redis) -> None:
    user_key, ip_key, global_key = _keys()
    ok, tag = await reserve_cost(
        r,
        user_key=user_key,
        ip_key=ip_key,
        global_key=global_key,
        estimate_microcents=2 * USD_TO_MICROCENTS,
        max_user_microcents=USD_TO_MICROCENTS,
        max_ip_microcents=10 * USD_TO_MICROCENTS,
        max_global_microcents=100 * USD_TO_MICROCENTS,
    )
    assert ok is False
    assert tag == "user_cap"


async def test_reserve_cost_above_ip_cap_fails(r: redis.Redis) -> None:
    user_key, ip_key, global_key = _keys()
    ok, tag = await reserve_cost(
        r,
        user_key=user_key,
        ip_key=ip_key,
        global_key=global_key,
        estimate_microcents=2 * USD_TO_MICROCENTS,
        max_user_microcents=10 * USD_TO_MICROCENTS,
        max_ip_microcents=USD_TO_MICROCENTS,
        max_global_microcents=100 * USD_TO_MICROCENTS,
    )
    assert ok is False
    assert tag == "ip_cap"


async def test_reserve_cost_invalid_estimate(r: redis.Redis) -> None:
    user_key, ip_key, global_key = _keys()
    ok, tag = await reserve_cost(
        r,
        user_key=user_key,
        ip_key=ip_key,
        global_key=global_key,
        estimate_microcents=0,
        max_user_microcents=USD_TO_MICROCENTS,
        max_ip_microcents=USD_TO_MICROCENTS,
        max_global_microcents=USD_TO_MICROCENTS,
    )
    assert ok is False
    assert tag == "invalid_estimate"


async def test_reserve_cost_ttl_only_on_first_increment(r: redis.Redis) -> None:
    """The 24h window starts at first creation; subsequent increments
    must preserve the remaining TTL (plan-v7 §V6-F6)."""
    user_key, ip_key, global_key = _keys()
    await reserve_cost(
        r,
        user_key=user_key,
        ip_key=ip_key,
        global_key=global_key,
        estimate_microcents=1_000,
        max_user_microcents=USD_TO_MICROCENTS,
        max_ip_microcents=USD_TO_MICROCENTS,
        max_global_microcents=USD_TO_MICROCENTS,
        ttl_seconds=86400,
    )
    ttl_after_first = await r.ttl(user_key)
    # Two short waits + a second reserve. The TTL should have
    # decreased, not been bumped back to ~86400.
    await asyncio.sleep(1.2)
    await reserve_cost(
        r,
        user_key=user_key,
        ip_key=ip_key,
        global_key=global_key,
        estimate_microcents=1_000,
        max_user_microcents=USD_TO_MICROCENTS,
        max_ip_microcents=USD_TO_MICROCENTS,
        max_global_microcents=USD_TO_MICROCENTS,
        ttl_seconds=86400,
    )
    ttl_after_second = await r.ttl(user_key)
    assert ttl_after_second < ttl_after_first


# ----------------------------------------------------------------
# reconcile_cost
# ----------------------------------------------------------------


async def test_reconcile_cost_negative_delta_decrements(r: redis.Redis) -> None:
    user_key, ip_key, global_key = _keys()
    await reserve_cost(
        r,
        user_key=user_key,
        ip_key=ip_key,
        global_key=global_key,
        estimate_microcents=10_000,
        max_user_microcents=USD_TO_MICROCENTS,
        max_ip_microcents=USD_TO_MICROCENTS,
        max_global_microcents=USD_TO_MICROCENTS,
    )
    ok, tag = await reconcile_cost(
        r,
        user_key=user_key,
        ip_key=ip_key,
        global_key=global_key,
        delta_microcents=-5_000,
    )
    assert ok is True
    assert tag == "ok"
    assert int(await r.get(user_key) or 0) == 5_000


async def test_reconcile_cost_floors_at_zero_and_dels(r: redis.Redis) -> None:
    user_key, ip_key, global_key = _keys()
    await reserve_cost(
        r,
        user_key=user_key,
        ip_key=ip_key,
        global_key=global_key,
        estimate_microcents=1_000,
        max_user_microcents=USD_TO_MICROCENTS,
        max_ip_microcents=USD_TO_MICROCENTS,
        max_global_microcents=USD_TO_MICROCENTS,
    )
    # Release more than we reserved — should floor at zero and DEL
    # the key (plan-v7 §V7-F5).
    await reconcile_cost(
        r,
        user_key=user_key,
        ip_key=ip_key,
        global_key=global_key,
        delta_microcents=-10_000,
    )
    assert await r.exists(user_key) == 0


async def test_reconcile_cost_absurd_delta_rejected(r: redis.Redis) -> None:
    user_key, ip_key, global_key = _keys()
    ok, tag = await reconcile_cost(
        r,
        user_key=user_key,
        ip_key=ip_key,
        global_key=global_key,
        delta_microcents=10_000_000_000,  # $10,000
        max_delta_magnitude_microcents=USD_TO_MICROCENTS,
    )
    assert ok is False
    assert tag == "delta_too_large"


# ----------------------------------------------------------------
# check_concurrency + release_concurrency
# ----------------------------------------------------------------


async def test_check_concurrency_below_cap(r: redis.Redis) -> None:
    user_key = f"concurrent:user:{uuid.uuid4().hex[:8]}"
    ok, count = await check_concurrency(r, user_key=user_key, max_concurrent=3)
    assert ok is True
    assert count == 1


async def test_check_concurrency_caps_at_max(r: redis.Redis) -> None:
    user_key = f"concurrent:user:{uuid.uuid4().hex[:8]}"
    for _ in range(3):
        ok, _ = await check_concurrency(r, user_key=user_key, max_concurrent=3)
        assert ok is True
    # Fourth must fail.
    ok, count = await check_concurrency(r, user_key=user_key, max_concurrent=3)
    assert ok is False
    assert count == 3


async def test_release_concurrency_decrements(r: redis.Redis) -> None:
    user_key = f"concurrent:user:{uuid.uuid4().hex[:8]}"
    await check_concurrency(r, user_key=user_key, max_concurrent=3)
    await check_concurrency(r, user_key=user_key, max_concurrent=3)
    new_val = await release_concurrency(r, user_key=user_key)
    assert new_val == 1


async def test_release_concurrency_floors_at_zero(r: redis.Redis) -> None:
    user_key = f"concurrent:user:{uuid.uuid4().hex[:8]}"
    # Release without any prior acquire — must not create a negative
    # counter (plan-v7 §V6-F13 — release_concurrency_floored_at_zero).
    new_val = await release_concurrency(r, user_key=user_key)
    assert new_val == 0
    assert await r.exists(user_key) == 0
