"""Course, module, lesson, enrollment, review models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class CourseStatus(StrEnum):
    draft = "draft"
    published = "published"
    archived = "archived"


class Visibility(StrEnum):
    """Sharing intent — owner-controlled, orthogonal to ``status`` (ADR-0026 §1).

    Default ``private``. A course is only ever publicly discoverable when
    ``visibility==public`` AND ``status==published`` AND
    ``moderation_state==approved`` (see ``app.services.visibility``). The
    ``unlisted`` value is deferred (FR-VIS-20).
    """

    private = "private"
    public = "public"


class ModerationState(StrEnum):
    """Admin/system authority axis — net-new, default ``none`` (ADR-0026 §1).

    Never a value of ``status`` or ``visibility``. **Sticky**: never reset to
    ``none`` on unpublish/archive (R-C2). ``none`` is NOT listable (R-C1′);
    only ``approved`` lists.
    """

    none = "none"
    pending_review = "pending_review"
    approved = "approved"
    rejected = "rejected"
    delisted = "delisted"


class Difficulty(StrEnum):
    beginner = "beginner"
    intermediate = "intermediate"
    advanced = "advanced"


class LessonType(StrEnum):
    text = "text"
    video = "video"
    image = "image"
    file = "file"
    quiz = "quiz"


class Subject(IdMixin, TimestampMixin, Base):
    __tablename__ = "subjects"

    title: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(140), unique=True, nullable=False, index=True)

    courses: Mapped[list[Course]] = relationship(back_populates="subject")


class Tag(IdMixin, TimestampMixin, Base):
    __tablename__ = "tags"

    name: Mapped[str] = mapped_column(String(60), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)


course_tags = Table(
    "course_tags",
    Base.metadata,
    Column("course_id", ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_course_tags_tag_id", "tag_id"),
)


class Course(IdMixin, TimestampMixin, Base):
    __tablename__ = "courses"
    # `slug` uniqueness is enforced via a *partial* unique index that
    # only considers live rows (`deleted_at IS NULL`). Soft-deleted
    # courses keep their slug, but a fresh course (or restored one)
    # can reclaim a freed slug without colliding. See migration 0008
    # and the rebuild Fix B3 regression test.
    __table_args__ = (
        Index("ix_courses_status_subject", "status", "subject_id"),
        Index("ix_courses_published_at", "published_at"),
        Index(
            "uq_courses_slug_live",
            "slug",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_courses_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
        # The consolidated catalog/ACL index (ADR-0026 §3, design-spec §2.5
        # consolidates ADR-0029's ix_courses_acl into this one by appending
        # owner_id). Partial on live rows so soft-deleted courses never sit in
        # the listing hot path. Migration 0033 builds it CONCURRENTLY; 0044
        # rebuilds it with ``quarantined = false`` in the partial WHERE.
        Index(
            "ix_courses_listed",
            "visibility",
            "moderation_state",
            "status",
            "subject_id",
            "owner_id",
            # ``quarantined = false`` in the partial WHERE keeps the listing
            # predicate index-covered after migration 0044 (DR-18-R2).
            postgresql_where=text("deleted_at IS NULL AND quarantined = false"),
        ),
        # F3 (S6 gate): the admin moderation queue's "needs re-review" arm reads
        # ``review_flagged_at IS NOT NULL``. Partial index keeps that scan small —
        # only the handful of flagged-but-still-listed courses are indexed
        # (migration 0047).
        Index(
            "ix_courses_review_flagged",
            "review_flagged_at",
            postgresql_where=text("review_flagged_at IS NOT NULL"),
        ),
        # Clone provenance lookups (ADR-0028 §"Index for clone read + lineage").
        # ``ix_courses_origin_course_id`` serves FR-CLONE-24 ("who cloned this")
        # and the S4.8 read-time ``origin_available`` re-resolution; the root
        # index supports lineage analytics. Built CONCURRENTLY in migration 0048.
        Index("ix_courses_origin_course_id", "origin_course_id"),
        Index("ix_courses_root_origin", "root_origin_course_id"),
    )

    owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    subject_id: Mapped[str] = mapped_column(
        ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), nullable=False, index=True)
    overview: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Bullet list of "what you'll learn" outcomes shown above the
    # syllabus on the detail page. Stored as JSONB so the API can
    # validate length / item-count via Pydantic without a separate
    # table. List ordering is the display order; instructors hand-
    # sort during editing.
    learning_outcomes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]", default=list
    )
    cover_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    difficulty: Mapped[Difficulty] = mapped_column(
        String(20), nullable=False, default=Difficulty.beginner
    )
    status: Mapped[CourseStatus] = mapped_column(
        String(20), nullable=False, default=CourseStatus.draft, index=True
    )
    # Sharing intent + admin authority (ADR-0026 §1) — same no-TypeDecorator
    # String(20) pattern as ``status``, so reads return a plain str. Default
    # private/none keeps the catalog behaviour identical post-backfill (every
    # live-published course is backfilled to public+approved by migration 0033).
    visibility: Mapped[Visibility] = mapped_column(
        String(20),
        nullable=False,
        server_default=Visibility.private.value,
        default=Visibility.private,
    )
    moderation_state: Mapped[ModerationState] = mapped_column(
        String(20),
        nullable=False,
        server_default=ModerationState.none.value,
        default=ModerationState.none,
        index=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Full-quarantine flag (DR-18-R2 / migration 0044). Set TRUE only by the
    # admin hard-removal moderation action for reason ∈ {csam, illegal} (NOT
    # severe_abuse); cleared only by admin. Single source of truth for the
    # legally-sensitive case in BOTH the Python authorizer (can_view_course)
    # AND the SQL clauses (publicly_listed_sql / retrieval_acl_clause) — a
    # quarantined course is invisible everywhere, even to enrolled learners.
    quarantined: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # F3 (S6 gate / R-S11): an APPROVED course that accumulates enough OPEN user
    # reports is flagged for admin re-review by stamping this timestamp — WITHOUT
    # touching ``moderation_state`` (which stays ``approved`` so the course stays
    # publicly listed; a weak signal must never auto-unlist a vetted course). The
    # admin moderation queue surfaces flagged courses out-of-band; every admin
    # transition (approve/reject/delist/relist/remove) clears it. Migration 0047.
    review_flagged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # ----- Clone provenance (ADR-0028 §"Data model changes") -----
    # Server-written ONCE at clone time, never client-writable (CourseCreate/
    # CourseUpdate carry ``extra="forbid"`` — S4.5). All nullable: a from-scratch
    # course has no origin. FKs are ``ondelete="SET NULL"`` so a hard admin purge
    # of an origin course/owner nulls the pointer while the snapshot text persists
    # (lineage survives; ADR-0028 §"Reconciliation note"). In normal self-serve
    # account deletion (anonymize-in-place, ADR-0030) ``origin_owner_id`` stays
    # valid pointing at the tombstoned user and the read-time serializer (DR-19)
    # renders "a deleted user".
    origin_course_id: Mapped[str | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), nullable=True
    )
    origin_owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    root_origin_course_id: Mapped[str | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), nullable=True
    )
    origin_title_snapshot: Mapped[str | None] = mapped_column(String(200), nullable=True)
    origin_owner_name_snapshot: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cloned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Postgres GENERATED ALWAYS AS STORED tsvector over title + overview.
    # Read-only at the ORM level; populated and refreshed by the DB on
    # every insert/update. Search queries hit this column via the
    # ix_courses_search_vector GIN index (Alembic 0014).
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(title, '') || ' ' || coalesce(overview, ''))",
            persisted=True,
        ),
        nullable=True,
    )

    owner: Mapped[User] = relationship(back_populates="courses_owned", foreign_keys=[owner_id])
    subject: Mapped[Subject] = relationship(back_populates="courses")
    tags: Mapped[list[Tag]] = relationship(secondary=course_tags)

    modules: Mapped[list[Module]] = relationship(
        back_populates="course", cascade="all, delete-orphan", order_by="Module.order"
    )
    enrollments: Mapped[list[Enrollment]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    reviews: Mapped[list[Review]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )


class Module(IdMixin, TimestampMixin, Base):
    __tablename__ = "modules"
    __table_args__ = (
        UniqueConstraint("course_id", "order", name="uq_modules_course_order"),
        Index("ix_modules_course_id_order", "course_id", "order"),
    )

    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    course: Mapped[Course] = relationship(back_populates="modules")
    lessons: Mapped[list[Lesson]] = relationship(
        back_populates="module", cascade="all, delete-orphan", order_by="Lesson.order"
    )


class Lesson(IdMixin, TimestampMixin, Base):
    __tablename__ = "lessons"
    __table_args__ = (
        UniqueConstraint("module_id", "order", name="uq_lessons_module_order"),
        Index("ix_lessons_module_id_order", "module_id", "order"),
    )

    module_id: Mapped[str] = mapped_column(
        ForeignKey("modules.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    type: Mapped[LessonType] = mapped_column(String(20), nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_preview: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    module: Mapped[Module] = relationship(back_populates="lessons")
    progress: Mapped[list[LessonProgress]] = relationship(
        back_populates="lesson", cascade="all, delete-orphan"
    )


class Enrollment(IdMixin, TimestampMixin, Base):
    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("user_id", "course_id", name="uq_enrollments_user_course"),
        Index("ix_enrollments_course_id", "course_id"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Owner self-enrollment marker (R-M8' / FR-CLONE-16). True when the course
    # owner enrolled in their own course (clone auto-enroll or ADR-0026 self-
    # preview). ``_maybe_issue_certificate`` short-circuits on ``is_self`` so a
    # self-learner never mints a certificate/badge. server_default keeps the
    # ADD COLUMN instant (existing rows = false; no historical enrollment was a
    # self-enroll). See migration 0048.
    is_self: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    certificate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Signed Open Badges 3.0 / W3C VC credential — populated at the
    # same instant ``certificate_id`` is minted, by
    # ``app.services.enrollment._maybe_issue_certificate``. Nullable
    # because soft-historical rows from before Phase E5 don't have one
    # (the service can re-mint on demand).
    badge_credential: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    user: Mapped[User] = relationship(back_populates="enrollments")
    course: Mapped[Course] = relationship(back_populates="enrollments")
    lesson_progress: Mapped[list[LessonProgress]] = relationship(
        back_populates="enrollment", cascade="all, delete-orphan"
    )


class LessonProgress(IdMixin, TimestampMixin, Base):
    __tablename__ = "lesson_progress"
    __table_args__ = (
        UniqueConstraint("enrollment_id", "lesson_id", name="uq_lp_enrollment_lesson"),
        Index("ix_lp_lesson_id", "lesson_id"),
    )

    enrollment_id: Mapped[str] = mapped_column(
        ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id: Mapped[str] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    enrollment: Mapped[Enrollment] = relationship(back_populates="lesson_progress")
    lesson: Mapped[Lesson] = relationship(back_populates="progress")


class Review(IdMixin, TimestampMixin, Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("author_id", "course_id", name="uq_reviews_author_course"),
        CheckConstraint("rating >= 1 AND rating <= 5", name="rating_range"),
        Index("ix_reviews_course_id_rating", "course_id", "rating"),
    )

    author_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    author: Mapped[User] = relationship(back_populates="reviews")
    course: Mapped[Course] = relationship(back_populates="reviews")
