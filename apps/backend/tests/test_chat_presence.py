"""Regression: presence must reflect actively-engaged users.

Before iteration 31 ``mark_present`` ran once on WS connect, then never
again. ``list_present`` filters by a 60-second freshness window, so a
user who stayed connected and kept sending fell off the presence list
after one minute. Refreshing on every inbound frame keeps active users
in the window; idle users still expire naturally.

This is a thin service-layer test that exercises the Redis sorted-set
behaviour without standing up a real WebSocket — the integration with
the WS loop is one line of code.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


class _FakeRedis:
    """Minimal in-memory stand-in for the bits of redis.asyncio.Redis we use."""

    def __init__(self) -> None:
        self._sets: dict[str, dict[str, float]] = {}

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        self._sets.setdefault(key, {}).update(mapping)
        return len(mapping)

    async def zrem(self, key: str, *members: str) -> int:
        bucket = self._sets.setdefault(key, {})
        removed = 0
        for m in members:
            if m in bucket:
                del bucket[m]
                removed += 1
        return removed

    async def zrangebyscore(self, key: str, min_score: float, max_score: str | float) -> list[str]:
        bucket = self._sets.get(key, {})
        hi = float("inf") if max_score == "+inf" else float(max_score)
        return [member for member, score in bucket.items() if min_score <= score <= hi]


async def test_mark_present_overwrites_the_score():
    from app.services import chat as chat_service

    r: Any = _FakeRedis()
    await chat_service.mark_present(r, course_id="c1", user_id="u1")
    # Force the stored score back in time so the freshness window would drop us
    key = "lumen:presence:c1"
    r._sets[key]["u1"] = datetime(2020, 1, 1, tzinfo=UTC).timestamp()
    listed_before = await chat_service.list_present(r, course_id="c1", within_seconds=60)
    assert listed_before == []

    # Re-marking present (the iteration-31 refresh on every inbound frame)
    # bumps the score back to ~now, so the user re-appears.
    await chat_service.mark_present(r, course_id="c1", user_id="u1")
    listed_after = await chat_service.list_present(r, course_id="c1", within_seconds=60)
    assert listed_after == ["u1"]


async def test_mark_absent_removes_from_presence():
    from app.services import chat as chat_service

    r: Any = _FakeRedis()
    await chat_service.mark_present(r, course_id="c2", user_id="u1")
    await chat_service.mark_present(r, course_id="c2", user_id="u2")
    assert sorted(await chat_service.list_present(r, course_id="c2")) == ["u1", "u2"]
    await chat_service.mark_absent(r, course_id="c2", user_id="u1")
    assert await chat_service.list_present(r, course_id="c2") == ["u2"]


async def test_list_present_excludes_stale_users():
    from app.services import chat as chat_service

    r: Any = _FakeRedis()
    await chat_service.mark_present(r, course_id="c3", user_id="fresh")
    await chat_service.mark_present(r, course_id="c3", user_id="stale")
    key = "lumen:presence:c3"
    r._sets[key]["stale"] = datetime(2020, 1, 1, tzinfo=UTC).timestamp()
    assert await chat_service.list_present(r, course_id="c3") == ["fresh"]
