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
    ModerationState,
    Module,
    Review,
    Subject,
    Tag,
    Visibility,
    course_tags,
)
from app.models.course_draft_trace import CourseDraftTrace
from app.models.discussion import Discussion, DiscussionReply
from app.models.learning_path import LearningPath, LearningPathStep
from app.models.lesson_chunk import EMBEDDING_DIM, LessonChunk
from app.models.llm_call import LLMCall
from app.models.mcp_client import MCPClient
from app.models.moderation import ModerationEvent
from app.models.notification import Notification, NotificationKind
from app.models.quiz_attempt import QuizAttempt
from app.models.retrieval_audit import RetrievalAudit
from app.models.review_card import ReviewCard, ReviewCardState
from app.models.tutor_conversation import (
    TutorConversation,
    TutorMessage,
    TutorMessageRole,
)
from app.models.tutor_turn_job import (
    TERMINAL_TURN_STATUSES,
    TURN_STATUS_ABORTED,
    TURN_STATUS_COMPLETE,
    TURN_STATUS_FAILED,
    TURN_STATUS_PENDING,
    TURN_STATUS_RUNNING,
    TURN_STATUS_STREAMING,
    TutorTurnJob,
)
from app.models.user import RefreshToken, Role, User
from app.models.user_llm_credential import (
    VALIDATION_ERROR,
    VALIDATION_INVALID,
    VALIDATION_NEEDS_ATTENTION,
    VALIDATION_UNVALIDATED,
    VALIDATION_VALID,
    UserLLMCredential,
)

__all__ = [
    "EMBEDDING_DIM",
    "TERMINAL_TURN_STATUSES",
    "TURN_STATUS_ABORTED",
    "TURN_STATUS_COMPLETE",
    "TURN_STATUS_FAILED",
    "TURN_STATUS_PENDING",
    "TURN_STATUS_RUNNING",
    "TURN_STATUS_STREAMING",
    "VALIDATION_ERROR",
    "VALIDATION_INVALID",
    "VALIDATION_NEEDS_ATTENTION",
    "VALIDATION_UNVALIDATED",
    "VALIDATION_VALID",
    "AgentTrace",
    "Asset",
    "AuditEvent",
    "Course",
    "CourseDraftTrace",
    "CourseStatus",
    "Difficulty",
    "Discussion",
    "DiscussionReply",
    "Enrollment",
    "LLMCall",
    "LearningPath",
    "LearningPathStep",
    "Lesson",
    "LessonChunk",
    "LessonProgress",
    "LessonType",
    "MCPClient",
    "ModerationEvent",
    "ModerationState",
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
    "TutorTurnJob",
    "User",
    "UserLLMCredential",
    "Visibility",
    "course_tags",
]
