"""Course bookmarks (favorites)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.user import User


class Bookmark(IdMixin, TimestampMixin, Base):
    __tablename__ = "bookmarks"
    __table_args__ = (
        UniqueConstraint("user_id", "course_id", name="uq_bookmarks_user_course"),
        Index("ix_bookmarks_user_id_created_at", "user_id", "created_at"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)

    user: Mapped[User] = relationship()
    course: Mapped[Course] = relationship()
