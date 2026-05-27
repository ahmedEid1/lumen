"""Redis Streams helpers (L21a) for tutor turn SSE.

Three primitives:

- :func:`emit_event` — XADD with MAXLEN cap. Producer (Celery task)
  calls this once per event emitted while orchestrating a turn.
- :func:`consume_stream` — XREAD with BLOCK; yields entries
  one-by-one for the SSE handler.
- :func:`check_trim` — pre-subscribe check for stale Last-Event-ID
  per plan-v7 §V7-F4. Returns a tuple `(needs_resync, first_kept_id)`
  the handler can use to emit a `trim_detected` event before
  falling back to the /status path.

Stream key shape: ``tutor:turn:{turn_id}``. TTL is set externally
(on `turn_complete` from the orchestrator + an orphan-cleanup beat
job for stuck streams). MAXLEN ~ 500 caps memory at ~150 KB / stream.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as redis

MAX_STREAM_ENTRIES = 500
DEFAULT_BLOCK_MS = 30_000


def stream_key(turn_id: str) -> str:
    """Canonical stream key for a turn."""
    return f"tutor:turn:{turn_id}"


async def emit_event(
    client: redis.Redis,
    *,
    turn_id: str,
    event: str,
    data: dict[str, Any] | None = None,
) -> str:
    """XADD one event onto the turn's stream.

    Returns the assigned entry id (``<ms>-<seq>``). The producer
    keeps this id so it can correlate retry / inspection logs to
    specific Redis entries.
    """
    payload = json.dumps(data or {})
    entry_id = await client.xadd(
        stream_key(turn_id),
        {"event": event, "data": payload},
        maxlen=MAX_STREAM_ENTRIES,
        approximate=True,
    )
    return entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)


async def check_trim(
    client: redis.Redis,
    *,
    turn_id: str,
    last_event_id: str,
) -> tuple[bool, str | None]:
    """Detect whether a Last-Event-ID has been trimmed off the stream.

    Plan-v7 §V7-F4: ``XREAD`` from an id older than the stream's
    first-retained entry silently returns the NEXT entries, hiding
    the gap. Before subscribing, look up the first retained entry
    via XRANGE; if our offset is older, the consumer needs to resync.

    Returns ``(needs_resync, first_kept_id)``:
    - ``(False, None)`` — empty stream or our offset is at/after the
      first retained entry. Caller can XREAD normally.
    - ``(True, None)`` — stream is empty (expired / never existed).
      Caller should fall back to the status-poll path.
    - ``(True, "<id>")`` — our offset has been trimmed. Caller should
      emit a ``trim_detected`` event, then resync from status.
    """
    if not last_event_id or last_event_id == "0":
        return False, None
    rng = await client.xrange(stream_key(turn_id), "-", "+", count=1)
    if not rng:
        return True, None
    first_id_raw = rng[0][0]
    first_id = first_id_raw.decode() if isinstance(first_id_raw, bytes) else str(first_id_raw)
    if _stream_id_lt(last_event_id, first_id):
        return True, first_id
    return False, first_id


def _stream_id_lt(a: str, b: str) -> bool:
    """Compare two stream IDs (``<ms>-<seq>``) numerically.

    Plan-v7 §V7-F12: lexicographic compare is wrong because '9-0' >
    '10-0' textually. Split + cast to int per component.
    """

    def _parts(s: str) -> tuple[int, int]:
        if "-" not in s:
            return (int(s), 0)
        ms, seq = s.split("-", 1)
        return (int(ms), int(seq))

    return _parts(a) < _parts(b)


async def consume_stream(
    client: redis.Redis,
    *,
    turn_id: str,
    last_event_id: str = "$",
    block_ms: int = DEFAULT_BLOCK_MS,
) -> AsyncIterator[tuple[str, str, dict[str, Any]]]:
    """Yield ``(entry_id, event_name, data_dict)`` triples as they arrive.

    Starts from ``last_event_id`` (``$`` = "only new entries from now").
    The caller is responsible for breaking the loop on terminal events
    (``turn_complete`` / ``turn_failed`` / ``turn_aborted``); this
    helper just keeps reading until the stream is gone.

    Returns when the stream key disappears (TTL fired) or when the
    XREAD call hits zero entries inside the block window (read as
    "idle, hand back to the handler"). The handler should re-call
    if it wants to keep polling.
    """
    key = stream_key(turn_id)
    while True:
        # XREAD returns either None (timeout) or [[stream_name, [(id, fields), ...]]]
        res = await client.xread({key: last_event_id}, block=block_ms, count=50)
        if not res:
            return
        # Single stream → single inner list.
        _stream_name, entries = res[0]
        for entry_id, fields in entries:
            entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
            event_name = (
                fields[b"event"].decode()
                if isinstance(fields.get(b"event"), bytes)
                else fields.get("event", "")
            )
            data_raw = (
                fields[b"data"].decode()
                if isinstance(fields.get(b"data"), bytes)
                else fields.get("data", "{}")
            )
            try:
                data = json.loads(data_raw) if data_raw else {}
            except json.JSONDecodeError:
                data = {"_raw": data_raw}
            last_event_id = entry_id_str
            yield entry_id_str, event_name, data


async def set_stream_ttl(
    client: redis.Redis,
    *,
    turn_id: str,
    seconds: int = 300,
) -> None:
    """Cap how long a completed stream sticks around for resume.

    5 minutes by default — enough for a flaky mobile reconnect, short
    enough that a forgotten subscriber doesn't pin RAM. The orphan-
    stream cleanup beat handles any streams that didn't get an
    explicit TTL set (worker crashed mid-turn, etc.).
    """
    await client.expire(stream_key(turn_id), seconds)
