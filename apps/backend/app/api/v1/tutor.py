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

from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select

from app.api.deps import CurrentUser, DBSession
from app.core.errors import NotFoundError, ValidationAppError
from app.core.ratelimit import limiter
from app.models.course import Course
from app.models.tutor_conversation import (
    TutorConversation,
    TutorMessage,
    TutorMessageRole,
)
from app.repositories import courses as courses_repo
from app.schemas.common import Page
from app.services import tutor as tutor_service

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


class PostMessageResponse(BaseModel):
    """Echoes back both turns from a single POST.

    Returning both turns (rather than just the assistant) lets the
    client reconcile its optimistic UI without a second GET — the
    user message it just optimistically rendered will be replaced
    with the canonical persisted row.
    """

    user_message: TutorMessageOut
    assistant_message: TutorMessageOut
    refused: bool = False


# ---------- Helpers ----------


async def _get_course_or_404(db, course_id: str) -> Course:
    course = await courses_repo.get_course(db, course_id)
    if not course or course.deleted_at is not None:
        raise NotFoundError("Course not found", code="course.not_found")
    return course


async def _get_my_conversation_or_404(
    db, conversation_id: str, user_id: str
) -> TutorConversation:
    """Fetch a conversation owned by ``user_id`` or raise 404.

    We collapse "not yours" to 404 (rather than 403) so the endpoint
    can't be used to probe other users' conversation ids — same
    posture the reviews-queue endpoint takes for ReviewCards.
    """
    conv = await db.get(TutorConversation, conversation_id)
    if conv is None or conv.user_id != user_id:
        raise NotFoundError(
            "Conversation not found", code="tutor.conversation_not_found"
        )
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
    ).scalars().all()

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
            await db.execute(
                select(TutorMessage.id).where(
                    TutorMessage.conversation_id == conv.id
                )
            )
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
        await db.execute(
            select(TutorMessage)
            .where(TutorMessage.conversation_id == conv.id)
            .order_by(TutorMessage.created_at)
        )
    ).scalars().all()
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
        raise ValidationAppError(
            "Message content cannot be empty", code="tutor.empty_message"
        )

    # Pull the prior turns so the model has conversation context.
    # We cap to the last 20 turns to keep prompts bounded — older
    # turns are still readable via GET but won't be replayed to the
    # model. A long-running thread starts to lose coherence anyway
    # once the system prompt + 5 chunks + N turns approaches the
    # context window.
    history_rows = (
        await db.execute(
            select(TutorMessage)
            .where(TutorMessage.conversation_id == conv.id)
            .order_by(desc(TutorMessage.created_at))
            .limit(20)
        )
    ).scalars().all()
    # ``m.role`` is typed as :class:`TutorMessageRole` but Postgres
    # round-trips it as a plain string, so call ``str(...)`` rather
    # than ``.value`` — the latter explodes when SQLAlchemy hands us
    # the raw string back instead of constructing the enum.
    history = [
        {"role": str(m.role), "content": m.content}
        for m in reversed(list(history_rows))
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

    # 2) Call the tutor service — retrieval + LLM + citation parse.
    result = await tutor_service.ask(
        db,
        course=course,
        user_message=content,
        conversation_history=history,
    )

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

    return PostMessageResponse(
        user_message=_message_to_out(user_msg),
        assistant_message=_message_to_out(assistant_msg),
        refused=result.refused,
    )
