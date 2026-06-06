"""Streamed tutor turns must persist conversation messages.

Regression coverage for the 2026-06-06 prod finding: every streamed turn
completed cleanly (job row ``complete``, ``llm_calls`` row written, SSE
delivered) while writing **zero** ``tutor_messages`` rows — the worker
forwarded ``synth_chunk`` deltas to Redis and discarded them, and the
POST endpoint neither created nor validated a conversation. History was
empty after reload and the per-turn trace drill-down was unreachable
(``turn_complete`` carried ``message_id: null``).

Three seams under test:

1. ``POST /tutor/turns`` auto-creates a conversation when the turn is
   course-scoped and the body carries no ``conversation_id`` — and
   validates ownership when it does (the worker now WRITES to the
   conversation, so attaching to a foreign one would be an IDOR).
2. ``_run_turn_async`` persists the user message right after the claim
   (mirroring the non-streaming "user turn survives an LLM blip"
   contract, ``app/api/v1/tutor.py:390``) and the assistant message at
   ``turn_complete`` — accumulated from the synth deltas, citations
   parsed against the retrieved chunks — then enriches the
   ``turn_complete`` event with the real ``message_id``.
3. Failure paths keep the user message and write no assistant row.

The worker tests run DB-backed: ``make_worker_engine`` resolves to the
transient test database, only the Redis/emit seams are patched.
"""

from __future__ import annotations

import uuid
from contextlib import suppress
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.course import (
    Course,
    CourseStatus,
    Difficulty,
    ModerationState,
    Subject,
    Visibility,
)
from app.models.tutor_conversation import TutorConversation, TutorMessage
from app.models.tutor_turn_job import (
    TURN_STATUS_COMPLETE,
    TURN_STATUS_FAILED,
    TutorTurnJob,
)
from app.models.user import Role
from app.services.tutor_subagents.retriever import RetrieverChunk, RetrieverResult
from app.services.tutor_turn_service import create_turn
from app.workers.tasks import tutor_streaming

QUESTION = "Why do we chunk documents before embedding?"


async def _make_course(db_session: AsyncSession, owner_id: str) -> Course:
    suffix = uuid.uuid4().hex[:6]
    subject = Subject(title=f"Persist {suffix}", slug=f"persist-{suffix}")
    db_session.add(subject)
    await db_session.flush()
    course = Course(
        owner_id=owner_id,
        subject_id=subject.id,
        title=f"Persist Course {suffix}",
        slug=f"persist-course-{suffix}",
        overview="o",
        difficulty=Difficulty.beginner,
        status=CourseStatus.published,
        visibility=Visibility.public,
        moderation_state=ModerationState.approved,
    )
    db_session.add(course)
    await db_session.commit()
    return course


# ---------------------------------------------------------------------
# 1. POST /tutor/turns — conversation auto-create + ownership gate
# ---------------------------------------------------------------------


