"""Course-scoped RAG tutor — REST endpoints.

Rebuild Phase E1. Four endpoints power the tutor panel:

* ``POST /api/v1/courses/{course_id}/tutor/conversations``
    Open a fresh thread for this learner + this course.
* ``GET  /api/v1/courses/{course_id}/tutor/conversations``
    List my recent threads for this course (paginated).
* ``GET  /api/v1/tutor/conversations/{id}``
    Pull one thread with its full message list.
* ``POST /api/v1/tutor/conversations/{id}/messages``
    Send a question. Persists the user turn, calls the tutor
    service, persists the assistant turn with citations, returns
    the assistant message. Rate-limited at 20/minute per user — the
    same cap the quiz-submit endpoint uses for the same reason
    (each call is a real round-trip with cost + DB writes).

Access model:

* Every endpoint requires authentication.
* List + post operate on conversations the caller owns. We never
  expose another user's tutor history — collapse "not yours" to
  404 so the endpoint can't be used to probe other learners'
  conversation ids.
* The course-scoped POST that opens a new thread is open to any
  authenticated user (the tutor is useful for preview/sample
  questions). The actual retrieval pipeline is gated by what's
  in ``lesson_chunks`` — if a course hasn't been published yet
  there's nothing to retrieve, the refusal fires, and the
  conversation reads as an empty exchange.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import redis.asyncio as redis
from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select

from app.api.deps import CurrentUser, DBSession
from app.core.config import get_settings
from app.core.cost_scripts import (
    USD_TO_MICROCENTS,
    check_concurrency,
    reconcile_cost,
    release_concurrency,
    reserve_cost,
)
from app.core.errors import (
    NotFoundError,
    TutorConcurrencyLimitError,
    TutorGlobalCapError,
    TutorIpCapError,
    TutorUserCapError,
    ValidationAppError,
)
from app.core.ratelimit import limiter
from app.models.course import Course
from app.models.tutor_conversation import (
    TutorConversation,
    TutorMessage,
    TutorMessageRole,
)
from app.models.tutor_turn_job import TURN_STATUS_COMPLETE, TURN_STATUS_FAILED, TURN_STATUS_RUNNING
from app.repositories import courses as courses_repo
from app.schemas.common import Page
from app.services import byok as byok_service
from app.services import tutor as tutor_service
from app.services.tutor_turn_service import create_turn, mark_terminal

router = APIRouter()


# ---------- Schemas ----------


class CitationOut(BaseModel):
    """One lesson reference rendered as a pill in the tutor panel."""

    lesson_id: str
    lesson_title: str
    chunk_excerpt: str


class TutorMessageOut(BaseModel):
    """One turn in a tutor conversation."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    role: TutorMessageRole
    content: str
    citations: list[CitationOut] = Field(default_factory=list)
    created_at: datetime


class TutorConversationSummary(BaseModel):
    """Slim list-view shape for the "my recent conversations" panel.

    ``last_message_preview`` is the trimmed text of the most recent
    message in the thread — what we render as the row's subtitle.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
    created_at: datetime
    last_message_at: datetime
    last_message_preview: str = ""
    message_count: int = 0


class TutorConversationDetail(BaseModel):
    """Full conversation with its message history."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
    created_at: datetime
    last_message_at: datetime
    messages: list[TutorMessageOut] = Field(default_factory=list)


class PostMessageRequest(BaseModel):
    """Body for POST /tutor/conversations/{id}/messages.

    ``content`` is the learner's question. We cap it at 4000 chars
    so a paste-the-whole-textbook prompt doesn't blow the LLM's
    context budget — long inputs hurt grounding ("haystack
    problem") and explode token cost.
    """

    content: str = Field(min_length=1, max_length=4000)


class ToolCallTraceOut(BaseModel):
    """One sub-agent dispatch as rendered in the agent-reasoning panel.

    Lumen v2 Phase I2 — the moat surface. Each tool call lands here
    with its name, the planner's rationale for picking it, a short
    summary of the result, and the structured details (chunks,
    snippets, stdout, ...) the frontend renders when the row is
    expanded.

    The schema is open at the ``result_details`` field (``dict``)
    because the five sub-agents produce different result shapes; the
    frontend dispatches on ``tool_name`` to know which keys to expect.
    Keeping it generic here avoids a per-tool union model that would
    drift every time we add a sub-agent.
    """

    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    result_summary: str = ""
    result_details: dict[str, Any] = Field(default_factory=dict)


