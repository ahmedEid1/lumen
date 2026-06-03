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
from app.core.errors import BudgetExceededError, QuotaExceededError
from app.core.logging import get_logger
from app.models.llm_call import (
    BILLING_BYOK,
    BILLING_PLATFORM,
    STATUS_BUDGET_EXCEEDED,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_QUOTA_EXCEEDED,
    SYSTEM_USER_ID,
    LLMCall,
)
from app.services.llm_pricing import compute_cost_usd

if TYPE_CHECKING:
    from app.services.byok import LLMContext
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
    """Return the sum of platform-billed ``cost_usd`` for ``user_id`` over 24h.

    Excludes the ``__system__`` sentinel from the guard window —
    that bucket is metered for admin observability but isn't a
    per-user cap. ``COALESCE`` to zero so an empty window returns a
    valid number we can compare directly.

    Gate-A fix: filters to ``billing_mode='platform'``. BYOK rows persist
    their real informational cost (the user's own-provider spend on priced
    models like gpt-4o-mini), and summing them here let own-key usage eat —
    and eventually trip — the PLATFORM dollar budget. BYOK is capped by the
    non-dollar request windows instead (charter decision 5 / DR-16).
    """
    stmt = select(func.coalesce(func.sum(LLMCall.cost_usd), 0)).where(
        LLMCall.user_id == user_id,
        LLMCall.billing_mode == BILLING_PLATFORM,
        LLMCall.created_at
        > func.now() - func.make_interval(0, 0, 0, 0, 0, 0, _BUDGET_WINDOW_SECONDS),
    )
    result = await session.execute(stmt)
    return result.scalar_one()


# S5.8 windows for the non-dollar request quota (DR-11/16). 24h matches the
# dollar window; 1h is the burst window.
_QUOTA_WINDOW_24H_SECONDS = 24 * 60 * 60
_QUOTA_WINDOW_1H_SECONDS = 60 * 60


async def _user_request_count(session: AsyncSession, user_id: str, window_seconds: int) -> int:
    """COUNT(*) of llm_calls for ``user_id`` in the last ``window_seconds``.

    Independent of dollars — a $0 BYOK call is still a row, so it still
    counts (the core DR-16 assertion that closes the $0 bypass). Index-
    covered by ``ix_llm_calls_user_created``.
    """
    stmt = select(func.count(LLMCall.id)).where(
        LLMCall.user_id == user_id,
        LLMCall.created_at > func.now() - func.make_interval(0, 0, 0, 0, 0, 0, window_seconds),
    )
    return int((await session.execute(stmt)).scalar_one() or 0)


def quota_limits(billing_mode: str) -> tuple[int, int]:
    """Return ``(limit_24h, limit_1h)`` for the billing mode (R-G1).

    Public: the streaming-turn enqueue path reuses these numbers for its
    BYOK request windows (Gate-A fix — streaming turns never produce
    ``llm_calls`` rows, so they enforce the same limits over
    ``tutor_turn_jobs`` instead).
    """
    s = get_settings()
    if billing_mode == BILLING_BYOK:
        # BYOK users get a higher 24h request ceiling (they pay their own
        # provider); the 1h burst window is shared.
        return int(s.byok_requests_24h), int(s.llm_user_request_quota_1h)
    return int(s.llm_user_request_quota_24h), int(s.llm_user_request_quota_1h)


# Backwards-compatible private alias (existing call sites/tests).
_quota_limits = quota_limits


async def user_request_count(session: AsyncSession, user_id: str, window_seconds: int) -> int:
    """Public window counter for the streaming enqueue path (Gate-A fix)."""
    return await _user_request_count(session, user_id, window_seconds)


async def record_streamed_turn_row(
    session: AsyncSession,
    *,
    user_id: str,
    provider: str,
    model: str,
    cost_usd: float,
    latency_ms: int,
    status: str,
    error_kind: str | None,
    billing_mode: str,
) -> None:
    """Persist an ``llm_calls`` row for a terminal streamed tutor turn.

    Gate-B fix / ADR-0027 §Consequences: streamed turns previously wrote no
    ``llm_calls`` row at all, so they escaped the non-dollar request windows
    and the admin ``billing_mode`` rollup. The worker calls this at the
    terminal transition. Token counts aren't plumbed through the stream
    usage events yet, so they persist as zero — the request COUNT and
    ``billing_mode``/``cost_usd`` are the quota- and rollup-bearing fields.
    """
    await _persist_row(
        session,
        user_id=user_id,
        feature="tutor.stream",
        provider=provider,
        model=model,
        prompt_tokens=0,
        completion_tokens=0,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        status=status,
        error_kind=error_kind,
        billing_mode=billing_mode,
    )


