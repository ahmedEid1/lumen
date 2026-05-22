"""Versioned root router."""

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    auth,
    catalog,
    certificates,
    courses,
    discussions,
    enrollments,
    health,
    notifications,
    reviews,
    search,
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
api_router.include_router(certificates.router, prefix="/certificates", tags=["certificates"])
api_router.include_router(discussions.router, tags=["discussions"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
