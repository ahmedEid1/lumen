"""Chat: history (REST) + WebSocket."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status

from app.api.deps import CurrentUser, DBSession
from app.core.errors import ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.core.security import decode_token
from app.db.base import get_sessionmaker
from app.repositories import chat as chat_repo
from app.repositories import courses as courses_repo
from app.repositories import users as users_repo
from app.schemas.chat import ChatHistoryPage, ChatMessageOut, ChatSendRequest
from app.schemas.user import UserPublic
from app.services import chat as chat_service

router = APIRouter()
log = get_logger(__name__)


@router.get("/courses/{course_id}/messages", response_model=ChatHistoryPage)
async def history(
    course_id: str,
    user: CurrentUser,
    db: DBSession,
    before: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> ChatHistoryPage:
    await chat_service.ensure_can_chat(db, user=user, course_id=course_id)
    msgs = await chat_repo.history(db, course_id=course_id, before_id=before, limit=limit)
    next_cursor = msgs[-1].id if len(msgs) == limit else None
    return ChatHistoryPage(
        items=[
            ChatMessageOut(
                id=m.id,
                course_id=m.course_id,
                body=m.body,
                created_at=m.created_at,
                author=UserPublic.model_validate(m.author),
            )
            for m in msgs
        ],
        next_cursor=next_cursor,
    )


@router.post("/courses/{course_id}/messages", response_model=ChatMessageOut, status_code=status.HTTP_201_CREATED)
async def post_message(
    course_id: str, payload: ChatSendRequest, user: CurrentUser, db: DBSession
) -> ChatMessageOut:
    course = await chat_service.ensure_can_chat(db, user=user, course_id=course_id)
    msg = await chat_repo.add_message(db, course_id=course.id, author_id=user.id, body=payload.body)

    redis = await chat_service.get_redis()
    try:
        await chat_service.publish(
            redis,
            course.id,
            {
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
            },
        )
    finally:
        await redis.aclose()

    return ChatMessageOut(
        id=msg.id,
        course_id=msg.course_id,
        body=msg.body,
        created_at=msg.created_at,
        author=UserPublic.model_validate(user),
    )


@router.websocket("/ws/{course_id}")
async def chat_ws(websocket: WebSocket, course_id: str, token: Annotated[str, Query()]) -> None:
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        await websocket.close(code=4401)
        return

    user_id = str(payload.get("sub", ""))
    if not user_id:
        await websocket.close(code=4401)
        return

    Session = get_sessionmaker()
    async with Session() as db:
        user = await users_repo.get_by_id(db, user_id)
        if not user or not user.is_active:
            await websocket.close(code=4401)
            return
        try:
            course = await chat_service.ensure_can_chat(db, user=user, course_id=course_id)
        except ForbiddenError:
            await websocket.close(code=4403)
            return
        except NotFoundError:
            await websocket.close(code=4404)
            return

    await websocket.accept()
    redis = await chat_service.get_redis()
    await chat_service.mark_present(redis, course_id=course_id, user_id=user.id)

    receiver_task: asyncio.Task[None] | None = None
    try:
        await _broadcast_presence(redis, course_id)

        async def push_from_redis() -> None:
            async with chat_service.subscribe(redis, course_id) as pubsub:
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    raw = message["data"]
                    if isinstance(raw, bytes):
                        raw = raw.decode()
                    await websocket.send_text(raw)

        receiver_task = asyncio.create_task(push_from_redis())

        while True:
            text = await websocket.receive_text()
            # Any inbound frame is proof of life — refresh the presence
            # sorted-set score so the 60-second window in list_present()
            # doesn't drop an actively-engaged user.
            await chat_service.mark_present(redis, course_id=course_id, user_id=user.id)
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "data": {"code": "invalid_json", "message": "Bad frame"}})
                continue
            kind = msg.get("type")
            data = msg.get("data") or {}

            if kind == "message":
                body = (data.get("body") or "").strip()
                if not body or len(body) > 4000:
                    await websocket.send_json({"type": "error", "data": {"code": "invalid_body", "message": "Body required (≤4000 chars)"}})
                    continue
                async with Session() as db_session:
                    posted = await chat_service.post(db_session, user=user, course=course, body=body)
                    await db_session.commit()
                await chat_service.publish(redis, course_id, posted)
            elif kind in {"typing.start", "typing.stop"}:
                await chat_service.publish(
                    redis,
                    course_id,
                    {"type": "typing", "data": {"user_id": user.id, "active": kind == "typing.start"}},
                )
            else:
                await websocket.send_json({"type": "error", "data": {"code": "unknown_type", "message": str(kind)}})

    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("chat_ws_error", course_id=course_id, user_id=user.id)
    finally:
        if receiver_task is not None:
            receiver_task.cancel()
        await chat_service.mark_absent(redis, course_id=course_id, user_id=user.id)
        await _broadcast_presence(redis, course_id)
        await redis.aclose()


async def _broadcast_presence(redis_client, course_id: str) -> None:
    online = await chat_service.list_present(redis_client, course_id=course_id)
    await chat_service.publish(redis_client, course_id, {"type": "presence", "data": {"online": online}})
