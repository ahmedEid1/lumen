"""SQLAlchemy ORM models — imported here so Alembic sees them all."""

from app.models.asset import Asset
from app.models.audit import AuditEvent
from app.models.chat import ChatMessage
from app.models.course import (
    Course,
    CourseStatus,
    Difficulty,
    Enrollment,
    Lesson,
    LessonProgress,
    LessonType,
    Module,
    Review,
    Subject,
    Tag,
    course_tags,
)
from app.models.notification import Notification, NotificationKind
from app.models.user import RefreshToken, Role, User

__all__ = [
    "Asset",
    "AuditEvent",
    "ChatMessage",
    "Course",
    "CourseStatus",
    "Difficulty",
    "Enrollment",
    "Lesson",
    "LessonProgress",
    "LessonType",
    "Module",
    "Notification",
    "NotificationKind",
    "RefreshToken",
    "Review",
    "Role",
    "Subject",
    "Tag",
    "User",
    "course_tags",
]
