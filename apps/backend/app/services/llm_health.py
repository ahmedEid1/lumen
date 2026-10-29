"""Cached LLM reachability probe behind ``GET /api/v1/health/llm``.

Why not ``/health/ready``. Ready is the api container healthcheck
(``docker-compose.prod.yml``: every 20 s, 2 s urlopen timeout, 5 retries) and
the deploy smoke gate. An LLM round-trip there would blow the 2 s budget on a
reasoning model, turn a vendor outage into an api restart loop / failed
deploy, and spend tokens ~4,300 times a day. Nothing in ``ready()`` may call
into this module.

Budget. At most ONE tiny upstream call per ``llm_health_probe_ttl_s``
fleet-wide: a Redis ``SET NX EX ttl`` lock elects the refresher across the
uvicorn workers, and the lock itself (not the cache write) is the rate limit.
Readers inside the window get the cached snapshot plus its age. Redis down →
a per-process memo (at most one call per TTL per worker, never one per
request). The probe client runs with ``max_retries=0`` so a failing upstream
still costs exactly one HTTP request.

Unmetered by design, like the BYOK validate probe
(``llm_credentials._run_validation``): no user, no ``llm_calls`` row, no
quota. Errors are reported as class / HTTP status / vendor code only — never
the vendor's raw message (ADR-0027 redaction rule).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as redis

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services import llm as llm_service

log = get_logger(__name__)

CACHE_KEY = "health:llm:v1"
LOCK_KEY = "health:llm:v1:lock"
# Tiny on purpose. A reasoning model (gpt-oss) may spend all of it on
# reasoning and return empty content with finish_reason="length"; that is
# still a served 2xx, which is all this probe asserts.
PROBE_MAX_TOKENS = 16
_PROBE_MESSAGES = [llm_service.ChatMessage(role="user", content="Reply with the word ok.")]
# Keep a stale snapshot this many TTLs so readers that lose the lock race
# still see the last result (with its age) instead of "unknown".
_STALE_KEEP_TTLS = 12

_memo: dict[str, Any] | None = None
_memo_lock = asyncio.Lock()


async def _run_probe() -> dict[str, Any]:
    """One tiny call to the PRIMARY platform model. Never raises."""
    s = get_settings()
    chain = llm_service.platform_model_chain()
    snap: dict[str, Any] = {
        "status": "disabled",
        "provider": s.llm_provider,
        "model": chain[0],
        "fallback_models": chain[1:],
        "latency_ms": None,
        "error_kind": None,
        "http_status": None,
        "error_code": None,
        "checked_at": datetime.now(UTC).isoformat(),
        "ts": time.time(),
    }
    if s.llm_provider == "noop":
        return snap
    timeout = float(s.llm_health_probe_timeout_s)
    provider = llm_service.build_platform_provider(
        chain[0], max_tokens=PROBE_MAX_TOKENS, timeout=timeout, max_retries=0
    )
    started = time.perf_counter()
    try:
        # The SDK timeout is what frees the to_thread worker; wait_for is the
        # backstop so this request can never hang past timeout + 2 s.
        await asyncio.wait_for(
            provider.chat_with_usage(_PROBE_MESSAGES, temperature=0.0), timeout=timeout + 2
        )
        snap["status"] = "ok"
    except Exception as exc:
        snap.update(
            status="down",
            error_kind=type(exc).__name__,
            http_status=llm_service.error_status(exc),
            error_code=llm_service.error_code(exc),
        )
    snap["latency_ms"] = int((time.perf_counter() - started) * 1000)
    fields = {k: snap[k] for k in ("status", "provider", "model", "latency_ms", "error_kind")}
    fields.update(http_status=snap["http_status"], error_code=snap["error_code"])
    if snap["status"] == "ok":
        log.info("llm_health_probe", **fields)
    else:
        log.warning("llm_health_probe", **fields)
    return snap


def _fresh(snap: dict[str, Any] | None, ttl: int) -> bool:
    return snap is not None and time.time() - float(snap.get("ts", 0)) < ttl


def _present(snap: dict[str, Any], ttl: int) -> dict[str, Any]:
    out = {k: v for k, v in snap.items() if k != "ts"}
    out["age_s"] = max(0, int(time.time() - float(snap.get("ts", 0))))
    out["ttl_s"] = ttl
    return out


async def _local_snapshot(ttl: int) -> dict[str, Any]:
    """Redis-down path: per-process memo, one probe per TTL per worker."""
    global _memo
    async with _memo_lock:
        if _memo is None or not _fresh(_memo, ttl):
            _memo = await _run_probe()
        return _memo


async def get_snapshot() -> dict[str, Any]:
    """Return the cached LLM health snapshot, refreshing at most once per TTL."""
    s = get_settings()
    # Floor: a TTL of 0 would send an upstream call on every public GET.
    ttl = max(60, int(s.llm_health_probe_ttl_s))
    snap: dict[str, Any] | None = None
    try:
        r = redis.Redis.from_url(s.redis_url, socket_timeout=1, socket_connect_timeout=1)
        try:
            raw = await r.get(CACHE_KEY)
            snap = json.loads(raw) if raw else None
            if not _fresh(snap, ttl) and await r.set(LOCK_KEY, "1", nx=True, ex=ttl):
                snap = await _run_probe()
                try:
                    await r.set(CACHE_KEY, json.dumps(snap), ex=ttl * _STALE_KEEP_TTLS)
                except redis.RedisError:
                    # The result never reached the cache: free the lock so the next
                    # request can publish one instead of seeing a stale snapshot
                    # (or "unknown") until the lock expires.
                    with contextlib.suppress(redis.RedisError):
                        await r.delete(LOCK_KEY)
        finally:
            with contextlib.suppress(redis.RedisError):
                await r.aclose()
    except (redis.RedisError, ValueError):
        # Raised only before a probe ran (get / lock / corrupt JSON), so this
        # never doubles the upstream call.
        log.warning("llm_health_cache_unavailable")
        snap = await _local_snapshot(ttl)
    if snap is None:
        # Another worker holds the lock and there is no earlier result yet.
        return {"status": "unknown", "reason": "probe_in_progress", "ttl_s": ttl}
    return _present(snap, ttl)


__all__ = ["CACHE_KEY", "LOCK_KEY", "PROBE_MAX_TOKENS", "get_snapshot"]
