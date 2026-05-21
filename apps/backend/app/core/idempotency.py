"""Idempotency-Key support for mutating endpoints.

Opt-in via the ``Idempotency-Key`` request header on POST/PUT/PATCH/
DELETE. The cache key is derived from the user identity (best-effort:
sub claim from the JWT, falling back to client IP) plus method, path,
and the verbatim key string. Cached entries pin the request body's
SHA-256 alongside the response, so:

* same key + same body within the TTL → replay the cached response;
* same key + *different* body → 422 ``idempotency.conflict`` (the
  client is replaying a key it already burned on a different payload,
  which RFC draft-ietf-httpapi-idempotency-key-header treats as
  always-an-error).

Cache backed by Redis with a 24-hour TTL (the lower bound the draft
RFC suggests). Responses larger than ``MAX_CACHE_BYTES`` are not
cached — the request still runs, the result still ships, but a replay
will re-execute. Better that than letting the cache grow without
bound or hold extremely large blobs.

WebSocket upgrades, multipart/form-data, and the long-poll
``/metrics`` endpoint are skipped.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import redis.asyncio as redis_async
from fastapi.responses import ORJSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Message

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


CACHE_TTL_SECONDS = 60 * 60 * 24  # 24h — RFC draft lower bound
MAX_CACHE_BYTES = 256 * 1024     # don't pin huge bodies in Redis
MAX_KEY_LEN = 200
_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Paths we never want to memoise — login auths, the metrics scrape,
# and any presign call that mints a new opaque URL on every hit.
_SKIP_PATH_PREFIXES = (
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
    "/metrics",
)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """RFC-shaped Idempotency-Key middleware."""

    def __init__(self, app, redis_client=None):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._redis = redis_client  # lazy if None

    async def _get_redis(self) -> redis_async.Redis:
        if self._redis is None:
            self._redis = redis_async.Redis.from_url(
                get_settings().redis_url, decode_responses=False
            )
        return self._redis

    async def dispatch(self, request: Request, call_next):
        if request.method not in _MUTATING:
            return await call_next(request)
        key = request.headers.get("idempotency-key")
        if not key:
            return await call_next(request)
        if len(key) > MAX_KEY_LEN:
            return ORJSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "idempotency.bad_key",
                        "message": "Idempotency-Key too long",
                        "request_id": getattr(request.state, "request_id", None),
                    }
                },
            )
        path = request.url.path
        if any(path.startswith(p) for p in _SKIP_PATH_PREFIXES):
            return await call_next(request)
        # multipart uploads (file bodies) — skip; the body is the data
        # and we don't want to pin it in Redis or read it twice.
        ct = (request.headers.get("content-type") or "").lower()
        if ct.startswith("multipart/form-data"):
            return await call_next(request)

        # Read and stash the body so the downstream handler can still
        # parse it. Starlette consumes the receive channel once;
        # ``_replay_body`` puts the bytes back.
        body = await request.body()
        body_hash = hashlib.sha256(body).hexdigest()
        user_key = _identity(request)
        cache_key = f"idemp:{user_key}:{request.method}:{path}:{key}"

        try:
            r = await self._get_redis()
            cached = await r.get(cache_key)
        except Exception:  # Redis being down is non-fatal
            log.warning("idempotency_redis_get_failed", path=path)
            cached = None

        if cached is not None:
            try:
                entry: dict[str, Any] = json.loads(cached)
            except (ValueError, TypeError):
                entry = {}
            if entry.get("body_hash") != body_hash:
                return ORJSONResponse(
                    status_code=422,
                    content={
                        "error": {
                            "code": "idempotency.conflict",
                            "message": (
                                "Idempotency-Key was reused with a different request body"
                            ),
                            "request_id": getattr(request.state, "request_id", None),
                        }
                    },
                )
            return _replay_response(entry)

        # Re-inject the consumed body so downstream sees it as normal.
        await _replay_body(request, body)

        # Capture the response body via send-spy so we can cache it.
        captured: dict[str, Any] = {"status": 200, "headers": [], "body": b""}

        async def _send_spy(msg: Message) -> None:
            if msg["type"] == "http.response.start":
                captured["status"] = msg.get("status", 200)
                captured["headers"] = msg.get("headers", [])
            elif msg["type"] == "http.response.body":
                captured["body"] += msg.get("body", b"")

        response = await call_next(request)
        # call_next already returned a Response; iterate its body to
        # capture, then re-stream it to the actual client.
        chunks: list[bytes] = []
        async for chunk in response.body_iterator:  # type: ignore[attr-defined]
            chunks.append(chunk)
        body_bytes = b"".join(chunks)

        # Cache only successful 2xx — caching a transient 5xx would
        # turn a flaky upstream into a permanent failure for the user.
        if 200 <= response.status_code < 300 and len(body_bytes) <= MAX_CACHE_BYTES:
            entry = {
                "status": response.status_code,
                # Strip per-response headers that don't make sense to
                # replay (request-id, content-length will be recomputed).
                "headers": [
                    (k.decode() if isinstance(k, bytes) else k,
                     v.decode() if isinstance(v, bytes) else v)
                    for k, v in response.raw_headers
                    if (k if isinstance(k, str) else k.decode()).lower()
                    not in {"x-request-id", "content-length", "set-cookie"}
                ],
                "body_hash": body_hash,
                # Iter 115: `GZipMiddleware` (registered earlier in the
                # chain) can gzip-encode the body before we see it.
                # Storing with `utf-8 + errors=replace` silently corrupts
                # binary data; the replay then ships a `gzip`
                # Content-Encoding with garbage bytes and httpx clients
                # fail `zlib.error: incorrect header check`. latin-1
                # is 1:1 for every byte 0–255 so the body round-trips
                # losslessly through JSON storage.
                "body": body_bytes.decode("latin-1"),
            }
            try:
                r = await self._get_redis()
                await r.set(cache_key, json.dumps(entry), ex=CACHE_TTL_SECONDS)
            except Exception:
                log.warning("idempotency_redis_set_failed", path=path)

        return Response(
            content=body_bytes,
            status_code=response.status_code,
            headers=dict(response.headers),
        )


async def _replay_body(request: Request, body: bytes) -> None:
    """Re-inject the consumed body so downstream sees it again."""
    sent = {"value": False}

    async def _receive() -> Message:
        if sent["value"]:
            return {"type": "http.disconnect"}
        sent["value"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    request._receive = _receive  # type: ignore[attr-defined]


def _replay_response(entry: dict[str, Any]) -> Response:
    body = entry.get("body", "")
    if isinstance(body, str):
        # Iter 115: paired with the latin-1 encode at cache time
        # so gzip-encoded bytes round-trip losslessly.
        body = body.encode("latin-1")
    headers = {k: v for k, v in entry.get("headers", [])}
    # Tell downstream observability this was a replay so a sudden
    # burst of identical responses doesn't look like a bug.
    headers["Idempotent-Replayed"] = "true"
    return Response(
        content=body,
        status_code=int(entry.get("status", 200)),
        headers=headers,
    )


def _identity(request: Request) -> str:
    """Best-effort user identifier for cache scoping.

    We avoid actually verifying the JWT here (the dep system handles
    that), and instead use a stable hash of the Authorization or auth
    cookie so anonymous-with-IP and authed-with-Bearer don't share
    cache space. Falls back to client IP for fully anonymous.
    """
    auth = request.headers.get("authorization") or ""
    if auth:
        return hashlib.sha256(auth.encode()).hexdigest()[:16]
    cookie = (
        request.cookies.get("__Host-access")
        or request.cookies.get("access")
        or ""
    )
    if cookie:
        return hashlib.sha256(cookie.encode()).hexdigest()[:16]
    return f"ip:{request.client.host if request.client else 'unknown'}"
