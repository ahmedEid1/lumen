"""SQLAlchemy ORM models — imported here so Alembic sees them all."""

from app.models.asset import Asset
from app.models.audit import AuditEvent
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
from app.models.discussion import Discussion, DiscussionReply
from app.models.notification import Notification, NotificationKind
from app.models.quiz_attempt import QuizAttempt
from app.models.user import RefreshToken, Role, User

__all__ = [
    "Asset",
    "AuditEvent",
    "Course",
    "CourseStatus",
    "Difficulty",
    "Discussion",
    "DiscussionReply",
    "Enrollment",
    "Lesson",
    "LessonProgress",
    "LessonType",
    "Module",
    "Notification",
    "NotificationKind",
    "QuizAttempt",
    "RefreshToken",
    "Review",
    "Role",
    "Subject",
    "Tag",
    "User",
    "course_tags",
]
