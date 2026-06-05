"""S7 — token usage on streamed-turn ``llm_calls`` rows.

Carry-forward from ``docs/two-role-rebuild/STATUS.md``: streamed-turn rows used
to persist ``tokens=0`` because the provider's usage payload wasn't plumbed
through the stream events. S7 wires it: ``orchestrate_stream`` surfaces the
final chunk's ``prompt_tokens`` / ``completion_tokens`` on the
``turn_complete`` event, the worker captures them, and
``record_streamed_turn_row`` persists them.

These DB-backed tests pin two things at the persistence layer:

1. **Tokens are recorded** for observability/cost (real values land on the
   row).
2. **The streaming request quota stays COUNT-based.** The token columns must
   NOT feed the request windows — ``user_request_count`` is a row COUNT,
   independent of the token totals. This test is the tripwire the
   ``record_streamed_turn_row`` docstring points at: a future refactor that
   flips streaming quota to token-based has to change this test deliberately.

DB-backed → runs under ``make test.api``. ``llm_calls.user_id`` is a plain
``String(64)`` with no FK, so a synthetic id is enough; no real user row
needed.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.llm_call import BILLING_BYOK, BILLING_PLATFORM, STATUS_OK, LLMCall
from app.services.llm import NOOP_MODEL_NAME, ChatMessage, NoopProvider
from app.services.llm_call_log import (
    _QUOTA_WINDOW_24H_SECONDS,
    record_streamed_turn_row,
    user_request_count,
)
from app.services.llm_stream import stream_chat


@pytest.mark.asyncio
async def test_streamed_turn_persists_real_token_usage(db_session: AsyncSession) -> None:
    """The provider's reported tokens land on the persisted row (was 0)."""
    user_id = "u_tok_persist"
    await record_streamed_turn_row(
        db_session,
        user_id=user_id,
        provider="openai",
        model="llama-3.3-70b-versatile",
        cost_usd=0.0012,
        latency_ms=850,
        status=STATUS_OK,
        error_kind=None,
        billing_mode=BILLING_BYOK,
        prompt_tokens=512,
        completion_tokens=128,
    )
    await db_session.commit()

    row = (await db_session.execute(select(LLMCall).where(LLMCall.user_id == user_id))).scalar_one()
    assert row.feature == "tutor.stream"
    assert row.prompt_tokens == 512
    assert row.completion_tokens == 128
    assert row.billing_mode == BILLING_BYOK


@pytest.mark.asyncio
async def test_streamed_turn_tokens_default_zero_on_abort(db_session: AsyncSession) -> None:
    """Honest abort: a terminal row written without token kwargs (the
    failure/abort path in the worker, which never received a usage chunk)
    persists zeros — we claim only what the provider actually billed."""
    user_id = "u_tok_abort"
    await record_streamed_turn_row(
        db_session,
        user_id=user_id,
        provider="platform",
        model="claude-sonnet-4-6",
        cost_usd=0.0,
        latency_ms=0,
        status="error",
        error_kind="RuntimeError",
        billing_mode=BILLING_PLATFORM,
        # No prompt_tokens / completion_tokens → defaults.
    )
    await db_session.commit()

    row = (await db_session.execute(select(LLMCall).where(LLMCall.user_id == user_id))).scalar_one()
    assert row.prompt_tokens == 0
    assert row.completion_tokens == 0


@pytest.mark.asyncio
async def test_streamed_turn_tokens_are_observability_only(db_session: AsyncSession) -> None:
    """QUOTA INVARIANT (the tripwire): streaming request windows are
    COUNT-based, not token-based.

    Write three streamed rows carrying enormous token totals. The request
    counter must report 3 (one per row) regardless of the millions of tokens
    recorded — proving the token columns are observability/cost only and never
    feed the quota window. If a future refactor flips streaming quota to
    token-based, THIS assertion breaks and forces a deliberate decision.
    """
    user_id = "u_tok_quota_invariant"
    huge_prompt = 1_000_000
    huge_completion = 500_000
    for _ in range(3):
        await record_streamed_turn_row(
            db_session,
            user_id=user_id,
            provider="openai",
            model="llama-3.3-70b-versatile",
            cost_usd=0.0,
            latency_ms=10,
            status=STATUS_OK,
            error_kind=None,
            billing_mode=BILLING_BYOK,
            prompt_tokens=huge_prompt,
            completion_tokens=huge_completion,
        )
    await db_session.commit()

    # The quota window is a row COUNT — three rows → three, not 4.5M tokens.
    count = await user_request_count(db_session, user_id, _QUOTA_WINDOW_24H_SECONDS)
    assert count == 3, (
        "streaming request quota must be COUNT-based: a row COUNT independent "
        "of the token totals on those rows. If this changed, the streaming "
        "quota was (probably accidentally) flipped to token-based."
    )

    # Sanity: the huge token totals really were persisted (observability).
    total_prompt = (
        await db_session.execute(
            select(func.sum(LLMCall.prompt_tokens)).where(LLMCall.user_id == user_id)
        )
    ).scalar_one()
    assert total_prompt == huge_prompt * 3


@pytest.mark.asyncio
async def test_noop_provider_stream_usage_is_zero(db_session: AsyncSession) -> None:
    """Noop provider keeps working: its streamed terminal chunk reports zero
    tokens (no real provider, no real billing), so a row recorded from it
    carries zeros. The Noop ``chat_with_usage`` still synthesises estimated
    tokens for the non-streamed metered path, but the STREAM path
    (``_stream_chat_noop``) deliberately emits a zero-cost / zero-token usage
    payload — mirror that here so the streamed Noop row is honest."""
    # Drive the real noop stream and capture its terminal usage payload.
    s = get_settings()
    with patch.object(s, "llm_provider", "noop"):
        terminal = None
        async for chunk in stream_chat([ChatMessage(role="user", content="hi")]):
            if chunk.done:
                terminal = chunk
    assert terminal is not None
    assert terminal.usage.get("prompt_tokens", 0) == 0
    assert terminal.usage.get("completion_tokens", 0) == 0

    # Persist a streamed row from those (zero) counts — the Noop path records
    # honest zeros, not the chat_with_usage estimate.
    user_id = "u_tok_noop"
    await record_streamed_turn_row(
        db_session,
        user_id=user_id,
        provider="noop",
        model=NOOP_MODEL_NAME,
        cost_usd=0.0,
        latency_ms=5,
        status=STATUS_OK,
        error_kind=None,
        billing_mode=BILLING_PLATFORM,
        prompt_tokens=int(terminal.usage.get("prompt_tokens", 0) or 0),
        completion_tokens=int(terminal.usage.get("completion_tokens", 0) or 0),
    )
    await db_session.commit()

    row = (await db_session.execute(select(LLMCall).where(LLMCall.user_id == user_id))).scalar_one()
    assert row.prompt_tokens == 0
    assert row.completion_tokens == 0
    # Prove the Noop provider abstraction is intact (chat_with_usage still
    # synthesises non-zero estimates for the NON-stream metered path).
    resp = await NoopProvider().chat_with_usage([ChatMessage(role="user", content="hello there")])
    assert resp.prompt_tokens > 0
    assert resp.completion_tokens > 0
