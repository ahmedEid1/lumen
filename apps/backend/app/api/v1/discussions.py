"""Course discussion threads (forum-style Q&A).

Visibility: anyone who can see the course can read its threads;
writes (new thread, reply, delete) require the same access.
Soft-delete is reserved to the author, the course owner, or an
admin. See ``services.discussions`` for the authz matrix.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response, status

from app.api.deps import CurrentUser, DBSession, OptionalUser
from app.core.errors import NotFoundError
from app.core.ratelimit import limiter
from app.repositories import courses as courses_repo
from app.repositories import discussions as discussions_repo
from app.schemas.common import OkResponse, Page
from app.schemas.discussion import (
    DiscussionCreate,
    DiscussionDetail,
    DiscussionListItem,
    DiscussionReplyCreate,
    DiscussionReplyOut,
    DiscussionUpdate,
)
from app.schemas.user import UserPublic
from app.services import courses as courses_service
from app.services import discussions as discussions_service

router = APIRouter()


def _to_list_item(d, reply_count: int, last_activity) -> DiscussionListItem:
    return DiscussionListItem(
        id=d.id,
        title=d.title,
        created_at=d.created_at,
        updated_at=d.updated_at,
        reply_count=reply_count,
        last_activity_at=last_activity,
        author=UserPublic.model_validate(d.author) if d.author else None,
    )


def _to_reply(r, *, author=None) -> DiscussionReplyOut:
    """Render a single reply; defaults to the ORM-loaded author."""
    resolved = author if author is not None else r.author
    return DiscussionReplyOut(
        id=r.id,
        body=r.body,
        created_at=r.created_at,
        updated_at=r.updated_at,
        author=UserPublic.model_validate(resolved) if resolved else None,
    )


def _to_detail(d) -> DiscussionDetail:
    return DiscussionDetail(
        id=d.id,
        course_id=d.course_id,
        title=d.title,
        body=d.body,
        created_at=d.created_at,
        updated_at=d.updated_at,
        author=UserPublic.model_validate(d.author) if d.author else None,
        replies=[_to_reply(r) for r in d.replies if r.deleted_at is None],
    )


@router.get("/courses/{course_id}/discussions", response_model=Page[DiscussionListItem])
async def list_discussions(
    course_id: str,
    viewer: OptionalUser,
    db: DBSession,
    page: int = Query(1, ge=1, le=10_000),
    page_size: int = Query(20, ge=1, le=50),
) -> Page[DiscussionListItem]:
    course = await courses_repo.get_course(db, course_id)
    if not course or not await courses_service.can_view_course(db, course, viewer):
        raise NotFoundError("Course not found", code="course.not_found")
    rows = await discussions_repo.list_for_course(
        db, course_id=course.id, limit=page_size, offset=(page - 1) * page_size
    )
    total = await discussions_repo.count_for_course(db, course_id=course.id)
    return Page(
        items=[_to_list_item(d, rc, la) for d, rc, la in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/courses/{course_id}/discussions",
    response_model=DiscussionDetail,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("10/minute")
async def create_discussion(
    course_id: str,
    payload: DiscussionCreate,
    user: CurrentUser,
    db: DBSession,
    request: Request,
    response: Response,
) -> DiscussionDetail:
    d = await discussions_service.create_discussion(
        db, course_id=course_id, user=user, payload=payload
    )
    fresh = await discussions_repo.get(db, d.id)
    return _to_detail(fresh)


@router.get("/discussions/{discussion_id}", response_model=DiscussionDetail)
async def get_discussion(
    discussion_id: str, viewer: OptionalUser, db: DBSession
) -> DiscussionDetail:
    d = await discussions_repo.get(db, discussion_id)
    if not d:
        raise NotFoundError("Discussion not found", code="discussion.not_found")
    course = await courses_repo.get_course(db, d.course_id)
    if not course or not await courses_service.can_view_course(db, course, viewer):
        raise NotFoundError("Discussion not found", code="discussion.not_found")
    return _to_detail(d)


@router.patch("/discussions/{discussion_id}", response_model=DiscussionDetail)
async def update_discussion(
    discussion_id: str,
    payload: DiscussionUpdate,
    user: CurrentUser,
    db: DBSession,
) -> DiscussionDetail:
    await discussions_service.update_discussion(
        db, discussion_id=discussion_id, user=user, payload=payload
    )
    fresh = await discussions_repo.get(db, discussion_id)
    return _to_detail(fresh)


@router.delete("/discussions/{discussion_id}", response_model=OkResponse)
async def delete_discussion(discussion_id: str, user: CurrentUser, db: DBSession) -> OkResponse:
    await discussions_service.delete_discussion(db, discussion_id=discussion_id, user=user)
    return OkResponse()


@router.post(
    "/discussions/{discussion_id}/replies",
    response_model=DiscussionReplyOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("20/minute")
async def reply_to_discussion(
    discussion_id: str,
    payload: DiscussionReplyCreate,
    user: CurrentUser,
    db: DBSession,
    request: Request,
    response: Response,
) -> DiscussionReplyOut:
    r = await discussions_service.reply(db, discussion_id=discussion_id, user=user, payload=payload)
    return _to_reply(r, author=user)


@router.delete("/discussions/replies/{reply_id}", response_model=OkResponse)
async def delete_reply(reply_id: str, user: CurrentUser, db: DBSession) -> OkResponse:
    await discussions_service.delete_reply(db, reply_id=reply_id, user=user)
    return OkResponse()
