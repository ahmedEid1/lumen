"""LLM sanitizer (L21-Sec)."""

from __future__ import annotations

import pytest

from app.core.llm_sanitize import (
    LLAMA_3_SPECIAL_TOKENS,
    count_special_tokens,
    sanitise_tool_output,
    sanitise_with_nonce_wrapper,
)


@pytest.mark.parametrize("token", LLAMA_3_SPECIAL_TOKENS)
def test_strips_each_known_special_token(token: str) -> None:
    text = f"benign text {token} more text"
    out = sanitise_tool_output(text)
    assert token not in out


def test_strips_unknown_special_token_shape() -> None:
    """The regex catches any `<|...|>` shape — defense against tokens
    we haven't seen yet (Llama 4? Other families?). The point is the
    *shape* is reserved, not just the named list."""
    text = "look at this <|future_unknown_token|> here"
    out = sanitise_tool_output(text)
    assert "<|" not in out


def test_leaves_normal_text_alone() -> None:
    text = "Hello, world. This text has < and | and > but not all in a row."
    assert sanitise_tool_output(text) == text


def test_does_not_strip_legit_pipe_or_angle() -> None:
    """Important — we don't want to break Markdown tables, ASCII art,
    or shell command examples."""
    text = "| Column | Header |\n|---|---|\n| Pipe usage | safe |"
    assert sanitise_tool_output(text) == text


def test_handles_empty_string() -> None:
    assert sanitise_tool_output("") == ""


def test_handles_only_special_tokens() -> None:
    text = "<|begin_of_text|><|end_of_text|>"
    assert sanitise_tool_output(text) == ""


def test_count_special_tokens() -> None:
    text = "<|begin_of_text|>hello<|end_of_text|> normal text <|eot_id|>"
    assert count_special_tokens(text) == 3


def test_count_returns_zero_on_clean_text() -> None:
    assert count_special_tokens("nothing to see here") == 0


def test_nonce_wrapper_envelopes_text() -> None:
    nonce = "abc12345"  # 8 chars exactly — the boundary
    out = sanitise_with_nonce_wrapper("payload", source="web", nonce=nonce)
    assert out.startswith(f'<lumen-data source="web" nonce="{nonce}">')
    assert out.endswith(f'</lumen-data nonce="{nonce}">')
    assert "payload" in out


def test_nonce_wrapper_also_sanitises_inner() -> None:
    """A tool output that contains a special token should be cleaned
    *and* wrapped — defense in depth."""
    out = sanitise_with_nonce_wrapper("before<|eot_id|>after", source="tool", nonce="abc12345")
    assert "<|eot_id|>" not in out
    assert "before" in out
    assert "after" in out


def test_nonce_wrapper_rejects_short_nonce() -> None:
    with pytest.raises(ValueError, match="nonce too short"):
        sanitise_with_nonce_wrapper("payload", source="web", nonce="abc")
