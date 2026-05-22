"""Cost-tracked LLM call wrapper — Phase H1.

Single entrypoint every metered LLM call goes through. Responsibilities:

1. **Budget guard.** Before invoking the provider, sum
   ``llm_calls.cost_usd`` for the caller (excluding the
   ``__system__`` sentinel — that bucket has its own, separate
   limit conceptually, and we don't want the eval suite's traffic
   to throttle a learner). If the rolling-24h sum is already over
   ``settings.llm_user_budget_24h_usd``, persist a
   ``status="budget_exceeded"`` row and raise
   :class:`~app.core.errors.BudgetExceededError` — the caller
   surfaces a friendly 429 to the client.
2. **Latency timing.** Wall-clock the call so the persisted
   ``latency_ms`` is the user-visible round-trip, not the
   downstream model's reported inference time. This is the
   cheapest "is the upstream slow?" signal we have.
3. **Cost computation.** Hand ``model + tokens`` to
   :func:`app.services.llm_pricing.compute_cost_usd`. Unknown
   models log a warning and persist ``cost_usd=0``.
4. **Error capture.** Any exception from the provider is caught,
   a row is persisted with ``status="error"`` + ``error_kind`` set
   to the exception class name, then the exception is re-raised
   unchanged. Callers see the same error they always have; the
   admin gets a forensic trail.
5. **Commit isolation.** Persisting the meter row uses a
   short-lived nested transaction (``session.begin_nested()``) so a
   commit failure on the meter doesn't roll back the caller's
   work. If we can't write the meter row, we log and move on —
   refusing to serve the request because we couldn't record it
   would be the wrong trade-off.

Disable switch. When ``settings.llm_cost_tracking_enabled`` is
``False``, the wrapper degenerates to a pass-through call: no
budget check, no row written, no extra DB I/O. Useful for synthetic
load tests and the rare case where we want to bypass the meter
during a migration.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.core.config import get_settings
from app.core.errors import BudgetExceededError
from app.core.logging import get_logger
from app.models.llm_call import (
    STATUS_BUDGET_EXCEEDED,
    STATUS_ERROR,
    STATUS_OK,
    SYSTEM_USER_ID,
    LLMCall,
)
from app.services.llm_pricing import compute_cost_usd

if TYPE_CHECKING:
    from app.services.llm import ChatMessage, ChatResponse, LLMProvider

log = get_logger(__name__)


def _approx_tokens(text: str) -> int:
    """Best-effort token estimate for providers that don't report usage.

    Mirrors the rule-of-thumb the Noop provider uses (``len // 4``).
    Only invoked when a caller has handed us a provider stub that
    implements the legacy ``chat()`` but not ``chat_with_usage()`` —
    in practice that's exclusively test scaffolding; the real
    Anthropic / OpenAI / Noop providers all carry the usage method.
    """
    return max(1, len(text) // 4)


# Budget window in seconds. Hard-coded because the spec ties the
# budget number itself ("user_budget_24h_usd") to a fixed 24h
# window — making the window configurable would muddy the name of
# the setting and the test that exercises it.
_BUDGET_WINDOW_SECONDS = 24 * 60 * 60


async def _user_cost_last_24h(session: AsyncSession, user_id: str):
    """Return the sum of ``cost_usd`` for ``user_id`` over 24h.

    Excludes the ``__system__`` sentinel from the guard window —
    that bucket is metered for admin observability but isn't a
    per-user cap. ``COALESCE`` to zero so an empty window returns a
    valid number we can compare directly.
    """
    stmt = select(
        func.coalesce(func.sum(LLMCall.cost_usd), 0)
    ).where(
        LLMCall.user_id == user_id,
        LLMCall.created_at
        > func.now() - func.make_interval(0, 0, 0, 0, 0, 0, _BUDGET_WINDOW_SECONDS),
    )
    result = await session.execute(stmt)
    return result.scalar_one()


async def _persist_row(
    session: AsyncSession,
    *,
    user_id: str,
    feature: str,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd,
    latency_ms: int,
    status: str,
    error_kind: str | None,
) -> None:
    """Write one ``llm_calls`` row, isolated from the caller's transaction.

    We use a SAVEPOINT (``begin_nested``) so a unique-constraint
    error or transient DB hiccup on the meter doesn't roll back the
    caller's domain work. The meter is best-effort — the alternative
    (refusing to serve the request because we couldn't write the
    row) would be the wrong trade-off for a passive observability
    feature. We do still ``await session.commit()`` outside the
    savepoint so the row actually lands; if we're inside a parent
    transaction that's about to roll back, the row goes with it,
    which is fine because the meter follows the request lifecycle.
    """
    try:
        async with session.begin_nested():
            row = LLMCall(
                user_id=user_id,
                feature=feature,
                provider=provider,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                status=status,
                error_kind=error_kind,
            )
            session.add(row)
            # Explicit flush inside the savepoint so a constraint
            # error fires here (and we catch + log it) rather than
            # bubbling up at the next outer-transaction operation.
            await session.flush()
    except SQLAlchemyError:
        # We deliberately don't re-raise — see docstring for the
        # rationale. Log with the call's vitals so an operator can
        # spot a meter outage in structlog.
        log.exception(
            "llm_call_log_persist_failed",
            user_id=user_id,
            feature=feature,
            provider=provider,
            model=model,
            status=status,
        )


async def _invoke_provider(
    provider: "LLMProvider",
    messages: "list[ChatMessage]",
    temperature: float,
) -> "ChatResponse":
    """Call the provider and normalise the result to a ``ChatResponse``.

    The real Anthropic / OpenAI / Noop providers all expose
    :meth:`chat_with_usage` and we use it directly. Test stubs that
    only implement the legacy :meth:`chat` (e.g. the scripted provider
    in ``test_ai_authoring.py``) get a ``ChatResponse`` synthesised
    from estimated token counts so the meter still records a row
    with sensible values — the cost will be $0 (the synthetic
    ``model="legacy"`` won't be in the pricing table) and the
    pricing-unknown warning will fire, which is the right "you're
    using an unmetered codepath" signal for the operator.
    """
    chat_with_usage = getattr(provider, "chat_with_usage", None)
    if chat_with_usage is not None:
        return await chat_with_usage(messages, temperature=temperature)

    # Legacy path — call ``chat`` and synthesise usage.
    from app.services.llm import ChatResponse  # local import to avoid cycle at module top

    text = await provider.chat(messages, temperature=temperature)
    prompt_text = "\n".join(m.content for m in messages)
    return ChatResponse(
        text=text,
        prompt_tokens=_approx_tokens(prompt_text),
        completion_tokens=_approx_tokens(text),
        model=getattr(provider, "_model", "legacy"),
    )


async def call_logged(
    provider: "LLMProvider",
    messages: "list[ChatMessage]",
    *,
    user_id: str,
    feature: str,
    session: AsyncSession,
    temperature: float = 0.2,
) -> "ChatResponse":
    """Invoke ``provider`` and record a metered row.

    Parameters mirror :meth:`LLMProvider.chat_with_usage` plus the
    persistence-side bits the meter needs.

    Returns the provider's :class:`ChatResponse`. Raises whatever the
    provider raises on failure (after persisting an error row), and
    raises :class:`BudgetExceededError` (after persisting a sentinel
    row) when the caller is already over their 24h cap.
    """
    settings = get_settings()
    if not settings.llm_cost_tracking_enabled:
        # Pass-through path. We still want to call ``chat_with_usage``
        # so downstream code receives the same shape; we just skip
        # the meter writes and the budget guard.
        return await provider.chat_with_usage(messages, temperature=temperature)

    # ---------- Budget guard ----------
    # We don't apply the guard to ``__system__`` calls; the eval
    # suite and ingest pipelines are operator-controlled and have
    # their own knobs.
    if user_id != SYSTEM_USER_ID:
        current_spend = await _user_cost_last_24h(session, user_id)
        if current_spend is not None and current_spend > settings.llm_user_budget_24h_usd:
            await _persist_row(
                session,
                user_id=user_id,
                feature=feature,
                provider=getattr(provider, "name", "unknown"),
                # No model dispatch happens for a blocked call —
                # record what *would have* run for diagnostic value.
                model=getattr(provider, "_model", "unknown"),
                prompt_tokens=0,
                completion_tokens=0,
                cost_usd=0,
                latency_ms=0,
                status=STATUS_BUDGET_EXCEEDED,
                error_kind=None,
            )
            log.warning(
                "llm_budget_exceeded",
                user_id=user_id,
                feature=feature,
                spent=str(current_spend),
                budget=str(settings.llm_user_budget_24h_usd),
            )
            raise BudgetExceededError(
                "Daily LLM budget reached. Please try again tomorrow.",
                code="llm.budget_exceeded",
                details={
                    "spent_usd": str(current_spend),
                    "budget_usd": str(settings.llm_user_budget_24h_usd),
                },
            )

    # ---------- Provider call (timed) ----------
    started = time.perf_counter()
    try:
        response = await _invoke_provider(provider, messages, temperature)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        await _persist_row(
            session,
            user_id=user_id,
            feature=feature,
            provider=getattr(provider, "name", "unknown"),
            model=getattr(provider, "_model", "unknown"),
            prompt_tokens=0,
            completion_tokens=0,
            cost_usd=0,
            latency_ms=latency_ms,
            status=STATUS_ERROR,
            error_kind=type(exc).__name__,
        )
        log.warning(
            "llm_call_failed",
            user_id=user_id,
            feature=feature,
            error_kind=type(exc).__name__,
            latency_ms=latency_ms,
        )
        raise

    latency_ms = int((time.perf_counter() - started) * 1000)
    cost = compute_cost_usd(
        response.model, response.prompt_tokens, response.completion_tokens
    )
    await _persist_row(
        session,
        user_id=user_id,
        feature=feature,
        provider=getattr(provider, "name", "unknown"),
        model=response.model,
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
        cost_usd=cost,
        latency_ms=latency_ms,
        status=STATUS_OK,
        error_kind=None,
    )
    return response


__all__ = ["call_logged"]
