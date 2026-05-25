"""Course reviews."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, NotFoundError
from app.models.course import Course, Review
from app.models.notification import NotificationKind
from app.models.user import User
from app.repositories import courses as courses_repo
from app.repositories import notifications as notifications_repo

if TYPE_CHECKING:
    from app.schemas.course import ReviewCreate, ReviewUpdate


async def upsert(
    db: AsyncSession, *, author: User, course: Course, payload: ReviewCreate | ReviewUpdate
) -> Review:
    # Instructors can self-enroll in their own published course (to see what
    # students see). Without this guard they could then post a 5-star review
    # and inflate avg_rating — same anti-self-review rule every other review
    # platform enforces. The notification path already encodes this awareness
    # via ``if course.owner_id != author.id``; here we reject outright.
    if course.owner_id == author.id:
        raise ForbiddenError("You can't review your own course", code="review.self_review")
    enrollment = await courses_repo.get_enrollment(db, user_id=author.id, course_id=course.id)
    if not enrollment:
        raise ForbiddenError("Enroll first to review", code="review.enroll_first")

    existing = await courses_repo.get_review(db, author_id=author.id, course_id=course.id)
    if existing:
        existing.rating = payload.rating
        existing.body = payload.body
        return existing

    review = Review(
        author_id=author.id, course_id=course.id, rating=payload.rating, body=payload.body
    )
    db.add(review)
    await db.flush()
    if course.owner_id != author.id:
        await notifications_repo.create(
            db,
            user_id=course.owner_id,
            kind=NotificationKind.review_received,
            title=f"New review on {course.title}",
            body=f"{author.full_name or 'A student'} left a {payload.rating}-star review.",
            data={"course_id": course.id, "review_id": review.id, "rating": payload.rating},
        )
    return review


async def delete(db: AsyncSession, *, author: User, course: Course) -> None:
    existing = await courses_repo.get_review(db, author_id=author.id, course_id=course.id)
    if not existing:
        raise NotFoundError("Review not found", code="review.not_found")
    existing.deleted_at = datetime.now(UTC)
