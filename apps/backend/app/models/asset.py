"""Uploaded asset metadata (objects live in S3/MinIO)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class Asset(IdMixin, TimestampMixin, Base):
    __tablename__ = "assets"

    owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(
        String(40), nullable=False, index=True
    )  # avatar | lesson | cover
    key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    public_url: Mapped[str | None] = mapped_column(String(700), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    owner: Mapped[User] = relationship()
