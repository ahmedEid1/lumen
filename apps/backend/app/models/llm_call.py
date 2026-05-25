"""LLMCall — one row per LLM invocation, with tokens, cost, and latency.

Lumen v2 Phase H1. Every LLM round-trip through ``app.services.llm`` is
recorded here so we can:

1. **Surface cost in the admin UI** — total $$ spent, by feature, by
   day, by user. Cheap reads off ``(feature, created_at)`` and
   ``(user_id, created_at)`` composite indexes.
2. **Enforce a per-user 24h budget guard** — the call wrapper sums
   ``cost_usd`` for the calling user over the last day and rejects
   the next call with ``status="budget_exceeded"`` (still persisted
   so the admin sees the spike).
3. **Audit any anomaly** — a failed call leaves a row with
   ``status="error"`` and ``error_kind`` set to the exception class
   name, so we can grep for spikes in 4xx/5xx from a vendor without
   trawling structlog.

``user_id`` design note. The column is **NOT NULL** and carries the
sentinel value ``"__system__"`` for calls that aren't tied to a
human user (the Phase H2 eval suite, the ingest pipeline's transcript
summariser). Keeping the column NOT NULL means the
``(user_id, created_at)`` composite index is dense and the budget
sum query never has to handle NULL semantics; the cost of one magic
string in our own code is small next to the cost of NULLable index
gymnastics across the admin rollups. Don't ever leak the sentinel
to a public API — admin routes filter it out for the per-user view.

Schema fields:

* ``call_id`` — 21-char nanoid, primary key, opaque (matches the
  rest of the codebase's URL-safe ID convention).
* ``feature`` — short slug (``"tutor"``, ``"authoring.outline"``,
  ``"authoring.lesson"``, ``"authoring.quiz"``, ``"ingest.youtube"``,
  ``"eval.judge"``, ...). Indexed alongside ``created_at`` for the
  "cost by feature this week" admin view.
* ``provider`` / ``model`` — denormalised provider + model strings.
  Persisting both means a future migration (e.g. swapping the
  ``llm_provider`` env) still keeps the historical cost attribution
  correct — the row remembers what it cost back then.
* ``prompt_tokens`` / ``completion_tokens`` — vendor-reported usage.
  For Noop we estimate ``len(prompt)//4`` / ``len(response)//4`` so
  the meter still works in test mode.
* ``cost_usd`` — ``Numeric(10, 6)``. Money math goes through
  ``Decimal`` everywhere; ``Numeric(10, 6)`` lets us land six
  significant fractional digits (sub-1¢ resolution) without
  overflowing on any plausible single-call cost.
* ``latency_ms`` — wall-clock ms around the provider call. The
  budget guard and admin rollups don't use this, but it's the
  cheapest "is the upstream slow?" signal.
* ``status`` — ``"ok" | "error" | "throttled" | "budget_exceeded"``.
  ``throttled`` is reserved for rate-limit / 429 from the upstream
  vendor (H2 will start populating it); for now H1 only ever writes
  ``ok``, ``error``, ``budget_exceeded``.
* ``error_kind`` — exception class name when ``status="error"``.
  Nullable elsewhere.
* ``created_at`` — tz-aware, server default ``now()``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin

# Sentinel ``user_id`` value used for system-initiated calls (eval
# suite, ingest pipelines). Imported by ``app.services.llm_call_log``
# and the admin API for filtering. Kept short and obviously-not-a-
# nanoid so it can never collide with a real user id.
SYSTEM_USER_ID = "__system__"

# Status literals — exported so callers don't sprinkle string
# literals across the codebase.
STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_THROTTLED = "throttled"
STATUS_BUDGET_EXCEEDED = "budget_exceeded"


class LLMCall(IdMixin, Base):
    """One row per LLM round-trip — see module docstring for the full picture."""

    __tablename__ = "llm_calls"
    __table_args__ = (
        # "Cost per user over the last 24h" — the budget guard query.
        Index(
            "ix_llm_calls_user_created",
            "user_id",
            "created_at",
        ),
        # "Cost by feature over a window" — the admin rollup.
        Index(
            "ix_llm_calls_feature_created",
            "feature",
            "created_at",
        ),
    )

    # ``IdMixin`` already declares ``id`` as the primary key; we
    # expose it under the more descriptive ``call_id`` name in
    # Pydantic DTOs at the API edge so the on-the-wire shape reads
    # naturally without renaming the underlying column.
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=False)
    feature: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    completion_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=False, default=Decimal("0"), server_default="0"
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    error_kind: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = [
    "STATUS_BUDGET_EXCEEDED",
    "STATUS_ERROR",
    "STATUS_OK",
    "STATUS_THROTTLED",
    "SYSTEM_USER_ID",
    "LLMCall",
]
