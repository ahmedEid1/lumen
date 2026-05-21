"""Certificate download (synchronous render) + public verification."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.core.errors import ForbiddenError, NotFoundError
from app.models.course import Course, Enrollment
from app.models.user import User
from app.repositories import courses as courses_repo
from app.workers.tasks.certificates import render

router = APIRouter()


class CertificateVerifyOut(BaseModel):
    certificate_id: str
    course_id: str
    course_title: str
    course_slug: str
    learner_name: str
    issued_at: datetime


@router.get("/verify/{certificate_id}", response_model=CertificateVerifyOut)
async def verify_certificate(certificate_id: str, db: DBSession) -> CertificateVerifyOut:
    """Public lookup of a certificate by its opaque id.

    Returns the learner's *display name* and course — never the email or other
    PII. Used by the public ``/verify/[id]`` page so anyone with a certificate
    ID can confirm it was issued by this platform.
    """
    row = (
        await db.execute(
            select(Enrollment, Course, User)
            .join(Course, Course.id == Enrollment.course_id)
            .join(User, User.id == Enrollment.user_id)
            .where(Enrollment.certificate_id == certificate_id)
        )
    ).first()
    if not row:
        raise NotFoundError("Certificate not found", code="cert.not_found")
    enrollment, course, user = row
    issued = enrollment.completed_at or enrollment.updated_at
    return CertificateVerifyOut(
        certificate_id=certificate_id,
        course_id=course.id,
        course_title=course.title,
        course_slug=course.slug,
        learner_name=user.full_name or "Learner",
        issued_at=issued,
    )


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
