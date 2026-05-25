"""Learner + instructor trace API surface (Lumen v2 Phase I4).

Two read-only endpoints powering the "show your work" surfaces:

* ``GET /api/v1/me/tutor/conversations/{conversation_id}/turns/{message_id}/trace``
    The learner's per-turn drill-down. Returns the full multi-
    agent trace for one tutor turn — every planner / sub-agent /
    retriever / synthesiser step, plus the linked LLM call's
    cost / latency / tokens, plus the retrieval audits that fed
    the answer. **Owner-only**: the conversation must belong to
    the calling learner, else 403.

* ``GET /api/v1/me/studio/drafts/{course_id}/replay``
    The instructor's per-draft replay. Same rows the I3 timeline
    surfaces, projected with totals so the auto-advance scrub
    bar can pace itself. **Owner-only**: the caller must own the
    course OR be an admin (mirrors the I3 timeline endpoint's
    posture).

Auth posture differs from H7's admin observability:

* H7 returns 403 to non-admins on every endpoint — admin-or-bust.
* I4 returns 403 to the *wrong* learner / instructor and 404
  to the rightful owner when the resource doesn't exist. We
  deliberately don't collapse non-owner to 404 (the way the
  tutor list endpoint does) — a learner sharing a trace URL
  with a teammate should see a clear "this isn't yours" rather
  than "this conversation doesn't exist". The URL isn't
  enumerated; the soft-leak of "the conversation exists" is
  worth the better UX.

NOTE: this router is **not** registered in ``app/api/router.py``
— the orchestrator mounts it under ``/api/v1`` after the wave
returns. The expected mount lives at the root prefix because the
two endpoints already carry their own ``/me/`` prefix in the
declared paths. Operator follow-up at the bottom of the file
spells out the include block.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DBSession
from app.core.errors import ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.repositories import courses as courses_repo
from app.schemas.learner_traces import DraftReplayOut, TutorTurnTraceOut
from app.services import learner_traces as learner_traces_service

log = get_logger(__name__)

router = APIRouter()


# ---------- Endpoints ----------


@router.get(
    "/me/tutor/conversations/{conversation_id}/turns/{message_id}/trace",
    response_model=TutorTurnTraceOut,
)
async def get_tutor_turn_trace(
    conversation_id: str,
    message_id: str,
    user: CurrentUser,
    db: DBSession,
) -> TutorTurnTraceOut:
    """Return the full multi-agent trace for one of my tutor turns.

    The 403 / 404 split is enforced by the service layer; we let
    those propagate as :class:`ForbiddenError` /
    :class:`NotFoundError` and the central handler in
    ``app.core.errors`` shapes the envelope.
    """
    return await learner_traces_service.fetch_tutor_turn_trace(
        db,
        user_id=user.id,
        conversation_id=conversation_id,
        message_id=message_id,
    )


@router.get(
    "/me/studio/drafts/{course_id}/replay",
    response_model=DraftReplayOut,
)
async def get_draft_replay(
    course_id: str,
    user: CurrentUser,
    db: DBSession,
) -> DraftReplayOut:
    """Return the replay payload for the latest draft of ``course_id``.

    Authorisation: the caller must own the course OR be an admin.
    Same posture as the I3 timeline endpoint
    (``GET /api/v1/studio/drafts/{course_id}/trace``) — a trace
    leaks the instructor's drafting approach, so we don't surface
    it to peer instructors. Non-existent courses get a 404 so we
    don't leak whether a private slug exists.
    """
    course = await courses_repo.get_course(db, course_id)
    if course is None:
        raise NotFoundError("Course not found", code="course.not_found")
    if not (user.is_admin() or course.owner_id == user.id):
        raise ForbiddenError("Not your course", code="course.forbidden")

    return await learner_traces_service.fetch_draft_replay(
        db, course_id=course.id
    )


# Orchestrator follow-up: register this router in
# ``apps/backend/app/api/router.py`` without an additional
# prefix (the routes already carry the ``/me/`` segment):
#
#     from app.api.v1 import learner_traces
#     api_router.include_router(
#         learner_traces.router,
#         tags=["learner-traces"],
#     )
#
# No model registration is needed — every table this router
# reads (``agent_traces``, ``retrieval_audits``, ``llm_calls``,
# ``course_draft_traces``, ``tutor_conversations``,
# ``tutor_messages``) is already in ``app/models/__init__.py``
# from H1/H7/E1/I3.
