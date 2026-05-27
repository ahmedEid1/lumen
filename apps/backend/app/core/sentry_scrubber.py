"""Sentry / Glitchtip before_send hook (L21-Sec).

The threat (plan-v7 §V7-sentry-scrubber):

Sentry / Glitchtip captures the entire call stack including local
variables when an unhandled exception bubbles. A tutor turn that
crashes deep in the synthesiser puts the *prompt content* — system
prompt, user question, retrieved chunks, even partial generations —
into Sentry's persistent storage. That's:

1. A PII leak (the question might contain an email, a name, a code
   sample with internal API keys).
2. A system-prompt-disclosure vector (anyone with Sentry read
   access can lift the system prompt straight out of an event).
3. A cost-tracking leak (token counts, model names, latencies all
   end up in the event metadata).

Mitigation: install a ``before_send`` hook that runs over every
event before it ships and zeros out anything in the "tutor" namespace.

What gets scrubbed:

- Local variables with the names ``prompt``, ``system_prompt``,
  ``user_message``, ``messages``, ``response_text``, ``tool_output``.
- Breadcrumb messages tagged with ``category="tutor"``.
- Request bodies whose URL matches ``/tutor`` or ``/api/v1/tutor/*``.

What stays:

- Exception class + filename + line number (the debug signal).
- Non-tutor breadcrumbs (DB queries, Celery tasks, HTTP requests).
- The stack trace structure (frames + function names, just not
  their captured locals).

The hook is pure-Python, no I/O, and idempotent. The Sentry SDK
calls ``before_send`` synchronously inside the event-publish path,
so it must stay cheap.
"""

from __future__ import annotations

from typing import Any

# Local-variable names that should be redacted across every captured
# stack frame. Keep this list narrow — broad redaction makes the
# Sentry event unhelpful for debugging.
SCRUB_LOCALS: frozenset[str] = frozenset(
    {
        "prompt",
        "system_prompt",
        "user_message",
        "user_prompt",
        "messages",
        "response_text",
        "tool_output",
        "tool_result",
        "completion",
        "answer",
        "agent_response",
        "retrieved_chunks",
        "lesson_body",
    }
)

# URL prefixes whose request body should not be captured.
SCRUB_URL_PREFIXES: tuple[str, ...] = (
    "/api/v1/tutor",
    "/tutor",
)

REDACTED = "<scrubbed by lumen.sentry_scrubber>"


def _scrub_frame_locals(frame: dict[str, Any]) -> None:
    """Zero out any in-scope local with a tutor-namespace name."""
    vars_ = frame.get("vars")
    if not isinstance(vars_, dict):
        return
    for name in list(vars_.keys()):
        if name in SCRUB_LOCALS:
            vars_[name] = REDACTED


def _scrub_request(event: dict[str, Any]) -> None:
    """Drop the request body if the URL targets a tutor endpoint.

    Sentry's HTTP integration captures the JSON body by default; for
    the tutor endpoints we don't want that body persisted at all.
    """
    request = event.get("request")
    if not isinstance(request, dict):
        return
    url = request.get("url", "")
    if not isinstance(url, str):
        return
    if any(prefix in url for prefix in SCRUB_URL_PREFIXES):
        request["data"] = REDACTED


def _scrub_breadcrumbs(event: dict[str, Any]) -> None:
    """Scrub the message body of any breadcrumb tagged tutor."""
    bc_root = event.get("breadcrumbs")
    if not isinstance(bc_root, dict):
        return
    bcs = bc_root.get("values")
    if not isinstance(bcs, list):
        return
    for bc in bcs:
        if not isinstance(bc, dict):
            continue
        if bc.get("category") == "tutor":
            bc["message"] = REDACTED
            bc["data"] = REDACTED


def before_send(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Sentry SDK ``before_send`` callable.

    The SDK expects ``(event, hint) -> event | None``. Returning ``None``
    drops the event entirely; we never do that (debuggability), we
    just zero out sensitive fields.

    Hint is unused but kept in the signature so the SDK can pass it.
    """
    del hint  # not consulted today

    # Scrub captured locals across every stack frame in every
    # exception in the event.
    exception_root = event.get("exception")
    if isinstance(exception_root, dict):
        for exc in exception_root.get("values", []) or []:
            if not isinstance(exc, dict):
                continue
            stacktrace = exc.get("stacktrace")
            if not isinstance(stacktrace, dict):
                continue
            for frame in stacktrace.get("frames", []) or []:
                if isinstance(frame, dict):
                    _scrub_frame_locals(frame)

    _scrub_request(event)
    _scrub_breadcrumbs(event)

    return event
