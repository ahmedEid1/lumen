"""Sentry/Glitchtip before_send scrubber (L21-Sec)."""

from __future__ import annotations

from app.core.sentry_scrubber import REDACTED, SCRUB_LOCALS, before_send


def _make_event(**overrides):
    """Skeleton Sentry event with one exception frame."""
    base = {
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": "boom",
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "tutor.py",
                                "function": "synthesise",
                                "lineno": 42,
                                "vars": {
                                    "prompt": "SECRET system prompt",
                                    "user_message": "what does X mean",
                                    "innocuous": "keep me",
                                },
                            }
                        ]
                    },
                }
            ]
        }
    }
    base.update(overrides)
    return base


def test_scrubs_tutor_locals_in_stack_frame() -> None:
    event = _make_event()
    cleaned = before_send(event)
    frame_vars = cleaned["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]
    assert frame_vars["prompt"] == REDACTED
    assert frame_vars["user_message"] == REDACTED
    # Non-tutor locals stay — debuggability requirement.
    assert frame_vars["innocuous"] == "keep me"


def test_scrubs_tutor_request_body() -> None:
    event = _make_event()
    event["request"] = {
        "url": "https://api.lumen.test/api/v1/tutor/conversations/abc/messages",
        "data": {"content": "private question"},
    }
    cleaned = before_send(event)
    assert cleaned["request"]["data"] == REDACTED


def test_leaves_non_tutor_request_body_alone() -> None:
    event = _make_event()
    event["request"] = {
        "url": "https://api.lumen.test/api/v1/courses",
        "data": {"query": "search term"},
    }
    cleaned = before_send(event)
    assert cleaned["request"]["data"] == {"query": "search term"}


def test_scrubs_tutor_breadcrumbs_only() -> None:
    event = _make_event()
    event["breadcrumbs"] = {
        "values": [
            {"category": "tutor", "message": "system prompt: ..."},
            {"category": "db", "message": "SELECT 1"},
        ]
    }
    cleaned = before_send(event)
    bcs = cleaned["breadcrumbs"]["values"]
    assert bcs[0]["message"] == REDACTED
    assert bcs[1]["message"] == "SELECT 1"  # untouched


def test_handles_missing_fields_gracefully() -> None:
    """The hook should never raise on a thin event — it's in the
    publish-path hot loop, an exception here would swallow the
    original error."""
    minimal = {"exception": {"values": []}}
    cleaned = before_send(minimal)
    assert cleaned == minimal


def test_scrub_locals_list_is_explicit() -> None:
    """Lock the list — adding a new field that needs scrubbing should
    be a deliberate edit, not an accident."""
    must_include = {"prompt", "system_prompt", "user_message", "messages", "tool_output"}
    assert must_include <= SCRUB_LOCALS


def test_hint_kwarg_is_optional() -> None:
    """The SDK passes hint as keyword; we accept None for direct
    unit-test calls."""
    event = _make_event()
    cleaned = before_send(event, None)
    assert cleaned is not None
