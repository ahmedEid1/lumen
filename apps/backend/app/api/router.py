"""Versioned root router."""

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    ai_authoring,
    auth,
    badges,
    catalog,
    certificates,
    content_ingest,
    courses,
    discussions,
    enrollments,
    health,
    notifications,
    reviews,
    reviews_queue,
    search,
    tutor,
    uploads,
    users,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(catalog.router, tags=["catalog"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(courses.router, prefix="/courses", tags=["courses"])
api_router.include_router(enrollments.router, prefix="/me", tags=["enrollments"])
api_router.include_router(reviews.router, prefix="/courses", tags=["reviews"])
api_router.include_router(uploads.router, prefix="/uploads", tags=["uploads"])
api_router.include_router(notifications.router, prefix="/me/notifications", tags=["notifications"])
api_router.include_router(reviews_queue.router, prefix="/me/reviews", tags=["reviews-queue"])
api_router.include_router(certificates.router, prefix="/certificates", tags=["certificates"])
api_router.include_router(badges.router, prefix="/credentials", tags=["badges"])
api_router.include_router(discussions.router, tags=["discussions"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
# Content ingest (Phase E3) — paste a URL, get a draft course.
api_router.include_router(
    content_ingest.router, prefix="/studio/ingest", tags=["studio-ingest"]
)
# Tutor (Phase E1) — mounts both course-scoped routes
# (``/courses/{id}/tutor/conversations``) and conversation-scoped
# routes (``/tutor/conversations/{id}``) so we let the router root
# inherit the ``/api/v1`` prefix and the module file declares its
# own paths.
api_router.include_router(tutor.router, tags=["tutor"])
# AI-assisted authoring (Phase E2) — outline + lesson body + quiz
# generation. All four endpoints share the ``/studio/ai`` prefix and
# the per-user 5/minute rate limit declared inside the module.
api_router.include_router(
    ai_authoring.router, prefix="/studio", tags=["studio-ai"]
)
