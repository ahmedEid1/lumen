"""User and refresh-token models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.course import Course, Enrollment, Review


class Role(StrEnum):
    # Two-role collapse (ADR-0025 §D1). Phase A widens the set to tolerate
    # both the legacy ``student``/``instructor`` rows (until 0031 backfills
    # them to ``user``) and the new canonical ``user``. ``student`` and
    # ``instructor`` are removed in the evidence-gated Phase-D cut (S1.13);
    # keep them here so legacy rows load and stale request bodies don't crash
    # deserialization during the transition window (R-C5).
    student = "student"
    instructor = "instructor"
    user = "user"
    admin = "admin"


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(CITEXT(), unique=True, nullable=False, index=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # S1.8: the ORM-side default flips to `user` here; the DB `server_default`
    # flip is migration 0032 (Phase C). Both land in the narrowed-enum release.
    role: Mapped[Role] = mapped_column(String(20), nullable=False, default=Role.user, index=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # ADR-0030 §D1 / Migration 0030. Tombstone marker that distinguishes a
    # *deleted* (anonymize-in-place) account from a *suspended* one — both
    # share ``is_active=False``; the single discriminator is ``deleted_at IS
    # NOT NULL``. Nullable, no default; set only by ``delete_account``.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_login_attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Per-kind notification dispatch prefs (Phase D4). Shape:
    # ``{"<NotificationKind>": "off"|"in_app"|"email_immediate"|"digest_daily"}``
    # Missing keys default to ``"in_app"`` via :mod:`app.services.notification_prefs`
    # so existing users keep today's bell-only behaviour automatically.
    notification_prefs: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}", default=dict
    )

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    courses_owned: Mapped[list[Course]] = relationship(
        back_populates="owner",
        foreign_keys="Course.owner_id",
        # DR-6-R2 / ADR-0030 D1: ``save-update`` (NOT ``all, delete-orphan``).
        # Courses are user-visible content with their own soft-delete and a
        # deliberate ``Course.owner_id ondelete="RESTRICT"`` FK; orphan-
        # deleting them on a parent-collection mutation contradicts that
        # RESTRICT and would silently destroy courses (+ other users'
        # enrollments/reviews via their CASCADE FKs). Self-serve deletion is
        # anonymize-in-place and never ``session.delete(user)``; RESTRICT
        # remains the DB-level backstop. This is the ONE load-bearing cascade
        # change (DR-6-R2 supersedes the "change all three" over-correction).
        cascade="save-update",
    )
    enrollments: Mapped[list[Enrollment]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    reviews: Mapped[list[Review]] = relationship(
        back_populates="author", cascade="all, delete-orphan"
    )

    def is_instructor_or_admin(self) -> bool:
        return self.role in (Role.instructor, Role.admin)

    def is_admin(self) -> bool:
        return self.role == Role.admin


class RefreshToken(IdMixin, Base):
    __tablename__ = "auth_refresh_tokens"
    __table_args__ = (Index("ix_auth_refresh_tokens_user_id_revoked", "user_id", "revoked_at"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("auth_refresh_tokens.id", ondelete="SET NULL"), nullable=True
    )
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")