class PostMessageResponse(BaseModel):
    """Echoes back both turns from a single POST.

    Returning both turns (rather than just the assistant) lets the
    client reconcile its optimistic UI without a second GET — the
    user message it just optimistically rendered will be replaced
    with the canonical persisted row.

    Phase I2 also surfaces:

    * ``confidence`` — 0-5 self-reported by the planner / re-planner.
      Rendered as a "Confidence: N/5" badge above the agent-reasoning
      panel.
    * ``agent_trace`` — the per-turn tool-call log. Empty list on a
      refused / empty-retrieval response (no plan ran).
    """

    user_message: TutorMessageOut
    assistant_message: TutorMessageOut
    refused: bool = False
    confidence: int = 0
    agent_trace: list[ToolCallTraceOut] = Field(default_factory=list)


# ---------- Helpers ----------


async def _get_course_or_404(db, course_id: str) -> Course:
    course = await courses_repo.get_course(db, course_id)
    if not course or course.deleted_at is not None:
        raise NotFoundError("Course not found", code="course.not_found")
    return course


async def _get_my_conversation_or_404(db, conversation_id: str, user_id: str) -> TutorConversation:
    """Fetch a conversation owned by ``user_id`` or raise 404.

    We collapse "not yours" to 404 (rather than 403) so the endpoint
    can't be used to probe other users' conversation ids — same
    posture the reviews-queue endpoint takes for ReviewCards.
    """
    conv = await db.get(TutorConversation, conversation_id)
    if conv is None or conv.user_id != user_id:
        raise NotFoundError("Conversation not found", code="tutor.conversation_not_found")
    return conv


def _message_to_out(msg: TutorMessage) -> TutorMessageOut:
    cits = [
        CitationOut(
            lesson_id=str(c.get("lesson_id", "")),
            lesson_title=str(c.get("lesson_title", "")),
            chunk_excerpt=str(c.get("chunk_excerpt", "")),
        )
        for c in (msg.citations or [])
    ]
    # ``msg.role`` round-trips through Postgres as a plain string, so
    # coerce back into the enum before handing it to Pydantic. The
    # ``TutorMessageRole(str_val)`` ctor handles both shapes safely.
    role = msg.role if isinstance(msg.role, TutorMessageRole) else TutorMessageRole(str(msg.role))
    return TutorMessageOut(
        id=msg.id,
        role=role,
        content=msg.content,
        citations=cits,
        created_at=msg.created_at,
    )


# ---------- Endpoints (course-scoped) ----------


@router.post(
    "/courses/{course_id}/tutor/conversations",
    response_model=TutorConversationDetail,
    status_code=status.HTTP_201_CREATED,
)
async def start_conversation(
    course_id: str, user: CurrentUser, db: DBSession
) -> TutorConversationDetail:
    """Open a fresh tutor thread for this learner + this course."""
    course = await _get_course_or_404(db, course_id)
    conv = TutorConversation(user_id=user.id, course_id=course.id)
    db.add(conv)
    await db.flush()
    await db.refresh(conv)
    return TutorConversationDetail(
        id=conv.id,
        course_id=conv.course_id,
        created_at=conv.created_at,
        last_message_at=conv.last_message_at,
        messages=[],
    )


