"""In-memory 429 counter for the H7 observability dashboard.

Slowapi exposes per-bucket headers (``X-RateLimit-Remaining`` etc.)
but no aggregate counter — useful in production we want to see *which*
endpoints are hot enough to trip the limiter and how often. The
proper home for this is Prometheus + an ``/admin/observability``
roll-up; H6 ships the simplest thing that works in a single process:
a ring-buffered list of ``(timestamp, path)`` tuples that the
read-only admin endpoint groups by path within a sliding window.

This is intentionally **not Redis-backed**. The demo deploy runs a
single VM (AWS t4g.small per `docs/deployment/aws-vps.md`), so a
process-local counter is honest about the data: it resets on every
redeploy. If Lumen later scales out, the endpoint switches to a Redis
``ZADD`` / ``ZRANGEBYSCORE`` pair without breaking the response shape.

The counter is process-wide and async-safe. Concurrent ``record_*``
calls share a single ``deque``; deque ``append`` is documented as
thread-safe, and FastAPI's single-threaded async runtime means we
never see true parallel access anyway.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Iterable

# Hard upper bound on the buffer size. At one 429 per second sustained
# that's a ~2.8h history; under normal load the time-window filter
# evicts old entries long before we hit the cap. The bound exists so
# a misconfigured client spamming requests can't drive unbounded memory.
_MAX_EVENTS = 10_000

# Default lookback for queries that don't pass ``since``. Matches the
# spec wording: "429 counts for the last hour".
_DEFAULT_WINDOW_SECONDS = 3600

# Each event is a ``(epoch_seconds, path)`` tuple. Deque + maxlen gives
# O(1) append and bounded memory; the linear scan on read is fine for
# the ~10k-event upper bound.
_events: deque[tuple[float, str]] = deque(maxlen=_MAX_EVENTS)


def record_rate_limited(path: str) -> None:
    """Append a 429 event for ``path`` to the in-memory buffer."""
    if not path:
        path = "<unknown>"
    _events.append((time.time(), path))


def counts_since(since_epoch_seconds: float | None = None) -> dict[str, int]:
    """Return ``{endpoint: count}`` for events newer than ``since``.

    Defaults to a 1-hour rolling window. Returns an empty dict when the
    buffer is empty so the JSON envelope stays stable for the admin UI.
    """
    cutoff = since_epoch_seconds if since_epoch_seconds is not None else time.time() - _DEFAULT_WINDOW_SECONDS
    out: dict[str, int] = {}
    # Snapshot the deque so a concurrent append doesn't tweak the
    # iteration. ``list(deque)`` is the cheapest way to do that and is
    # documented as atomic at the C level for the deque type.
    for ts, path in list(_events):
        if ts >= cutoff:
            out[path] = out.get(path, 0) + 1
    return out


def reset() -> None:
    """Empty the counter — tests use this between cases."""
    _events.clear()


def snapshot() -> list[tuple[float, str]]:
    """Return a copy of the current event buffer (tests only)."""
    return list(_events)


def _iter_events() -> Iterable[tuple[float, str]]:  # pragma: no cover — debug helper
    yield from list(_events)
