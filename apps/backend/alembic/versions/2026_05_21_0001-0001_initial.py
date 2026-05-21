"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-21
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # users
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("bio", sa.String(length=1000), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="student"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_created_at", "users", ["created_at"])

    # refresh tokens
    op.create_table(
        "auth_refresh_tokens",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_auth_refresh_tokens_user_id_users"),
        sa.ForeignKeyConstraint(["replaced_by_id"], ["auth_refresh_tokens.id"], ondelete="SET NULL", name="fk_auth_refresh_tokens_replaced_by_id"),
        sa.UniqueConstraint("token_hash", name="uq_auth_refresh_tokens_token_hash"),
    )
    op.create_index("ix_auth_refresh_tokens_token_hash", "auth_refresh_tokens", ["token_hash"], unique=True)
    op.create_index("ix_auth_refresh_tokens_user_id_revoked", "auth_refresh_tokens", ["user_id", "revoked_at"])

    # subjects
    op.create_table(
        "subjects",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=140), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("slug", name="uq_subjects_slug"),
    )
    op.create_index("ix_subjects_slug", "subjects", ["slug"], unique=True)
    op.create_index("ix_subjects_created_at", "subjects", ["created_at"])

    # tags
    op.create_table(
        "tags",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("slug", name="uq_tags_slug"),
    )
    op.create_index("ix_tags_slug", "tags", ["slug"], unique=True)
    op.create_index("ix_tags_created_at", "tags", ["created_at"])

    # courses
    op.create_table(
        "courses",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("subject_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=220), nullable=False),
        sa.Column("overview", sa.Text(), nullable=False, server_default=""),
        sa.Column("cover_url", sa.String(length=500), nullable=True),
        sa.Column("difficulty", sa.String(length=20), nullable=False, server_default="beginner"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT", name="fk_courses_owner_id_users"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="RESTRICT", name="fk_courses_subject_id_subjects"),
        sa.UniqueConstraint("slug", name="uq_courses_slug"),
    )
    op.create_index("ix_courses_slug", "courses", ["slug"], unique=True)
    op.create_index("ix_courses_owner_id", "courses", ["owner_id"])
    op.create_index("ix_courses_subject_id", "courses", ["subject_id"])
    op.create_index("ix_courses_status", "courses", ["status"])
    op.create_index("ix_courses_status_subject", "courses", ["status", "subject_id"])
    op.create_index("ix_courses_published_at", "courses", ["published_at"])
    op.create_index("ix_courses_created_at", "courses", ["created_at"])

    # course_tags
    op.create_table(
        "course_tags",
        sa.Column("course_id", sa.String(length=64), nullable=False),
        sa.Column("tag_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("course_id", "tag_id"),
    )
    op.create_index("ix_course_tags_tag_id", "course_tags", ["tag_id"])

    # modules
    op.create_table(
        "modules",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("course_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE", name="fk_modules_course_id_courses"),
        sa.UniqueConstraint("course_id", "order", name="uq_modules_course_order"),
    )
    op.create_index("ix_modules_course_id_order", "modules", ["course_id", "order"])
    op.create_index("ix_modules_created_at", "modules", ["created_at"])

    # lessons
    op.create_table(
        "lessons",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("module_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["module_id"], ["modules.id"], ondelete="CASCADE", name="fk_lessons_module_id_modules"),
        sa.UniqueConstraint("module_id", "order", name="uq_lessons_module_order"),
    )
    op.create_index("ix_lessons_module_id_order", "lessons", ["module_id", "order"])
    op.create_index("ix_lessons_created_at", "lessons", ["created_at"])

    # enrollments
    op.create_table(
        "enrollments",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("course_id", sa.String(length=64), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("certificate_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_enrollments_user_id_users"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE", name="fk_enrollments_course_id_courses"),
        sa.UniqueConstraint("user_id", "course_id", name="uq_enrollments_user_course"),
    )
    op.create_index("ix_enrollments_course_id", "enrollments", ["course_id"])
    op.create_index("ix_enrollments_created_at", "enrollments", ["created_at"])

    # lesson_progress
    op.create_table(
        "lesson_progress",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("enrollment_id", sa.String(length=64), nullable=False),
        sa.Column("lesson_id", sa.String(length=64), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("score", sa.SmallInteger(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["enrollment_id"], ["enrollments.id"], ondelete="CASCADE", name="fk_lesson_progress_enrollment_id"),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE", name="fk_lesson_progress_lesson_id"),
        sa.UniqueConstraint("enrollment_id", "lesson_id", name="uq_lp_enrollment_lesson"),
    )
    op.create_index("ix_lp_lesson_id", "lesson_progress", ["lesson_id"])
    op.create_index("ix_lesson_progress_created_at", "lesson_progress", ["created_at"])

    # reviews
    op.create_table(
        "reviews",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("author_id", sa.String(length=64), nullable=False),
        sa.Column("course_id", sa.String(length=64), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("author_id", "course_id", name="uq_reviews_author_course"),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_reviews_rating_range"),
    )
    op.create_index("ix_reviews_course_id_rating", "reviews", ["course_id", "rating"])
    op.create_index("ix_reviews_created_at", "reviews", ["created_at"])

    # chat_messages
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("course_id", sa.String(length=64), nullable=False),
        sa.Column("author_id", sa.String(length=64), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_chat_messages_course_id_created_at", "chat_messages", ["course_id", "created_at"])
    op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"])

    # notifications
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_notifications_user_id_read", "notifications", ["user_id", "read_at"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])

    # audit_events
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=60), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_audit_events_actor_id", "audit_events", ["actor_id"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_actor_id_created_at", "audit_events", ["actor_id", "created_at"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])

    # assets
    op.create_table(
        "assets",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("key", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("public_url", sa.String(length=700), nullable=True),
        sa.Column("meta", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("key", name="uq_assets_key"),
    )
    op.create_index("ix_assets_key", "assets", ["key"], unique=True)
    op.create_index("ix_assets_owner_id", "assets", ["owner_id"])
    op.create_index("ix_assets_kind", "assets", ["kind"])
    op.create_index("ix_assets_created_at", "assets", ["created_at"])


def downgrade() -> None:
    for tbl in [
        "assets",
        "audit_events",
        "notifications",
        "chat_messages",
        "reviews",
        "lesson_progress",
        "enrollments",
        "lessons",
        "modules",
        "course_tags",
        "courses",
        "tags",
        "subjects",
        "auth_refresh_tokens",
        "users",
    ]:
        op.drop_table(tbl)