@router.get(
    "/courses/{course_id}/tutor/conversations",
    response_model=Page[TutorConversationSummary],
)
async def list_my_conversations(
    course_id: str,
    user: CurrentUser,
    db: DBSession,
    page: int = 1,
    page_size: int = 20,
) -> Page[TutorConversationSummary]:
    """My recent conversations for this course, newest-touched first."""
    if page < 1:
        raise ValidationAppError("page must be >= 1", code="tutor.bad_page")
    page_size = max(1, min(int(page_size or 20), 100))
    course = await _get_course_or_404(db, course_id)

    # We deliberately don't preload the full message list for the
    # listing endpoint — the panel only needs the preview + count.
    # Two cheap aggregate queries beat one heavy joinedload.
    rows = (
        (
            await db.execute(
                select(TutorConversation)
                .where(
                    TutorConversation.user_id == user.id,
                    TutorConversation.course_id == course.id,
                )
                .order_by(desc(TutorConversation.last_message_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )

    # Last message + count per conversation. Doing this as two
    # follow-up SELECTs (instead of a window function in the main
    # query) keeps the SQL readable; the index on
    # ``(conversation_id, created_at)`` makes both cheap.
    summaries: list[TutorConversationSummary] = []
    for conv in rows:
        last = (
            await db.execute(
                select(TutorMessage)
                .where(TutorMessage.conversation_id == conv.id)
                .order_by(desc(TutorMessage.created_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        count_row = (
            await db.execute(select(TutorMessage.id).where(TutorMessage.conversation_id == conv.id))
        ).all()
        preview = ""
        if last is not None:
            preview = last.content[:160]
        summaries.append(
            TutorConversationSummary(
                id=conv.id,
                course_id=conv.course_id,
                created_at=conv.created_at,
                last_message_at=conv.last_message_at,
                last_message_preview=preview,
                message_count=len(count_row),
            )
        )

    # Total count for the paginator.
    total_rows = (
        await db.execute(
            select(TutorConversation.id).where(
                TutorConversation.user_id == user.id,
                TutorConversation.course_id == course.id,
            )
        )
    ).all()
    total = len(total_rows)

    return Page[TutorConversationSummary](
        items=summaries, total=total, page=page, page_size=page_size
    )


# ---------- Endpoints (conversation-scoped) ----------


@router.get(
    "/tutor/conversations/{conversation_id}",
    response_model=TutorConversationDetail,
)
async def get_conversation(
    conversation_id: str, user: CurrentUser, db: DBSession
) -> TutorConversationDetail:
    conv = await _get_my_conversation_or_404(db, conversation_id, user.id)
    msgs = (
        (
            await db.execute(
                select(TutorMessage)
                .where(TutorMessage.conversation_id == conv.id)
                .order_by(TutorMessage.created_at)
            )
        )
        .scalars()
        .all()
    )
    return TutorConversationDetail(
        id=conv.id,
        course_id=conv.course_id,
        created_at=conv.created_at,
        last_message_at=conv.last_message_at,
        messages=[_message_to_out(m) for m in msgs],
    )


@router.post(
    "/tutor/conversations/{conversation_id}/messages",
    response_model=PostMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("20/minute")
async def post_message(
    conversation_id: str,
    payload: PostMessageRequest,
    user: CurrentUser,
    db: DBSession,
    request: Request,
    response: Response,
) -> PostMessageResponse:
    """Send a question. Persists user + assistant turns; returns both.

    The user message is persisted before the LLM call so a network
    blip on the model's side leaves a clean audit trail (you can
    see what the learner asked). The assistant message is persisted
    only after a successful answer — if the LLM raises, we leave
    the user turn in place and surface the error to the client; a
    retry produces a clean new assistant message rather than
    appending duplicate turns.

    Rate-limited at 20/minute per identity (same cap the quiz
    endpoint uses): each call is a real LLM round-trip with cost
    plus two DB writes. Twenty messages a minute is well above any
    plausible human typing speed and still leaves headroom for an
    eager UI that fires retries.
    """
    conv = await _get_my_conversation_or_404(db, conversation_id, user.id)
    course = await _get_course_or_404(db, conv.course_id)
    content = payload.content.strip()
    if not content:
        raise ValidationAppError("Message content cannot be empty", code="tutor.empty_message")

    # L34 — apply the same L21-Sec defences the streaming POST uses:
    # check_concurrency + reserve_cost against the three rolling-24h
    # microcent buckets. Without this layer the legacy POST is a
    # bypass for the cost cap. Concurrency is user-scoped (same
    # bucket as streaming) — a user can't stack a legacy + streaming
    # turn to dodge the limit.
    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"
    redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=False)
    user_concurrency_key = f"concurrent:user:{user.id}"
    try:
        conc_ok, _conc_count = await check_concurrency(
            redis_client,
            user_key=user_concurrency_key,
            max_concurrent=settings.tutor_max_concurrent,
        )
        if not conc_ok:
            raise TutorConcurrencyLimitError("Too many concurrent tutor turns for this user.")

        reserve_ok, reserve_tag = await reserve_cost(
            redis_client,
            user_key=f"cost:user:{user.id}",
            ip_key=f"cost:ip:{client_ip}",
            global_key="cost:global",
            estimate_microcents=settings.tutor_estimate_microcents,
            max_user_microcents=settings.tutor_cap_user_microcents,
            max_ip_microcents=settings.tutor_cap_ip_microcents,
            max_global_microcents=settings.tutor_cap_global_microcents,
        )
        if not reserve_ok:
            await release_concurrency(redis_client, user_key=user_concurrency_key)
            if reserve_tag == "user_cap":
                raise TutorUserCapError("Per-user cost cap reached.")
            if reserve_tag == "ip_cap":
                raise TutorIpCapError("Per-IP cost cap reached.")
            if reserve_tag == "global_cap":
                raise TutorGlobalCapError("Global cost cap reached for the day.")
            raise TutorUserCapError(f"reservation rejected: {reserve_tag}")
    finally:
        # Don't close redis_client here — we need it for the
        # reconcile/release path in the post-LLM block.
        pass

    # L34 — write a tutor_turn_jobs row for unified observability.
    # Streaming + legacy both now produce rows in the same table; the
    # admin observability surface (plan-v7 §V7-F11) sees both paths.
    # Unlike the streaming path this row is synchronous: we transition
    # running → complete/failed inside this handler, never via Celery.
    # L34-rescue P1: wrap all post-reserve setup work (create_turn,
    # history query, user-msg persist) in a try/except that releases
    # the reservation on any failure. Without this, an exception
    # between the reservation and the orchestrator's inner try-block
    # would leak the reservation until its 24h TTL.
    reserved_usd = Decimal(settings.tutor_estimate_microcents) / Decimal(USD_TO_MICROCENTS)
    try:
        turn = await create_turn(
            db,
            user_id=user.id,
            conversation_id=conv.id,
            course_id=conv.course_id,
            user_message=content,
            reserved_cost_usd=reserved_usd,
            reservation_ip_key=client_ip,
            prompt_template_hash=None,
            enqueue_task=False,  # synchronous path — no Celery
        )
        # Immediately promote to running so the sweep won't claim it.
        turn.status = TURN_STATUS_RUNNING
        await db.flush()
    except Exception:
        await _release_legacy_reservation(
            redis_client,
            user_id=user.id,
            client_ip=client_ip,
            user_concurrency_key=user_concurrency_key,
            reserved_microcents=settings.tutor_estimate_microcents,
            actual_microcents=0,
        )
        with contextlib.suppress(Exception):
            await redis_client.aclose()
        raise

    # L34-rescue P1: unified cleanup path for every post-reserve
    # failure. Pre-L34-rescue the history query and user_msg persist
    # ran outside any try/except, so a DB hiccup between
    # create_turn and the orchestrator call would leak the
    # reservation for 24h.
    try:
        # Pull the prior turns so the model has conversation context.
        # Cap at 20 — older turns are still readable via GET but won't
        # be replayed.
        history_rows = (
            (
                await db.execute(
                    select(TutorMessage)
                    .where(TutorMessage.conversation_id == conv.id)
                    .order_by(desc(TutorMessage.created_at))
                    .limit(20)
                )
            )
            .scalars()
            .all()
        )
        # ``m.role`` is typed as :class:`TutorMessageRole` but Postgres
        # round-trips it as a plain string, so call ``str(...)`` rather
        # than ``.value`` — the latter explodes when SQLAlchemy hands
        # us the raw string back instead of constructing the enum.
        history = [
            {"role": str(m.role), "content": m.content} for m in reversed(list(history_rows))
        ]

        # 1) Persist the user turn before calling the LLM. If the model
        # call fails the audit log still shows what the learner asked.
        user_msg = TutorMessage(
            conversation_id=conv.id,
            role=TutorMessageRole.user,
            content=content,
            citations=[],
        )
        db.add(user_msg)
        await db.flush()

        # 2) Call the multi-agent orchestrator via the trace-aware
        # surface. Phase I2 — the chat API gets the full
        # ``OrchestratorResult`` (tool calls + confidence) alongside
        # the legacy ``TutorAnswer`` so the response carries the
        # agent's per-turn reasoning. The H1 cost meter is wired
        # internally; we pass ``user.id`` so calls attribute to the
        # learner.
        # S5.12/DR-8: resolve the foreground BYOK context for the acting
        # user; the orchestrator threads it through every LLM call so a
        # user-initiated tutor turn runs on the user's key end-to-end.
        ctx = await byok_service.resolve_context(db, user_id=user.id)
        result, orch = await tutor_service.ask_with_trace(
            db,
            course=course,
            user_message=content,
            conversation_history=history,
            user_id=user.id,
            feature="tutor.multi_agent",
            ctx=ctx,
        )
    except Exception:
        # Any failure between reserve_cost and the assistant-message
        # persist: mark the turn failed, release the reservation, and
        # re-raise so the FastAPI error envelope fires as before.
        with contextlib.suppress(Exception):
            await mark_terminal(
                db,
                turn_id=turn.id,
                status=TURN_STATUS_FAILED,
                error_code="tutor.runtime_legacy",
            )
            await db.flush()
        await _release_legacy_reservation(
            redis_client,
            user_id=user.id,
            client_ip=client_ip,
            user_concurrency_key=user_concurrency_key,
            reserved_microcents=settings.tutor_estimate_microcents,
            actual_microcents=0,
        )
        with contextlib.suppress(Exception):
            await redis_client.aclose()
        raise

    # 3) Persist the assistant turn with its citations.
    assistant_msg = TutorMessage(
        conversation_id=conv.id,
        role=TutorMessageRole.assistant,
        content=result.answer,
        citations=result.citations_as_dicts(),
    )
    db.add(assistant_msg)

    await db.flush()
    await db.refresh(assistant_msg)
    await db.refresh(user_msg)

    # 4) Touch ``last_message_at`` so the listing endpoint sorts
    # this thread to the top. We use the persisted assistant
    # message's ``created_at`` (populated server-side) so the
    # column matches what GET will return.
    conv.last_message_at = assistant_msg.created_at or datetime.now(UTC)
    await db.flush()

    # L34 — mark the tutor_turn_jobs row complete + reconcile cost.
    # The legacy orchestrator's H1 cost meter logs to llm_calls so we
    # don't have a direct cost_usd handle here; pass 0 actual which
    # releases the full reservation (the actual cost is tracked
    # separately via llm_calls). A future follow-up can wire the
    # orchestrator to surface aggregated cost so reconcile is exact.
    with contextlib.suppress(Exception):
        await mark_terminal(db, turn_id=turn.id, status=TURN_STATUS_COMPLETE)
        await db.flush()
    # L34-rescue P1: successful turns must NOT release the full
    # reservation — that lets repeated successes bypass the cap.
    # Reconcile with `actual = reserved` (zero delta) so the
    # microcent bucket retains the spend until its 24h TTL. The
    # precise per-call cost still lives in `llm_calls` for billing;
    # the bucket is just the rolling-window cap. A future follow-up
    # can plumb real cost back from the orchestrator.
    await _release_legacy_reservation(
        redis_client,
        user_id=user.id,
        client_ip=client_ip,
        user_concurrency_key=user_concurrency_key,
        reserved_microcents=settings.tutor_estimate_microcents,
        actual_microcents=settings.tutor_estimate_microcents,
    )
    with contextlib.suppress(Exception):
        await redis_client.aclose()

    # 5) Project the orchestrator's tool-call log into the API
    # surface. Refused / empty-retrieval responses surface an empty
    # ``agent_trace`` and ``confidence=0`` — the frontend renders
    # "no plan ran" on those rather than blowing up.
    trace_out = [
        ToolCallTraceOut(
            tool_name=tc.tool_name,
            args=tc.args,
            rationale=tc.rationale,
            result_summary=tc.result_summary,
            result_details=tc.result_details,
        )
        for tc in orch.tool_calls_made
    ]

    return PostMessageResponse(
        user_message=_message_to_out(user_msg),
        assistant_message=_message_to_out(assistant_msg),
        refused=result.refused,
        confidence=orch.confidence,
        agent_trace=trace_out,
    )


async def _release_legacy_reservation(
    redis_client: redis.Redis,
    *,
    user_id: str,
    client_ip: str,
    user_concurrency_key: str,
    reserved_microcents: int,
    actual_microcents: int,
) -> None:
    """L34 — release a legacy POST's cost reservation + concurrency slot.

    Wrapped in ``contextlib.suppress`` blocks so a Redis flake on one
    cleanup step doesn't skip the next. ``reconcile_cost`` takes a
    delta — when actual is 0 (failure / refusal), the delta is
    negative, which releases the full reservation.
    """
    delta = actual_microcents - reserved_microcents
    with contextlib.suppress(Exception):
        await reconcile_cost(
            redis_client,
            user_key=f"cost:user:{user_id}",
            ip_key=f"cost:ip:{client_ip}",
            global_key="cost:global",
            delta_microcents=delta,
        )
    with contextlib.suppress(Exception):
        await release_concurrency(redis_client, user_key=user_concurrency_key)
