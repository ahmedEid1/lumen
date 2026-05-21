from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.course import CourseStatus, Difficulty, LessonType
from app.schemas.user import UserPublic

# ----- Subjects / Tags -----


class SubjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    slug: str
    total_courses: int | None = None


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str


# ----- Lesson payload variants -----


class TextLessonData(BaseModel):
    type: Literal["text"] = "text"
    body_markdown: str = Field(min_length=1)


class VideoLessonData(BaseModel):
    type: Literal["video"] = "video"
    url: str = Field(min_length=1, max_length=500)
    asset_key: str | None = None


class ImageLessonData(BaseModel):
    type: Literal["image"] = "image"
    asset_key: str = Field(min_length=1, max_length=500)
    alt: str = Field(default="", max_length=240)


class FileLessonData(BaseModel):
    type: Literal["file"] = "file"
    asset_key: str = Field(min_length=1, max_length=500)
    filename: str = Field(min_length=1, max_length=240)


class QuizChoice(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=400)


class QuizQuestion(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    prompt: str = Field(min_length=1, max_length=1000)
    kind: Literal["single", "multiple", "short"]
    choices: list[QuizChoice] = Field(default_factory=list, max_length=10)
    answer_keys: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _validate(self) -> QuizQuestion:
        if self.kind in {"single", "multiple"}:
            if not self.choices:
                raise ValueError("choice-based question requires choices")
            ids = {c.id for c in self.choices}
            if not set(self.answer_keys).issubset(ids):
                raise ValueError("answer_keys must reference choice ids")
            if self.kind == "single" and len(self.answer_keys) != 1:
                raise ValueError("single-choice expects exactly one answer_key")
        else:  # short
            if self.choices:
                raise ValueError("short-answer questions must have no choices")
        return self


class QuizLessonData(BaseModel):
    type: Literal["quiz"] = "quiz"
    pass_score: int = Field(ge=0, le=100, default=60)
    questions: list[QuizQuestion] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _unique_question_ids(self) -> QuizLessonData:
        ids = [q.id for q in self.questions]
        if len(set(ids)) != len(ids):
            raise ValueError("question ids must be unique within a quiz")
        return self


LessonData = Annotated[
    TextLessonData | VideoLessonData | ImageLessonData | FileLessonData | QuizLessonData,
    Field(discriminator="type"),
]


# ----- Lessons -----


class LessonCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    type: LessonType
    duration_seconds: int | None = Field(default=None, ge=0, le=60 * 60 * 8)
    is_preview: bool = False
    data: LessonData


class LessonUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    duration_seconds: int | None = Field(default=None, ge=0, le=60 * 60 * 8)
    is_preview: bool | None = None
    data: LessonData | None = None


class LessonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    type: LessonType
    order: int
    is_preview: bool = False
    # Populated by the course-detail builder when the viewer is enrolled.
    # Other endpoints leave it at False — they don't have a learner context.
    completed: bool = False
    duration_seconds: int | None = None
    data: dict[str, Any]


# ----- Modules -----


class ModuleCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)


class ModuleUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)


class ModuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str
    order: int
    lessons: list[LessonOut] = Field(default_factory=list)


# ----- Courses -----


class CourseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    subject_id: str
    overview: str = Field(default="", max_length=10_000)
    difficulty: Difficulty = Difficulty.beginner
    tag_ids: list[str] = Field(default_factory=list, max_length=20)
    cover_url: str | None = Field(default=None, max_length=500)


class CourseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    subject_id: str | None = None
    overview: str | None = Field(default=None, max_length=10_000)
    difficulty: Difficulty | None = None
    tag_ids: list[str] | None = Field(default=None, max_length=20)
    cover_url: str | None = Field(default=None, max_length=500)
    status: CourseStatus | None = None


class CourseListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    slug: str
    overview: str
    difficulty: Difficulty
    cover_url: str | None = None
    status: CourseStatus
    is_featured: bool
    published_at: datetime | None = None
    created_at: datetime
    owner: UserPublic
    subject: SubjectOut
    tags: list[TagOut] = Field(default_factory=list)
    modules_count: int = 0
    enrollments_count: int = 0
    avg_rating: float | None = None


class CourseDetail(CourseListItem):
    modules: list[ModuleOut] = Field(default_factory=list)
    is_enrolled: bool = False
    is_bookmarked: bool = False
    progress_pct: float = 0.0


# ----- Enrollment & progress -----


class EnrollmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course: CourseListItem
    created_at: datetime
    completed_at: datetime | None = None
    certificate_id: str | None = None
    progress_pct: float = 0.0


class ProgressUpdate(BaseModel):
    completed: bool = True
    payload: dict[str, Any] = Field(default_factory=dict)


# ----- Reviews -----


class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    body: str = Field(default="", max_length=4000)


class ReviewUpdate(ReviewCreate):
    pass


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    rating: int
    body: str
    created_at: datetime
    updated_at: datetime
    author: UserPublic


# ----- Ordering -----


class OrderUpdateRequest(BaseModel):
    """Map of id → desired zero-based order."""

    order: dict[str, int] = Field(min_length=1, max_length=500)