async def _check_request_quota(
    session: AsyncSession, *, user_id: str, billing_mode: str
) -> tuple[str, int, int] | None:
    """Return ``(dimension, used, limit)`` if over a quota, else ``None``.

    Checks the 24h ceiling then the 1h burst window. The provider is NOT
    invoked when this returns a tripped dimension.
    """
    limit_24h, limit_1h = _quota_limits(billing_mode)
    used_24h = await _user_request_count(session, user_id, _QUOTA_WINDOW_24H_SECONDS)
    if used_24h >= limit_24h:
        return ("requests_24h", used_24h, limit_24h)
    used_1h = await _user_request_count(session, user_id, _QUOTA_WINDOW_1H_SECONDS)
    if used_1h >= limit_1h:
        return ("requests_1h", used_1h, limit_1h)
    return None


async def _try_acquire_concurrency(user_id: str) -> tuple[object | None, str | None]:
    """Best-effort Redis concurrency lease. Fail-open on Redis-down (R-M7').

    Returns ``(redis_client, user_key)`` when a slot was acquired so the
    caller can release it; ``(None, None)`` when Redis is unreachable (the
    call proceeds — the DB COUNT is the hard guard) OR when leasing is
    skipped. Over-concurrency raises ``QuotaExceededError`` directly.
    """
    s = get_settings()
    try:
        import redis.asyncio as redis

        from app.core.cost_scripts import check_concurrency

        client = redis.Redis.from_url(s.redis_url, decode_responses=False)
        user_key = f"llm:concurrency:{user_id}"
        ok, current = await check_concurrency(
            client,
            user_key=user_key,
            max_concurrent=int(s.llm_max_concurrent),
            ttl_seconds=int(s.llm_provider_timeout_s) + 30,
        )
    except Exception:
        # Redis-down → fail-open. The DB COUNT backstop still applies.
        log.warning("llm_concurrency_lease_unavailable", user_id=user_id)
        return None, None
    if not ok:
        # Over the concurrency cap. Release nothing (we never acquired).
        raise QuotaExceededError(
            "Too many concurrent requests. Please wait a moment.",
            details={"dimension": "concurrency", "current": current},
        )
    return client, user_key


