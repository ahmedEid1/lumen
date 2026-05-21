"""Discussion service — authz and write paths.

Visibility rule reuses ``courses_service.can_view_course``: anyone
who can see the course can read its discussions. Posting (new
thread or reply) requires the same access — i.e. enrollment for
non-published courses, owner / admin always, anonymous-on-published
*reads* yes but writes no.

Deletion is soft (sets ``deleted_at``) and is allowed for the
author of the thread/reply OR an admin OR the course owner.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, NotFoundError
from app.models.course import Course
from app.models.discussion import Discussion, DiscussionReply
from app.models.notification import NotificationKind
from app.models.user import User
from app.repositories import courses as courses_repo
from app.repositories import discussions as discussions_repo
from app.repositories import notifications as notifications_repo
from app.services import courses as courses_service

if TYPE_CHECKING:
    from app.schemas.discussion import (
        DiscussionCreate,
        DiscussionReplyCreate,
        DiscussionUpdate,
    )


async def _course_for_write(db: AsyncSession, course_id: str, user: User) -> Course:
    course = await courses_repo.get_course(db, course_id)
    if not course:
        raise NotFoundError("Course not found", code="course.not_found")
    if not await courses_service.can_view_course(db, course, user):
        # Same posture other write paths take — don't confirm
        # existence to a caller who shouldn't see the course.
        raise NotFoundError("Course not found", code="course.not_found")
    return course


async def create_discussion(
    db: AsyncSession, *, course_id: str, user: User, payload: DiscussionCreate
) -> Discussion:
    course = await _course_for_write(db, course_id, user)
    d = Discussion(
        course_id=course.id,
        author_id=user.id,
        title=payload.title.strip(),
        body=payload.body.strip(),
    )
    db.add(d)
    await db.flush()
    return d


async def update_discussion(
    db: AsyncSession, *, discussion_id: str, user: User, payload: DiscussionUpdate
) -> Discussion:
    d = await discussions_repo.get(db, discussion_id)
    if not d:
        raise NotFoundError("Discussion not found", code="discussion.not_found")
    if not _can_edit(d, user, course_owner_id=None):
        # We don't have the course here, but the author-or-admin
        # check covers the common case. Re-fetching the course for
        # the owner-check is fine because edits are rare.
        course = await courses_repo.get_course(db, d.course_id)
        if not _can_edit(d, user, course_owner_id=course.owner_id if course else None):
            raise ForbiddenError("Cannot edit this discussion", code="discussion.forbidden")
    if payload.title is not None:
        d.title = payload.title.strip()
    if payload.body is not None:
        d.body = payload.body.strip()
    return d


async def delete_discussion(
    db: AsyncSession, *, discussion_id: str, user: User
) -> None:
    d = await discussions_repo.get(db, discussion_id)
    if not d:
        raise NotFoundError("Discussion not found", code="discussion.not_found")
    course = await courses_repo.get_course(db, d.course_id)
    if not _can_edit(d, user, course_owner_id=course.owner_id if course else None):
        raise ForbiddenError("Cannot delete this discussion", code="discussion.forbidden")
    d.deleted_at = datetime.now(timezone.utc)


async def reply(
    db: AsyncSession, *, discussion_id: str, user: User, payload: DiscussionReplyCreate
) -> DiscussionReply:
    d = await discussions_repo.get(db, discussion_id)
    if not d:
        raise NotFoundError("Discussion not found", code="discussion.not_found")
    # Replying is a write on the underlying course; gate the same way.
    await _course_for_write(db, d.course_id, user)
    r = DiscussionReply(
        discussion_id=d.id, author_id=user.id, body=payload.body.strip()
    )
    db.add(r)
    # Bump parent updated_at so list_for_course's last-activity
    # sort surfaces the bumped thread.
    d.updated_at = datetime.now(timezone.utc)
    await db.flush()
    # Ping the thread author — only if it's not themselves replying
    # (which would be a self-notification with no signal) and only
    # if the author still exists (author_id is SET NULL on user
    # delete; ``None`` means a deleted account, no inbox to ping).
    if d.author_id and d.author_id != user.id:
        await notifications_repo.create(
            db,
            user_id=d.author_id,
            kind=NotificationKind.discussion_reply,
            title=f"New reply on “{d.title}”",
            body=f"{user.full_name or 'A learner'} replied.",
            data={
                "discussion_id": d.id,
                "reply_id": r.id,
                "course_id": d.course_id,
            },
        )
    return r


async def delete_reply(
    db: AsyncSession, *, reply_id: str, user: User
) -> None:
    r = await discussions_repo.get_reply(db, reply_id)
    if not r:
        raise NotFoundError("Reply not found", code="reply.not_found")
    d = await discussions_repo.get(db, r.discussion_id)
    course = (
        await courses_repo.get_course(db, d.course_id) if d is not None else None
    )
    if not _can_edit(r, user, course_owner_id=course.owner_id if course else None):
        raise ForbiddenError("Cannot delete this reply", code="reply.forbidden")
    r.deleted_at = datetime.now(timezone.utc)


def _can_edit(
    obj: Discussion | DiscussionReply, user: User, *, course_owner_id: str | None
) -> bool:
    if user.is_admin():
        return True
    if obj.author_id == user.id:
        return True
    if course_owner_id is not None and course_owner_id == user.id:
        return True
    return False
