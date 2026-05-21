"""Certificate download (synchronous render — small PDFs)."""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.api.deps import CurrentUser, DBSession
from app.core.errors import ForbiddenError, NotFoundError
from app.repositories import courses as courses_repo
from app.workers.tasks.certificates import render

router = APIRouter()


@router.get("/{course_id}.pdf", response_class=Response)
async def download_certificate(course_id: str, user: CurrentUser, db: DBSession) -> Response:
    enrollment = await courses_repo.get_enrollment(db, user_id=user.id, course_id=course_id)
    if not enrollment:
        raise ForbiddenError("Enroll first", code="cert.not_enrolled")
    if not enrollment.completed_at or not enrollment.certificate_id:
        raise ForbiddenError("Not yet earned", code="cert.not_earned")
    course = await courses_repo.get_course(db, course_id)
    if not course:
        raise NotFoundError("Course not found", code="course.not_found")

    pdf_bytes = render(
        learner_name=user.full_name or user.email,
        course_title=course.title,
        certificate_id=enrollment.certificate_id,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="lumen-{course.slug}.pdf"',
            "Cache-Control": "private, max-age=0, no-store",
        },
    )
