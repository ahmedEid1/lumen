"""Course chat — persistence + Redis pub/sub fan-out."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ForbiddenError, NotFoundError
from app.models.course import Course
from app.models.user import User
from app.repositories import chat as chat_repo
from app.repositories import courses as courses_repo


CHANNEL_FMT = "lumen:chat:{course_id}"
PRESENCE_FMT = "lumen:presence:{course_id}"


async def get_redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


async def ensure_can_chat(db: AsyncSession, *, user: User, course_id: str) -> Course:
    course = await courses_repo.get_course(db, course_id)
    if not course:
        raise NotFoundError("Course not found", code="course.not_found")
    if user.is_admin() or course.owner_id == user.id:
        return course
    enrollment = await courses_repo.get_enrollment(db, user_id=user.id, course_id=course.id)
    if not enrollment:
        raise ForbiddenError("Enroll first to chat", code="chat.enroll_first")
    return course


async def post(db: AsyncSession, *, user: User, course: Course, body: str) -> dict[str, Any]:
    msg = await chat_repo.add_message(db, course_id=course.id, author_id=user.id, body=body)
    return {
        "type": "message",
        "data": {
            "id": msg.id,
            "course_id": course.id,
            "body": msg.body,
            "created_at": msg.created_at.isoformat(),
            "author": {
                "id": user.id,
                "full_name": user.full_name,
                "avatar_url": user.avatar_url,
                "bio": user.bio,
                "role": user.role,
            },
        },
    }


async def publish(r: redis.Redis, course_id: str, event: dict[str, Any]) -> None:
    await r.publish(CHANNEL_FMT.format(course_id=course_id), json.dumps(event, default=str))


@asynccontextmanager
async def subscribe(r: redis.Redis, course_id: str) -> AsyncIterator[redis.client.PubSub]:
    pubsub = r.pubsub()
    try:
        await pubsub.subscribe(CHANNEL_FMT.format(course_id=course_id))
        yield pubsub
    finally:
        await pubsub.unsubscribe(CHANNEL_FMT.format(course_id=course_id))
        await pubsub.aclose()


async def mark_present(r: redis.Redis, *, course_id: str, user_id: str) -> None:
    await r.zadd(PRESENCE_FMT.format(course_id=course_id), {user_id: datetime.now(timezone.utc).timestamp()})


async def mark_absent(r: redis.Redis, *, course_id: str, user_id: str) -> None:
    await r.zrem(PRESENCE_FMT.format(course_id=course_id), user_id)


async def list_present(r: redis.Redis, *, course_id: str, within_seconds: int = 60) -> list[str]:
    threshold = datetime.now(timezone.utc).timestamp() - within_seconds
    return await r.zrangebyscore(PRESENCE_FMT.format(course_id=course_id), threshold, "+inf")
