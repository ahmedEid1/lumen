"""The builder's placeholder lesson bodies, and how to recognise them (L11).

A lesson drafter call that fails (rate limit, timeout, bad JSON) leaves the
placeholder in place so one bad lesson doesn't sink the whole build. These
markers let the build report the fallback honestly and let publish and share
refuse a course that still carries one.
"""

from __future__ import annotations

from typing import Any

PLACEHOLDER_TEXT = "Draft — replace before publishing."
PLACEHOLDER_QUIZ_PROMPT = "Draft question — replace before publishing"


def is_placeholder_lesson_data(data: dict[str, Any] | None) -> bool:
    """True when ``lesson.data`` is still the untouched builder placeholder."""
    if not isinstance(data, dict):
        return False
    if data.get("type") == "text":
        return (
            data.get("body_markdown") or ""
        ).strip() == PLACEHOLDER_TEXT and _blocks_are_placeholder(data.get("blocks"))
    if data.get("type") == "quiz":
        questions = data.get("questions") or []
        return bool(questions) and all(
            isinstance(q, dict) and q.get("prompt") == PLACEHOLDER_QUIZ_PROMPT for q in questions
        )
    return False


def _blocks_are_placeholder(blocks: Any) -> bool:
    # No blocks, or the single placeholder paragraph the builder writes.
    if not blocks:
        return True
    try:
        (para,) = blocks["content"]
        (text,) = para["content"]
        return text.get("text") == PLACEHOLDER_TEXT
    except (KeyError, TypeError, ValueError):
        return False
