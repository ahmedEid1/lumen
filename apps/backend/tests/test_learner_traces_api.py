"""Learner-traces API tests (Lumen v2 Phase I4).

Mount the router under ``/api/v1`` (the orchestrator will land
the same include on master; this is a shim mirroring the H7
tests' fixture posture) and verify the auth + response shape:

* Owner of the conversation gets 200 with the full trace shape.
* Another learner gets 403.
* Missing conversation / message → 404.
* Instructor replay endpoint: owner gets 200, other instructor
  gets 403, missing course → 404.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import learner_traces
from app.models.agent_trace import TRACE_STATUS_OK, AgentTrace  # noqa: F401
from app.models.course import Course, Subject
from app.models.course_draft_trace import (
    DRAFT_STATUS_OK,
    DRAFT_STEP_RESEARCHER,
    CourseDraftTrace,
)
from app.models.llm_call import STATUS_OK, LLMCall
from app.models.retrieval_audit import RetrievalAudit  # noqa: F401
from app.models.tutor_conversation import (
    TutorConversation,
    TutorMessage,
    TutorMessageRole,
)
from app.models.user import Role


# ---------- Fixtures ----------


@pytest_asyncio.fixture
async def traces_app(app):
    """Mount the learner-traces router under the test app."""
    paths = {r.path for r in app.routes}  # type: ignore[attr-defined]
    sentinel = (
        "/api/v1/me/tutor/conversations/{conversation_id}"
        "/turns/{message_id}/trace"
    )
    if sentinel not in paths:
        app.include_router(
            learner_traces.router,
            prefix="/api/v1",
            tags=["learner-traces"],
        )
    return app


@pytest_asyncio.fixture
async def traces_client(traces_app):
    transport = ASGITransport(app=traces_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as c:
        yield c


# ---------- Seed helpers ----------


async def _login(client: AsyncClient, email: str, password: str) -> str:
    r = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _make_subject(db: AsyncSession) -> Subject:
    suffix = uuid.uuid4().hex[:6]
    s = Subject(title=f"Sub {suffix}", slug=f"sub-{suffix}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _make_course(
    db: AsyncSession, *, owner_id: str, subject_id: str
) -> Course:
    suffix = uuid.uuid4().hex[:6]
    c = Course(
        title=f"Course {suffix}",
        slug=f"course-{suffix}",
        subject_id=subject_id,
        owner_id=owner_id,
        status="draft",
        difficulty="beginner",
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def _ensure_course_row(db: AsyncSession, *, course_id: str, owner_id: str) -> None:
    """Idempotently seed a Course at a hardcoded id (FK target for the conv)."""
    existing = await db.get(Course, course_id)
    if existing is not None:
        return
    subj = Subject(
        title=f"Subj {course_id}", slug=f"subj-{course_id.replace('_', '-')}"
    )
    db.add(subj)
    await db.flush()
    db.add(
        Course(
            id=course_id,
            owner_id=owner_id,
            subject_id=subj.id,
            title=f"Course {course_id}",
            slug=f"course-{course_id.replace('_', '-')}",
            status="draft",
            difficulty="beginner",
        )
    )
    await db.commit()


async def _seed_conv_with_turn(
    db: AsyncSession, *, user_id: str, course_id: str = "crs_t01"
) -> tuple[TutorConversation, TutorMessage]:
    await _ensure_course_row(db, course_id=course_id, owner_id=user_id)
    conv = TutorConversation(user_id=user_id, course_id=course_id)
    db.add(conv)
    await db.flush()
    user_msg = TutorMessage(
        conversation_id=conv.id,
        role=TutorMessageRole.user,
        content="Q",
        citations=[],
    )
    db.add(user_msg)
    asst_msg = TutorMessage(
        conversation_id=conv.id,
        role=TutorMessageRole.assistant,
        content="A",
        citations=[],
    )
    db.add(asst_msg)
    await db.commit()
    await db.refresh(asst_msg)
    await db.refresh(conv)
    return conv, asst_msg


async def _seed_trace_and_call(
    db: AsyncSession, *, user_id: str, anchor
) -> None:
    when = anchor - timedelta(seconds=2)
    db.add(
        AgentTrace(
            user_id=user_id,
            feature="tutor.multi_agent",
            step="plan",
            step_index=0,
            payload={
                "tool_calls": [{"tool_name": "retriever"}],
                "confidence_after_plan": 4,
            },
            duration_ms=42,
            status=TRACE_STATUS_OK,
        )
    )
    db.add(
        LLMCall(
            user_id=user_id,
            feature="tutor.multi_agent.synth",
            provider="openai",
            model="llama-3.3-70b-versatile",
            prompt_tokens=80,
            completion_tokens=20,
            cost_usd=Decimal("0.000050"),
            latency_ms=420,
            status=STATUS_OK,
        )
    )
    await db.flush()
    # Backdate so the seeded rows fall in the 120s trace window
    # ending at the assistant message's ``created_at``.
    await db.execute(
        text(
            "update agent_traces set created_at = :ts "
            "where user_id = :u and feature = 'tutor.multi_agent'"
        ),
        {"ts": when, "u": user_id},
    )
    await db.execute(
        text(
            "update llm_calls set created_at = :ts "
            "where user_id = :u and feature = 'tutor.multi_agent.synth'"
        ),
        {"ts": when, "u": user_id},
    )
    await db.commit()


# ---------- Tutor turn trace endpoint ----------


async def test_owner_gets_tutor_trace(
    traces_client: AsyncClient,
    make_user,
    db_session: AsyncSession,
) -> None:
    user = await make_user(
        email="learner-trace@lumen.test",
        password="Password!1234",
        role=Role.student,
    )
    token = await _login(
        traces_client, "learner-trace@lumen.test", "Password!1234"
    )
    conv, asst = await _seed_conv_with_turn(db_session, user_id=user.id)
    await _seed_trace_and_call(db_session, user_id=user.id, anchor=asst.created_at)

    r = await traces_client.get(
        f"/api/v1/me/tutor/conversations/{conv.id}/turns/{asst.id}/trace",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["message_id"] == asst.id
    assert body["conversation_id"] == conv.id
    assert body["confidence"] == 4
    assert isinstance(body["agent_traces"], list)
    assert len(body["agent_traces"]) >= 1
    # The synth LLM call is the surfaced one.
    assert body["llm_call"] is not None
    assert body["llm_call"]["feature"] == "tutor.multi_agent.synth"


async def test_non_owner_blocked_with_403(
    traces_client: AsyncClient,
    make_user,
    db_session: AsyncSession,
) -> None:
    owner = await make_user(
        email="owner-trace@lumen.test",
        password="Password!1234",
        role=Role.student,
    )
    await make_user(
        email="stranger-trace@lumen.test",
        password="Password!1234",
        role=Role.student,
    )
    token = await _login(
        traces_client, "stranger-trace@lumen.test", "Password!1234"
    )
    conv, asst = await _seed_conv_with_turn(db_session, user_id=owner.id)

    r = await traces_client.get(
        f"/api/v1/me/tutor/conversations/{conv.id}/turns/{asst.id}/trace",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403, r.text
    body = r.json()
    assert body["error"]["code"] == "trace.forbidden"


async def test_missing_conversation_returns_404(
    traces_client: AsyncClient,
    make_user,
) -> None:
    await make_user(
        email="learner-404@lumen.test",
        password="Password!1234",
        role=Role.student,
    )
    token = await _login(
        traces_client, "learner-404@lumen.test", "Password!1234"
    )
    r = await traces_client.get(
        "/api/v1/me/tutor/conversations/conv_does_not_exist/turns/msg_x/trace",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404, r.text
    body = r.json()
    assert body["error"]["code"] == "trace.conversation_not_found"


async def test_missing_message_returns_404(
    traces_client: AsyncClient,
    make_user,
    db_session: AsyncSession,
) -> None:
    user = await make_user(
        email="learner-msg404@lumen.test",
        password="Password!1234",
        role=Role.student,
    )
    token = await _login(
        traces_client, "learner-msg404@lumen.test", "Password!1234"
    )
    conv, _ = await _seed_conv_with_turn(db_session, user_id=user.id)

    r = await traces_client.get(
        f"/api/v1/me/tutor/conversations/{conv.id}/turns/msg_nope/trace",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404, r.text
    body = r.json()
    assert body["error"]["code"] == "trace.message_not_found"


async def test_anonymous_request_returns_401(
    traces_client: AsyncClient,
) -> None:
    r = await traces_client.get(
        "/api/v1/me/tutor/conversations/conv_x/turns/msg_x/trace",
    )
    assert r.status_code == 401


# ---------- Instructor replay endpoint ----------


async def test_instructor_owner_gets_replay(
    traces_client: AsyncClient,
    make_user,
    db_session: AsyncSession,
) -> None:
    owner = await make_user(
        email="instr-replay@lumen.test",
        password="Password!1234",
        role=Role.instructor,
    )
    token = await _login(
        traces_client, "instr-replay@lumen.test", "Password!1234"
    )
    subject = await _make_subject(db_session)
    course = await _make_course(
        db_session, owner_id=owner.id, subject_id=subject.id
    )
    draft_id = uuid.uuid4().hex[:16]
    db_session.add(
        CourseDraftTrace(
            draft_id=draft_id,
            user_id=owner.id,
            course_id=course.id,
            step=DRAFT_STEP_RESEARCHER,
            step_index=0,
            payload={"prompt_summary": "ok", "response_summary": "ok"},
            duration_ms=110,
            status=DRAFT_STATUS_OK,
        )
    )
    await db_session.commit()

    r = await traces_client.get(
        f"/api/v1/me/studio/drafts/{course.id}/replay",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["course_id"] == course.id
    assert body["draft_id"] == draft_id
    assert body["step_count"] == 1
    assert body["total_duration_ms"] == 110
    assert body["steps"][0]["step"] == DRAFT_STEP_RESEARCHER


async def test_other_instructor_gets_403_on_replay(
    traces_client: AsyncClient,
    make_user,
    db_session: AsyncSession,
) -> None:
    owner = await make_user(
        email="instr-owner-r@lumen.test",
        password="Password!1234",
        role=Role.instructor,
    )
    await make_user(
        email="instr-stranger-r@lumen.test",
        password="Password!1234",
        role=Role.instructor,
    )
    token = await _login(
        traces_client, "instr-stranger-r@lumen.test", "Password!1234"
    )
    subject = await _make_subject(db_session)
    course = await _make_course(
        db_session, owner_id=owner.id, subject_id=subject.id
    )

    r = await traces_client.get(
        f"/api/v1/me/studio/drafts/{course.id}/replay",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    body = r.json()
    assert body["error"]["code"] == "course.forbidden"


async def test_missing_course_replay_returns_404(
    traces_client: AsyncClient,
    make_user,
) -> None:
    await make_user(
        email="instr-404r@lumen.test",
        password="Password!1234",
        role=Role.instructor,
    )
    token = await _login(
        traces_client, "instr-404r@lumen.test", "Password!1234"
    )
    r = await traces_client.get(
        "/api/v1/me/studio/drafts/crs_no_such_course/replay",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == "course.not_found"
