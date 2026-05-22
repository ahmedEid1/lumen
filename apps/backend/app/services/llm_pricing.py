"""Per-model LLM token pricing — for the cost meter.

Lumen v2 Phase H1. Single source of truth for "how much did that
call cost us?" The map is a small literal dict keyed on model
identifier; the values are ``(input_per_million, output_per_million)``
USD pairs sourced from each vendor's public pricing page as of the
v2 spec date (2026-05-22).

The pairs are tuples of plain ``float`` for readability; the
``compute_cost_usd`` helper wraps them in ``Decimal`` before the
multiply so the persisted ``cost_usd`` column (``Numeric(10, 6)``)
never picks up a float-rounding gremlin.

Unknown model handling. The Groq + OpenAI-compat endpoint accepts
any model name we hand it, and a typo (or a future model we
haven't priced yet) would otherwise be free in the meter. We
explicitly return ``Decimal("0")`` and log a warning so the operator
notices in structlog while the request still succeeds — refusing to
serve a request because we couldn't price it would be the wrong
trade-off.

Updating the table. When a vendor changes prices or we add a new
model, append a row and bump the corresponding test in
``tests/test_llm_pricing.py``. Pricing is a config concern, not a
behaviour concern — no other module should hard-code these numbers.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.logging import get_logger

log = get_logger(__name__)


# Prices in **USD per 1,000,000 tokens** (input, output). Sourced
# from each vendor's pricing page; keep the comments terse and
# include the date alongside any future update so we can track
# drift.
#
# As of 2026-05-22:
#   - Groq (free tier still on the cards, but priced once paid):
#       llama-3.3-70b-versatile: $0.59 in / $0.79 out
#   - Anthropic:
#       claude-sonnet-4-6:          $3.00 in / $15.00 out
#       claude-haiku-4-5-20251001:  $1.00 in /  $5.00 out
#   - OpenAI:
#       gpt-4o-mini:                $0.15 in /  $0.60 out
#       gpt-4o:                     $2.50 in / $10.00 out
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}


# Per-million → per-token divisor as a ``Decimal`` so the multiplication
# stays in Decimal-land end-to-end (no float coercion mid-math).
_PER_MILLION = Decimal("1000000")


def compute_cost_usd(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> Decimal:
    """Return the USD cost of a call as a quantized ``Decimal``.

    Result is quantized to 6 fractional digits to match the
    ``cost_usd`` column's ``Numeric(10, 6)`` precision — a value
    that's persisted unchanged round-trips through SQLAlchemy
    without re-quantization noise.

    Unknown models return ``Decimal("0.000000")`` and log a warning.
    Callers may persist the row with ``cost_usd=0`` and the admin
    surface will show the unpriced traffic next to a sum that's
    obviously missing entries — better than dropping the row.
    """
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        log.warning(
            "llm_pricing_unknown_model",
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        return Decimal("0.000000")

    in_per_m, out_per_m = pricing
    cost = (
        Decimal(str(in_per_m)) * Decimal(int(prompt_tokens))
        + Decimal(str(out_per_m)) * Decimal(int(completion_tokens))
    ) / _PER_MILLION
    return cost.quantize(Decimal("0.000001"))


__all__ = [
    "MODEL_PRICING",
    "compute_cost_usd",
]
