"""Pricing math + unknown-model fallback for the cost meter."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.llm_pricing import MODEL_PRICING, compute_cost_usd

# ---------- Known models ----------


def test_groq_llama_pricing_matches_published_rates() -> None:
    """1M input tokens + 1M output tokens on llama-3.3-70b → $1.38.

    0.59 (in) + 0.79 (out) per million → 1.38 USD exactly.
    """
    cost = compute_cost_usd("llama-3.3-70b-versatile", 1_000_000, 1_000_000)
    assert cost == Decimal("1.380000")


def test_anthropic_sonnet_pricing_matches_published_rates() -> None:
    """Sonnet 4.6 — $3 in, $15 out per million."""
    cost = compute_cost_usd("claude-sonnet-4-6", 1_000_000, 1_000_000)
    assert cost == Decimal("18.000000")


def test_anthropic_haiku_pricing_matches_published_rates() -> None:
    cost = compute_cost_usd("claude-haiku-4-5-20251001", 1_000_000, 1_000_000)
    assert cost == Decimal("6.000000")


def test_openai_gpt4o_mini_pricing_matches_published_rates() -> None:
    cost = compute_cost_usd("gpt-4o-mini", 1_000_000, 1_000_000)
    assert cost == Decimal("0.750000")


def test_openai_gpt4o_pricing_matches_published_rates() -> None:
    cost = compute_cost_usd("gpt-4o", 1_000_000, 1_000_000)
    assert cost == Decimal("12.500000")


# ---------- Token math at typical request sizes ----------


def test_small_request_lands_in_sub_cent_territory() -> None:
    """A 500-in / 300-out Groq call should be well under a cent.

    0.59 * 500 / 1e6 + 0.79 * 300 / 1e6 = 0.000295 + 0.000237 = 0.000532.
    """
    cost = compute_cost_usd("llama-3.3-70b-versatile", 500, 300)
    assert cost == Decimal("0.000532")


def test_zero_tokens_zero_cost() -> None:
    """A throttled / errored call recorded with 0 tokens costs $0."""
    cost = compute_cost_usd("llama-3.3-70b-versatile", 0, 0)
    assert cost == Decimal("0")


# ---------- Unknown model fallback ----------


def test_unknown_model_returns_zero_and_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unpriced model must not blow up — log a warning and return $0.

    The meter still wants to write a row; we just don't know what to
    multiply by, so the safe default is zero. The structlog warning
    is the operator's signal to add the model to ``MODEL_PRICING``.

    We assert on the warning via a monkeypatch over the module's
    bound logger rather than via :func:`caplog` because the project's
    structlog config uses :class:`structlog.PrintLoggerFactory` —
    output goes straight to stdout and never enters the stdlib
    logging tree that pytest's caplog hooks into. Capturing the call
    on the module attribute is more direct and survives any future
    log-renderer swap.
    """
    from app.services import llm_pricing as pricing_mod

    events: list[tuple[str, dict[str, object]]] = []

    class _Recorder:
        def warning(self, event: str, **kwargs: object) -> None:
            events.append((event, kwargs))

    monkeypatch.setattr(pricing_mod, "log", _Recorder())
    cost = compute_cost_usd("some-future-model", 1000, 1000)
    assert cost == Decimal("0.000000")
    assert any(name == "llm_pricing_unknown_model" for name, _ in events)


def test_pricing_table_includes_all_required_models() -> None:
    """Lock the floor — these models must always be priced.

    A future PR can add more, but removing one breaks the cost
    attribution for historical calls and should be a deliberate
    decision (and a separate test failure flagging it).
    """
    required = {
        "llama-3.3-70b-versatile",
        "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001",
        "gpt-4o-mini",
        "gpt-4o",
    }
    assert required.issubset(MODEL_PRICING.keys())
