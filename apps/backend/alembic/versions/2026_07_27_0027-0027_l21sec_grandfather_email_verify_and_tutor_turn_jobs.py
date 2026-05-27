"""L21-Sec migrations.

Two coordinated changes that ship together for the L21+ streaming
tutor stack:

1. **Grandfather every existing user's `email_verified_at`.** L21-Sec
   begins gating the tutor on a verified email (the per-IP-cost-cap
   bypass would otherwise cost $7200/day at the v7 threat-model
   numbers). 100% of existing users have ``email_verified_at IS NULL``
   today; locking them out on deploy is unacceptable. Their
   ``registered`` action is their consent — backfill the column with
   ``created_at`` so they pass the gate on first hit after deploy.

   Audit row is written so an operator looking at the audit log can
   tell exactly which users were grandfathered. See
   ``app/main.py::_grandfather_unverified_on_boot`` for the boot-hook
   backstop that covers the deploy-window race (plan-v7 §V7-F9).

2. **Create the empty ``tutor_turn_jobs`` table.** Per ADR-0019, this
   is the row that the L21a streaming tutor's atomic phase fence
   updates and that the sweep beat job reads. Includes the
   ``reserved_cost_usd`` + ``reservation_ip_key`` columns from
   plan-v7 §V7-F2 so the sweep can release reservations atomically
   when a worker dies mid-turn.

   The table ships empty in L21-Sec — no producer yet. L21a wires the
   Celery task that fills it; L21b wires the SSE consumer that reads
   the related Redis stream. The empty table is harmless: the sweep
   beat job loops over an empty set; the streaming POST endpoint
   doesn't exist yet so nothing inserts rows.

Revision ID: 0027
Revises: 0026
Create Date: 2026-05-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ----------------------------------------------------------------
    # Part 1 — Grandfather email-verify state
    # ----------------------------------------------------------------
    # COALESCE is the idempotent shape — a re-run is a no-op because
    # any row whose email_verified_at is non-NULL is left as-is. The
    # RETURNING gives us an accurate count for the audit row (plan-v7
    # §V7-F13 — beats a separate SELECT before the UPDATE because
    # there's no race between the two queries).
    conn = op.get_bind()
    grandfathered = conn.execute(
        sa.text(
            """
            UPDATE users
            SET email_verified_at = COALESCE(email_verified_at, created_at)
            WHERE email_verified_at IS NULL
            RETURNING id
            """
        )
    ).fetchall()
    count = len(grandfathered)

    # Audit row — visible in /admin/audit. action shape matches the
    # existing convention (verb.namespace.target). The data jsonb
    # column stores the count + a sample of the first 100 ids so an
    # operator can spot-check.
    if count > 0:
        sample_ids = [row[0] for row in grandfathered[:100]]
        conn.execute(
            sa.text(
                """
                INSERT INTO audit_events (
                    id, actor_id, action, target_type, data, created_at, updated_at
                )
                VALUES (:id, NULL, :action, 'user', :data::jsonb, NOW(), NOW())
                """
            ),
            {
                "id": _short_id(),
                "action": "auth.bulk_grandfather_email_verify",
                "data": _as_json(
                    {"count": count, "sample_ids": sample_ids, "loop": "L21-Sec"}
                ),
            },
        )

    # ----------------------------------------------------------------
    # Part 2 — tutor_turn_jobs table (empty; producer lands in L21a)
    # ----------------------------------------------------------------
    op.create_table(
        "tutor_turn_jobs",
        sa.Column("id", sa.String(length=24), nullable=False),
        sa.Column("user_id", sa.String(length=24), nullable=False),
        sa.Column("conversation_id", sa.String(length=24), nullable=True),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("prompt_template_hash", sa.String(length=64), nullable=True),
        # plan-v7 §V7-F2 — reservation metadata so the sweep can
        # release the reserved cost atomically when a worker dies.
        sa.Column(
            "reserved_cost_usd",
            sa.Numeric(precision=10, scale=6),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("reservation_ip_key", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    # Partial index on the still-active states — the sweep job reads
    # this constantly (every 10-30 seconds). Limiting it to non-
    # terminal rows keeps the index tiny.
    op.create_index(
        "ix_tutor_turn_jobs_active_updated",
        "tutor_turn_jobs",
        ["status", "updated_at"],
        postgresql_where=sa.text("status IN ('pending', 'running', 'streaming')"),
    )

    # Per-user index for /me/tutor-turns/{tid} drill-down (L23).
    op.create_index(
        "ix_tutor_turn_jobs_user_created",
        "tutor_turn_jobs",
        ["user_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_tutor_turn_jobs_user_created", table_name="tutor_turn_jobs")
    op.drop_index("ix_tutor_turn_jobs_active_updated", table_name="tutor_turn_jobs")
    op.drop_table("tutor_turn_jobs")

    # Note: we do NOT undo the email-verify grandfather. Once those
    # rows have email_verified_at set, reverting that loses the
    # consent record. Downgrade is for schema rollback only; auth
    # state stays.


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------


def _short_id() -> str:
    """Generate a 21-char URL-safe nanoid for the audit row's id.

    Same as the application's :func:`app.core.ids.new_id` shape, but
    inlined here so the migration doesn't depend on importing the
    application module (Alembic runs migrations under a thin context).
    """
    import secrets

    return secrets.token_urlsafe(16)[:21]


def _as_json(d: dict) -> str:
    """JSON-encode for the JSONB INSERT bind. SQLAlchemy can take a
    Python dict for JSONB but psycopg's text bind variant is more
    predictable across drivers."""
    import json

    return json.dumps(d)