async def _release_concurrency_quiet(client: object | None, user_key: str | None) -> None:
    if client is None or user_key is None:
        return
    try:
        from app.core.cost_scripts import release_concurrency

        await release_concurrency(client, user_key=user_key)  # type: ignore[arg-type]
    except Exception:
        log.warning("llm_concurrency_release_failed", user_key=user_key)


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
    billing_mode: str = BILLING_PLATFORM,
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
                billing_mode=billing_mode,
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
    provider: LLMProvider,
    messages: list[ChatMessage],
    temperature: float,
) -> ChatResponse:
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
    provider: LLMProvider,
    messages: list[ChatMessage],
    *,
    user_id: str,
    feature: str,
    session: AsyncSession,
    temperature: float = 0.2,
    ctx: LLMContext | None = None,
    billing_mode: str | None = None,
) -> ChatResponse:
    """Invoke ``provider`` and record a metered row.

    Parameters mirror :meth:`LLMProvider.chat_with_usage` plus the
    persistence-side bits the meter needs.

    ``ctx``/``billing_mode`` (S5.8): when the caller built the provider via
    ``byok.build_provider`` it passes the returned billing_mode; the persisted
    row + the request-quota window are chosen accordingly. Defaults to
    platform so existing call sites are unchanged.

    Returns the provider's :class:`ChatResponse`. Raises whatever the
    provider raises on failure (after persisting an error row),
    :class:`BudgetExceededError` (platform dollar cap), or
    :class:`QuotaExceededError` (the non-dollar request/concurrency guard —
    DR-11/16; a sentinel ``quota_exceeded`` row is persisted and the provider
    is NOT invoked).
    """
    settings = get_settings()
    mode = billing_mode or (ctx.mode if ctx is not None else BILLING_PLATFORM)
    if mode not in (BILLING_PLATFORM, BILLING_BYOK):
        mode = BILLING_PLATFORM

    if not settings.llm_cost_tracking_enabled:
        # Pass-through path. We still want to call ``chat_with_usage``
        # so downstream code receives the same shape; we just skip
        # the meter writes and the budget guard.
        return await provider.chat_with_usage(messages, temperature=temperature)

    # We don't apply the per-user guards to ``__system__`` calls; the eval
    # suite and ingest pipelines are operator-controlled (match the dollar
    # guard carve-out below).
    if user_id != SYSTEM_USER_ID:
        # ---------- Pre-dispatch DB COUNT request quota (DR-11/16) ----------
        # The hard backstop, independent of dollars: a $0 BYOK call still
        # counts (it is still a row). Trips BEFORE the provider is invoked.
        tripped = await _check_request_quota(session, user_id=user_id, billing_mode=mode)
        if tripped is not None:
            dimension, used, limit = tripped
            await _persist_row(
                session,
                user_id=user_id,
                feature=feature,
                provider=getattr(provider, "name", "unknown"),
                model=getattr(provider, "_model", "unknown"),
                prompt_tokens=0,
                completion_tokens=0,
                cost_usd=0,
                latency_ms=0,
                status=STATUS_QUOTA_EXCEEDED,
                error_kind=None,
                billing_mode=mode,
            )
            log.warning(
                "llm_quota_exceeded",
                user_id=user_id,
                feature=feature,
                dimension=dimension,
                used=used,
                limit=limit,
                billing_mode=mode,
            )
            raise QuotaExceededError(
                "You've reached your request limit for now.",
                details={"dimension": dimension, "used": used, "limit": limit},
            )

        # ---------- Platform dollar guard (platform-billed calls only) ----------
        # Confirm-round fix: the guard itself is skipped for BYOK calls —
        # a user who exhausted the FREE platform budget and then configured
        # their own key must not stay blocked (BYOK is governed by the
        # request windows above; its spend goes to the user's provider).
        # The window sum is platform-rows-only for the same reason.
        current_spend = (
            await _user_cost_last_24h(session, user_id) if mode == BILLING_PLATFORM else None
        )
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
                billing_mode=mode,
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

    # ---------- Concurrency lease (best-effort, fail-open) ----------
    lease_client: object | None = None
    lease_key: str | None = None
    if user_id != SYSTEM_USER_ID:
        lease_client, lease_key = await _try_acquire_concurrency(user_id)

    # ---------- Provider call (timed) ----------
    started = time.perf_counter()
    byok_dispatch_exc: Exception | None = None
    try:
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
                billing_mode=mode,
            )
            log.warning(
                "llm_call_failed",
                user_id=user_id,
                feature=feature,
                error_kind=type(exc).__name__,
                latency_ms=latency_ms,
            )
            if mode == BILLING_BYOK and ctx is not None:
                # Adjudicated below, AFTER the finally releases this call's
                # concurrency lease — the consent fallback re-enters
                # call_logged, and the lease is fail-closed at the limit, so
                # holding it through the retry would wedge max_concurrent=1.
                byok_dispatch_exc = exc
            else:
                raise
    finally:
        await _release_concurrency_quiet(lease_client, lease_key)

    if byok_dispatch_exc is not None:
        # ADR-0027 §4 item 3 (Gate-B fix): an auth-class failure on a BYOK
        # dispatch marks the credential invalid and — with the user's
        # consent — retries THIS request on the platform model. Without
        # consent the handler raises the redacted ByokProviderError.
        # Non-auth (transient/rate-limit/timeout) failures re-raise as-is:
        # item 4 forbids fallback there so cost ownership stays predictable.
        from app.services import byok as byok_service  # cycle-safe local import

        fallback = await byok_service.handle_dispatch_auth_failure(session, ctx, byok_dispatch_exc)
        if fallback is None:
            raise byok_dispatch_exc
        fb_provider, fb_mode = fallback
        log.info(
            "byok_dispatch_platform_fallback",
            user_id=user_id,
            feature=feature,
        )
        # Re-enter with platform billing: the fallback call is platform
        # usage, so platform request quotas and the dollar guard apply to
        # it. Recursion depth is bounded at 1 — the platform mode can't
        # take this branch.
        return await call_logged(
            fb_provider,
            messages,
            user_id=user_id,
            feature=feature,
            session=session,
            temperature=temperature,
            billing_mode=fb_mode,
        )

    latency_ms = int((time.perf_counter() - started) * 1000)
    cost = compute_cost_usd(response.model, response.prompt_tokens, response.completion_tokens)
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
        billing_mode=mode,
    )
    return response


__all__ = ["call_logged"]