async def test_post_turn_autocreates_conversation_for_course(
    client: AsyncClient,
    auth_headers,
    make_user,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(get_settings(), "feature_tutor_streaming", True)
    owner = await make_user(role=Role.instructor)
    course = await _make_course(db_session, owner.id)

    headers = await auth_headers(role=Role.student)
    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": QUESTION, "course_slug": course.slug},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["conversation_id"], "course-scoped turn must land in a conversation"

    conv = (
        await db_session.execute(
            select(TutorConversation).where(TutorConversation.id == body["conversation_id"])
        )
    ).scalar_one_or_none()
    assert conv is not None
    assert conv.course_id == course.id

    turn = (
        await db_session.execute(select(TutorTurnJob).where(TutorTurnJob.id == body["id"]))
    ).scalar_one()
    assert turn.conversation_id == conv.id
    # The conversation belongs to the asker, not the course owner.
    assert conv.user_id == turn.user_id


async def test_post_turn_rejects_foreign_conversation(
    client: AsyncClient,
    auth_headers,
    make_user,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    """Attaching a turn to someone else's thread must 404 (existence-hide).

    Pre-fix this was latently broken but harmless (nothing ever wrote to
    the conversation); now that the worker persists messages into it, a
    foreign conversation_id would write into another user's history.
    """
    monkeypatch.setattr(get_settings(), "feature_tutor_streaming", True)
    owner = await make_user(role=Role.instructor)
    course = await _make_course(db_session, owner.id)

    other = await make_user(email=f"victim-{uuid.uuid4().hex[:6]}@lumen.test")
    foreign_conv = TutorConversation(user_id=other.id, course_id=course.id)
    db_session.add(foreign_conv)
    await db_session.commit()

    headers = await auth_headers(role=Role.student)
    r = await client.post(
        "/api/v1/tutor/turns",
        json={
            "content": QUESTION,
            "course_slug": course.slug,
            "conversation_id": foreign_conv.id,
        },
        headers=headers,
    )
    assert r.status_code == 404, r.text

    count = (
        (
            await db_session.execute(
                select(TutorTurnJob).where(TutorTurnJob.conversation_id == foreign_conv.id)
            )
        )
        .scalars()
        .all()
    )
    assert count == [], "no turn row may attach to a foreign conversation"


async def test_post_turn_keeps_own_conversation(
    client: AsyncClient,
    auth_headers,
    make_user,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(get_settings(), "feature_tutor_streaming", True)
    owner = await make_user(role=Role.instructor)
    course = await _make_course(db_session, owner.id)

    asker_headers = await auth_headers(role=Role.student)
    # Resolve the asker's own user via the headers' bearer identity:
    me = await client.get("/api/v1/auth/me", headers=asker_headers)
    asker_id = me.json()["id"]

    conv = TutorConversation(user_id=asker_id, course_id=course.id)
    db_session.add(conv)
    await db_session.commit()

    r = await client.post(
        "/api/v1/tutor/turns",
        json={
            "content": QUESTION,
            "course_slug": course.slug,
            "conversation_id": conv.id,
        },
        headers=asker_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["conversation_id"] == conv.id


async def test_post_turn_rejects_cross_course_conversation(
    client: AsyncClient,
    auth_headers,
    make_user,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    """Codex P2: an owned course-A thread must not take a course-B turn.

    Conversations are course-scoped; without this gate the worker would
    retrieve/synthesise against course B but persist the messages (and
    course-B citations) into the course-A thread.
    """
    monkeypatch.setattr(get_settings(), "feature_tutor_streaming", True)
    owner = await make_user(role=Role.instructor)
    course_a = await _make_course(db_session, owner.id)
    course_b = await _make_course(db_session, owner.id)

    asker_headers = await auth_headers(role=Role.student)
    me = await client.get("/api/v1/auth/me", headers=asker_headers)
    conv_a = TutorConversation(user_id=me.json()["id"], course_id=course_a.id)
    db_session.add(conv_a)
    await db_session.commit()

    r = await client.post(
        "/api/v1/tutor/turns",
        json={
            "content": QUESTION,
            "course_slug": course_b.slug,
            "conversation_id": conv_a.id,
        },
        headers=asker_headers,
    )
    assert r.status_code == 404, r.text


async def test_post_turn_derives_course_from_conversation(
    client: AsyncClient,
    auth_headers,
    make_user,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    """A follow-up turn may send just {content, conversation_id} — the
    course context (and with it the worker's retrieval scope) derives
    from the thread instead of degrading to synth-only."""
    monkeypatch.setattr(get_settings(), "feature_tutor_streaming", True)
    owner = await make_user(role=Role.instructor)
    course = await _make_course(db_session, owner.id)

    asker_headers = await auth_headers(role=Role.student)
    me = await client.get("/api/v1/auth/me", headers=asker_headers)
    conv = TutorConversation(user_id=me.json()["id"], course_id=course.id)
    db_session.add(conv)
    await db_session.commit()

    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": QUESTION, "conversation_id": conv.id},
        headers=asker_headers,
    )
    assert r.status_code == 201, r.text

    turn = (
        await db_session.execute(select(TutorTurnJob).where(TutorTurnJob.id == r.json()["id"]))
    ).scalar_one()
    assert turn.course_id == course.id
    assert turn.conversation_id == conv.id


# ---------------------------------------------------------------------
# 2. Worker persistence — DB-backed ``_run_turn_async``
# ---------------------------------------------------------------------


def _patch_redis_seams(monkeypatch, emitted: list[dict]) -> None:
    """Patch ONLY the Redis/cost seams; DB paths stay real."""
    redis_client = MagicMock()
    redis_client.aclose = AsyncMock()
    monkeypatch.setattr(
        tutor_streaming.redis.Redis, "from_url", MagicMock(return_value=redis_client)
    )

    async def _capture(_client, *, turn_id, event, data):
        emitted.append({"turn_id": turn_id, "event": event, "data": data})

    monkeypatch.setattr(tutor_streaming, "emit_event", _capture)
    monkeypatch.setattr(tutor_streaming, "set_stream_ttl", AsyncMock())
    monkeypatch.setattr(tutor_streaming, "reconcile_cost", AsyncMock())
    monkeypatch.setattr(tutor_streaming, "release_concurrency", AsyncMock())
    monkeypatch.setattr(tutor_streaming, "reserve_cost", AsyncMock(return_value=(True, "ok")))
    monkeypatch.setattr(tutor_streaming, "set_reserved_cost", AsyncMock(return_value=True))


async def _seed_turn(
    db_session: AsyncSession,
    make_user,
) -> tuple[str, str, str]:
    """Create user + course + conversation + pending turn job."""
    user = await make_user(email=f"stream-{uuid.uuid4().hex[:6]}@lumen.test")
    course = await _make_course(db_session, user.id)
    course_id = course.id
    conv = TutorConversation(user_id=user.id, course_id=course_id)
    db_session.add(conv)
    await db_session.flush()
    turn = await create_turn(
        db_session,
        user_id=user.id,
        conversation_id=conv.id,
        reserved_cost_usd=Decimal("0"),
        reservation_ip_key=None,
        prompt_template_hash=None,
        user_message=QUESTION,
        course_id=course_id,
        credential_id=None,
        enqueue_task=False,
    )
    await db_session.commit()
    return turn.id, conv.id, course_id


async def test_worker_persists_messages_on_complete(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    turn_id, conv_id, _course_id = await _seed_turn(db_session, make_user)

    lesson_id = "lsn_persist_1"
    chunk = RetrieverChunk(
        lesson_id=lesson_id,
        lesson_title="Chunking 101",
        text="Chunking keeps each embedding focused on one concept.",
        score=0.0,
    )
    monkeypatch.setattr(
        tutor_streaming,
        "run_retriever",
        AsyncMock(return_value=RetrieverResult(chunks=[chunk], citations=[lesson_id], note="x")),
    )

    async def _stub_stream(**_kw):
        yield {"event": "planner_start", "data": {"plan": "answer"}}
        yield {"event": "synth_chunk", "data": {"delta": "Chunking keeps embeddings sharp "}}
        yield {"event": "synth_chunk", "data": {"delta": f"[L:{lesson_id}]."}}
        yield {
            "event": "turn_complete",
            "data": {
                "message_id": None,
                "cost_usd": 0.0,
                "prompt_tokens": 3,
                "completion_tokens": 5,
                "first_token_ms": 1.0,
                "total_ms": 2.0,
            },
        }

    monkeypatch.setattr(tutor_streaming, "orchestrate_stream", _stub_stream)

    emitted: list[dict] = []
    _patch_redis_seams(monkeypatch, emitted)

    await tutor_streaming._run_turn_async(turn_id)

    msgs = (
        (
            await db_session.execute(
                select(TutorMessage)
                .where(TutorMessage.conversation_id == conv_id)
                .order_by(TutorMessage.created_at)
            )
        )
        .scalars()
        .all()
    )
    assert [m.role for m in msgs] == ["user", "assistant"], (
        f"expected user+assistant rows, got {[(m.role, m.content) for m in msgs]}"
    )
    user_msg, assistant_msg = msgs
    assert user_msg.content == QUESTION
    assert user_msg.citations == []
    assert assistant_msg.content == f"Chunking keeps embeddings sharp [L:{lesson_id}]."
    assert assistant_msg.citations == [
        {
            "lesson_id": lesson_id,
            "lesson_title": "Chunking 101",
            "chunk_excerpt": "Chunking keeps each embedding focused on one concept.",
        }
    ]

    conv = (
        await db_session.execute(select(TutorConversation).where(TutorConversation.id == conv_id))
    ).scalar_one()
    assert conv.last_message_at is not None
    assert conv.last_message_at == assistant_msg.created_at

    # The SSE consumer needs the persisted id for the trace drill-down link.
    completes = [e for e in emitted if e["event"] == "turn_complete"]
    assert len(completes) == 1
    assert completes[0]["data"]["message_id"] == assistant_msg.id

    turn = (
        await db_session.execute(select(TutorTurnJob).where(TutorTurnJob.id == turn_id))
    ).scalar_one()
    assert turn.status == TURN_STATUS_COMPLETE


async def test_worker_persists_user_message_when_stream_fails(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """A raised mid-stream failure keeps the question in history."""
    turn_id, conv_id, _ = await _seed_turn(db_session, make_user)

    async def _exploding_stream(**_kw):
        yield {"event": "planner_start", "data": {"plan": "answer"}}
        raise RuntimeError("provider blew up")

    monkeypatch.setattr(tutor_streaming, "orchestrate_stream", _exploding_stream)
    # Keep retrieval out of the failure test — the suppress-wrapped branch
    # would otherwise run real pgvector retrieval against an empty course.
    monkeypatch.setattr(tutor_streaming, "run_retriever", AsyncMock())
    emitted: list[dict] = []
    _patch_redis_seams(monkeypatch, emitted)

    with suppress(RuntimeError):
        await tutor_streaming._run_turn_async(turn_id)

    msgs = (
        (
            await db_session.execute(
                select(TutorMessage).where(TutorMessage.conversation_id == conv_id)
            )
        )
        .scalars()
        .all()
    )
    assert [m.role for m in msgs] == ["user"]
    assert msgs[0].content == QUESTION

    turn = (
        await db_session.execute(select(TutorTurnJob).where(TutorTurnJob.id == turn_id))
    ).scalar_one()
    assert turn.status == TURN_STATUS_FAILED
