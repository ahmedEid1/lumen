"""SQLAlchemy ORM models — imported here so Alembic sees them all."""

from app.models.agent_trace import AgentTrace
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
from app.models.learning_path import LearningPath, LearningPathStep
from app.models.lesson_chunk import EMBEDDING_DIM, LessonChunk
from app.models.llm_call import LLMCall
from app.models.mcp_client import MCPClient
from app.models.notification import Notification, NotificationKind
from app.models.quiz_attempt import QuizAttempt
from app.models.retrieval_audit import RetrievalAudit
from app.models.review_card import ReviewCard, ReviewCardState
from app.models.tutor_conversation import (
    TutorConversation,
    TutorMessage,
    TutorMessageRole,
)
from app.models.user import RefreshToken, Role, User

__all__ = [
    "AgentTrace",
    "Asset",
    "AuditEvent",
    "Course",
    "CourseStatus",
    "Difficulty",
    "Discussion",
    "DiscussionReply",
    "EMBEDDING_DIM",
    "Enrollment",
    "Lesson",
    "LLMCall",
    "LearningPath",
    "LearningPathStep",
    "LessonChunk",
    "LessonProgress",
    "LessonType",
    "MCPClient",
    "Module",
    "Notification",
    "NotificationKind",
    "QuizAttempt",
    "RefreshToken",
    "RetrievalAudit",
    "Review",
    "ReviewCard",
    "ReviewCardState",
    "Role",
    "Subject",
    "Tag",
    "TutorConversation",
    "TutorMessage",
    "TutorMessageRole",
    "User",
    "course_tags",
]
