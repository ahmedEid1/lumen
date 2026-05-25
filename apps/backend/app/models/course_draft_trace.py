"""CourseDraftTrace — one row per step in a self-critique authoring run.

Lumen v2 Phase I3. The schema-specific sibling of :class:`AgentTrace`
(H7). Where ``agent_traces`` is the generic substrate (tutor + any
future agentic surface), ``course_draft_traces`` is purpose-built
for the authoring critique-revise loop: every researcher / outliner
/ critic / reviser / lesson_drafter / final_critic step lands here.

Why a separate table, not just more ``agent_traces`` rows:

1. **Distinct read pattern.** The instructor's studio trace viewer
   wants every step for a single ``draft_id`` in chronological
   order, scoped to one specific instructor. The admin tracer dashboard
   queries ``agent_traces`` cross-feature. Keeping authoring traces in
   their own table avoids interleaving the instructor-facing surface
   with system-wide observability — and lets the instructor query
   without admin gating.

2. **Authoring-specific FKs.** Course id is meaningful here
   (the trace anchors to a real course row, once one is minted), and
   a ``draft_id`` groups all steps from one drafting run before any
   course exists. ``agent_traces`` is course-agnostic; bolting these
   FKs onto it would clutter the generic substrate.

3. **Tree shape mirrors :class:`AgentTrace`.** ``parent_trace_id`` is
   self-referential FK; ``parent_call_id`` links to ``llm_calls.id``.
   The frontend timeline reads rows in insertion order and groups
   them by ``draft_id``.

Fields:

* ``id`` — 21-char nanoid (via :class:`IdMixin`). Used as ``trace_id``
  in the spec; we keep the column name ``id`` for IdMixin consistency.
* ``draft_id`` — opaque string that groups every step of one
  ``draft_course`` call. The orchestrator mints a fresh nanoid at
  the start of the run and threads it through every step.
* ``course_id`` — FK → ``courses.id``, nullable. Populated once the
  course row exists; pre-outline-acceptance steps (researcher,
  early critic) may run before any course is minted.
* ``user_id`` — instructor running the draft. Plain ``String(64)``
  (no FK) so the same ``"__system__"`` sentinel pattern as
  ``llm_calls`` / ``agent_traces`` is available for batch/eval work,
  but in practice this is always a real instructor id.
* ``step`` — open-ended string: ``"researcher" | "outliner" |
  "critic" | "reviser" | "lesson_drafter" | "final_critic"``. Kept
  string so adding new step kinds doesn't need a migration.
* ``step_index`` — 0-based ordering within the draft. Lets the
  timeline render without sorting by created_at (which can collide
  inside a single async batch).
* ``parent_call_id`` — FK → ``llm_calls.id`` (nullable). The cost-
  meter row spawned by this step's underlying LLM call. Nullable
  because some steps don't issue an LLM call (researcher's Tavily
  hop doesn't go through ``call_logged``).
* ``parent_trace_id`` — self-referential FK for the tree. Reserved
  for future sub-trace expansion; v1 emits a flat sibling list.
* ``payload`` — JSONB blob. Schema-by-convention; see module
  docstring in :mod:`app.services.authoring_orchestrator` for the
  per-step shapes.
* ``duration_ms`` — wall-clock duration for the step.
* ``status`` — ``"ok" | "error"``.
* ``created_at`` — tz-aware, server default ``now()``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin

# Status literals — exported so callers don't sprinkle string
# literals across the codebase. Same shape as ``AgentTrace``'s
# status constants on purpose; the trace viewer uses the same
# colour scheme for ok / error rows.
DRAFT_STATUS_OK = "ok"
DRAFT_STATUS_ERROR = "error"

# Step kind constants — exported so the orchestrator and the tests
# don't ship raw string literals everywhere. The column itself
# stays open-ended (String(64)) so future steps can be added
# without a migration.
DRAFT_STEP_RESEARCHER = "researcher"
DRAFT_STEP_OUTLINER = "outliner"
DRAFT_STEP_CRITIC = "critic"
DRAFT_STEP_REVISER = "reviser"
DRAFT_STEP_LESSON_DRAFTER = "lesson_drafter"
DRAFT_STEP_FINAL_CRITIC = "final_critic"


class CourseDraftTrace(IdMixin, Base):
    """One row per step in a self-critique authoring run.

    See module docstring for the full design rationale. Indexes are
    optimised for the three read patterns we actually use:

    * ``(draft_id, step_index)`` — the studio timeline view.
    * ``(course_id, created_at desc)`` — "show me the trace for this
      course's last draft."
    * ``(user_id, created_at desc)`` — instructor's recent activity.
    """

    __tablename__ = "course_draft_traces"
    __table_args__ = (
        # Studio timeline — the primary read path. The instructor
        # opens the draft page; we fetch every row for the draft in
        # step order. Composite index lets Postgres serve the
        # whole timeline from one b-tree scan.
        Index(
            "ix_course_draft_traces_draft_id_step_index",
            "draft_id",
            "step_index",
        ),
        # Course-scoped lookup — "show me the trace tied to this
        # course id, most recent first." Used by the read endpoint
        # that the instructor's studio surface hits with a course id.
        Index(
            "ix_course_draft_traces_course_created",
            "course_id",
            "created_at",
        ),
        # Per-instructor recent activity — for future "your recent
        # AI drafts" surfaces and admin observability roll-ups.
        Index(
            "ix_course_draft_traces_user_created",
            "user_id",
            "created_at",
        ),
    )

    # Groups every step of one ``draft_course`` orchestrator call.
    # Not a FK — there's no parent ``drafts`` table; the draft_id is
    # just an opaque correlation token the orchestrator mints with
    # ``new_id()``. Indexed via the composite above.
    draft_id: Mapped[str] = mapped_column(String(64), nullable=False, index=False)
    # Nullable because the researcher + first outliner + early
    # critic steps run before the course row exists. Once the
    # orchestrator persists the course, every subsequent step is
    # written with the resolved id, AND the earlier rows are
    # back-filled with the same id so the course-scoped lookup
    # returns the full timeline. SET NULL on delete so an admin
    # purging a course doesn't cascade away the forensic trail.
    course_id: Mapped[str | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"),
        nullable=True,
    )
    # FK to ``users.id`` because in practice this is always a real
    # instructor. ``ondelete="CASCADE"`` matches the LearningPath
    # convention — a user's removal takes their drafts' traces
    # with them.
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    step: Mapped[str] = mapped_column(String(64), nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    parent_call_id: Mapped[str | None] = mapped_column(
        ForeignKey("llm_calls.id", ondelete="SET NULL"),
        nullable=True,
    )
    parent_trace_id: Mapped[str | None] = mapped_column(
        ForeignKey("course_draft_traces.id", ondelete="CASCADE"),
        nullable=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = [
    "DRAFT_STATUS_ERROR",
    "DRAFT_STATUS_OK",
    "DRAFT_STEP_CRITIC",
    "DRAFT_STEP_FINAL_CRITIC",
    "DRAFT_STEP_LESSON_DRAFTER",
    "DRAFT_STEP_OUTLINER",
    "DRAFT_STEP_RESEARCHER",
    "DRAFT_STEP_REVISER",
    "CourseDraftTrace",
]
