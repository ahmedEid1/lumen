"""Discussion subscriptions — "watch this thread for updates".

Iter 79 already notifies the thread *author* on every reply, which
closes the "did anyone answer my question?" loop. But a non-author
who finds a useful thread had no way to get pinged on subsequent
replies — they'd have to manually re-visit.

Iter 90 adds an opt-in subscribe per thread. GitHub's pattern: the
author is auto-subscribed; anyone who replies is auto-subscribed
(they've shown interest and probably want to know about followups);
anyone else can subscribe via an explicit button.

Stored as a single row per (user, discussion). Hard-delete on
unsubscribe — no soft-delete because the question of "is this user
subscribed to this thread?" is binary and the audit value of a
historical un-subscribe trail is zero.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.discussion import Discussion
    from app.models.user import User


class DiscussionSubscription(IdMixin, TimestampMixin, Base):
    __tablename__ = "discussion_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "discussion_id", name="uq_discussion_subscriptions_user_thread"
        ),
        Index("ix_discussion_subscriptions_discussion_id", "discussion_id"),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    discussion_id: Mapped[str] = mapped_column(
        ForeignKey("discussions.id", ondelete="CASCADE"), nullable=False
    )

    user: Mapped[User] = relationship()
    discussion: Mapped[Discussion] = relationship()
