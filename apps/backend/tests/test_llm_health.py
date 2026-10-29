"""GET /api/v1/health/llm — cached, at most one upstream call per TTL.

Service-level tests are DB-free: Redis is a tiny in-memory fake and the
upstream call is a counting stub. The two HTTP tests use the normal
``client`` fixture.
"""

from __future__ import annotations

import time
from typing import ClassVar

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.services import llm_health


class _FakeRedis:
    store: ClassVar[dict[str, object]] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def aclose(self):
        return None


class _CacheWriteFailsRedis(_FakeRedis):
    """The lock SET succeeds, the cache SET fails (e.g. Redis at maxmemory)."""

    async def set(self, key, value, nx=False, ex=None):
        if key == llm_health.CACHE_KEY:
            raise llm_health.redis.ResponseError("OOM command not allowed")
        return await super().set(key, value, nx=nx, ex=ex)

    async def delete(self, key):
        self.store.pop(key, None)
        return 1


class _DownRedis(_FakeRedis):
    async def get(self, key):
        raise llm_health.redis.ConnectionError("down")


@pytest.fixture
def probe_calls(monkeypatch):
    """Count upstream probes; each returns a fresh ok snapshot."""
    calls: list[float] = []

    async def _fake_probe():
        calls.append(time.time())
        return {"status": "ok", "provider": "openai", "model": "m", "ts": time.time()}

    monkeypatch.setattr(llm_health, "_run_probe", _fake_probe)
    monkeypatch.setattr(llm_health, "_memo", None)
    _FakeRedis.store = {}
    return calls


async def test_one_probe_per_ttl_across_requests(monkeypatch, probe_calls) -> None:
    monkeypatch.setattr(llm_health.redis.Redis, "from_url", lambda *a, **k: _FakeRedis())
    for _ in range(5):
        snap = await llm_health.get_snapshot()
    assert len(probe_calls) == 1
    assert snap["status"] == "ok"
    assert snap["ttl_s"] == get_settings().llm_health_probe_ttl_s
    assert "ts" not in snap and snap["age_s"] >= 0


async def test_lock_holder_elsewhere_means_no_probe(monkeypatch, probe_calls) -> None:
    _FakeRedis.store = {llm_health.LOCK_KEY: "1"}
    monkeypatch.setattr(llm_health.redis.Redis, "from_url", lambda *a, **k: _FakeRedis())
    snap = await llm_health.get_snapshot()
    assert probe_calls == []
    assert snap["status"] == "unknown"


async def test_redis_down_falls_back_to_process_memo(monkeypatch, probe_calls) -> None:
    monkeypatch.setattr(llm_health.redis.Redis, "from_url", lambda *a, **k: _DownRedis())
    for _ in range(3):
        snap = await llm_health.get_snapshot()
    assert len(probe_calls) == 1
    assert snap["status"] == "ok"


async def test_noop_provider_reports_disabled_without_a_call(monkeypatch) -> None:
    from unittest.mock import patch

    s = get_settings()
    with patch.object(s, "llm_provider", "noop"):
        snap = await llm_health._run_probe()
    assert snap["status"] == "disabled"
    assert snap["latency_ms"] is None


async def test_probe_reports_status_code_never_raw_message(monkeypatch) -> None:
    class _NotFound(Exception):
        status_code = 404
        code = "model_not_found"

    class _Provider:
        async def chat_with_usage(self, messages, temperature=0.2):
            raise _NotFound("req_LEAKME The model `x` does not exist")

    seen: dict = {}

    def _build(model, **kwargs):
        seen.update(kwargs, model=model)
        return _Provider()

    from unittest.mock import patch

    s = get_settings()
    monkeypatch.setattr(llm_health.llm_service, "build_platform_provider", _build)
    with patch.object(s, "llm_provider", "openai"), patch.object(s, "llm_model", "x"):
        snap = await llm_health._run_probe()
    assert snap["status"] == "down"
    assert (snap["http_status"], snap["error_code"]) == (404, "model_not_found")
    assert "LEAKME" not in str(snap)
    # One tiny request: small max_tokens, no SDK retries.
    assert seen["max_tokens"] == llm_health.PROBE_MAX_TOKENS
    assert seen["max_retries"] == 0


# ---------- HTTP ----------


async def test_llm_endpoint_503_only_when_down(client: AsyncClient, monkeypatch) -> None:
    async def _down():
        return {"status": "down", "model": "m", "age_s": 1, "ttl_s": 300}

    monkeypatch.setattr(llm_health, "get_snapshot", _down)
    r = await client.get("/api/v1/health/llm")
    assert r.status_code == 503
    assert r.json()["status"] == "down"


async def test_ready_never_touches_the_llm(client: AsyncClient, monkeypatch) -> None:
    async def _boom():  # pragma: no cover - must not be called
        raise AssertionError("/health/ready must not probe the LLM")

    monkeypatch.setattr(llm_health, "get_snapshot", _boom)
    monkeypatch.setattr(llm_health, "_run_probe", _boom)
    r = await client.get("/api/v1/health/ready")
    assert r.status_code in (200, 503)
    assert set(r.json()["checks"]) == {"db", "redis"}


async def test_failed_cache_write_releases_the_lock(monkeypatch, probe_calls) -> None:
    monkeypatch.setattr(llm_health.redis.Redis, "from_url", lambda *a, **k: _CacheWriteFailsRedis())
    snap = await llm_health.get_snapshot()
    assert snap["status"] == "ok"  # this request still answers with its own probe
    assert llm_health.LOCK_KEY not in _CacheWriteFailsRedis.store  # the next one may publish
