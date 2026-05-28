"""Course reviews."""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DBSession
from app.core.errors import NotFoundError
from app.repositories import courses as courses_repo
from app.schemas.common import OkResponse
from app.schemas.course import ReviewCreate, ReviewOut
from app.schemas.user import UserPublic
from app.services import reviews as reviews_service

router = APIRouter()


@router.get("/{course_id}/reviews", response_model=list[ReviewOut])
async def list_reviews(
    course_id: str,
    db: DBSession,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[ReviewOut]:
    course = await courses_repo.get_course(db, course_id)
    if not course:
        raise NotFoundError("Course not found", code="course.not_found")
    rows = await courses_repo.list_reviews_for_course(db, course.id, limit=limit, offset=offset)
    return [
        ReviewOut(
            id=r.id,
            rating=r.rating,
            body=r.body,
            created_at=r.created_at,
            updated_at=r.updated_at,
            author=UserPublic.model_validate(r.author),
        )
        for r in rows
    ]


@router.put("/{course_id}/reviews", response_model=ReviewOut, status_code=status.HTTP_200_OK)
async def upsert_review(
    course_id: str, payload: ReviewCreate, user: CurrentUser, db: DBSession
) -> ReviewOut:
    course = await courses_repo.get_course(db, course_id)
    if not course:
        raise NotFoundError("Course not found", code="course.not_found")
    review = await reviews_service.upsert(db, author=user, course=course, payload=payload)
    return ReviewOut(
        id=review.id,
        rating=review.rating,
        body=review.body,
        created_at=review.created_at,
        updated_at=review.updated_at,
        author=UserPublic.model_validate(user),
    )


@router.delete("/{course_id}/reviews", response_model=OkResponse)
async def delete_review(course_id: str, user: CurrentUser, db: DBSession) -> OkResponse:
    course = await courses_repo.get_course(db, course_id)
    if not course:
        raise NotFoundError("Course not found", code="course.not_found")
    await reviews_service.delete(db, author=user, course=course)
    return OkResponse()
