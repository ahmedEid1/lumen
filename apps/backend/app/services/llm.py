"""LLM client abstraction backing the course-scoped tutor.

Rebuild Phase E1. The rest of the codebase talks to one
:class:`LLMProvider` Protocol so we can swap chat backends behind a
single env var. Today's concrete providers:

* :class:`AnthropicProvider` — :mod:`anthropic` SDK, defaults to
  ``claude-sonnet-4-6``. The Anthropic Messages API keeps the system
  prompt as a top-level ``system`` parameter rather than as a
  ``role: "system"`` message; we transform our normalised
  ``[ChatMessage]`` list into that shape inside
  :meth:`AnthropicProvider.chat`.
* :class:`OpenAIProvider` — :mod:`openai` SDK, defaults to
  ``gpt-4o-mini``. The Chat Completions endpoint *does* accept a
  ``system`` role, so the message list passes through unchanged.
* :class:`NoopProvider` — returns a deterministic canned response
  built from the system prompt's context block. It never imports a
  vendor SDK and is what the test suite exercises so every CI run
  that touches the tutor doesn't burn API tokens or depend on
  outbound network — same pattern E0 already uses for embeddings.

Selection is by :attr:`Settings.llm_provider` and resolved through
:func:`get_provider` per-call so tests can flip the provider via
``monkeypatch.setenv("LLM_PROVIDER", "noop")`` + ``get_settings.cache_clear()``
without restarting the process — mirroring the convention CLAUDE.md
documents for ``SEARCH_BACKEND`` and ``EMBEDDING_PROVIDER``.

A note on async vs sync. The vendor SDKs ship both, but the tutor
service is called from inside FastAPI's request loop, and we don't
want the chat round-trip to block the event loop. We expose
:meth:`chat` as ``async`` on the Protocol and run the underlying
synchronous client calls via :func:`asyncio.to_thread` — this keeps
the dependency surface small (no separate async client to keep in
lockstep) and the latency hit of the off-loop hop is negligible
next to the multi-second LLM call itself.
"""

from __future__ import annotations

import asyncio
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


# Default model identifiers. The Anthropic default ships the Sonnet
# 4.6 release alias (``claude-sonnet-4-6``) — operators who want to
# pin to a dated build (e.g. ``claude-sonnet-4-6-20260301``) can
# override via ``LLM_MODEL``.
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
# Prefix on every NoopProvider reply. Tests assert on this token so
# they can prove the tutor pipeline (and the persisted assistant
# message) actually round-tripped through the provider rather than
# short-circuiting somewhere in the service layer.
NOOP_RESPONSE_PREFIX = "Based on the course content, "
# Sentinel response when retrieval (or the noop's parsing of the
# system prompt) finds no in-course context. The tutor service's
# refusal path emits a translatable message at the API edge; the
# noop's role here is to expose a deterministic "no context"
# signal that downstream tests can assert against.
NOOP_REFUSAL = (
    "I don't have material in this course that covers that yet. "
    "Try a different question."
)


class ChatMessage(BaseModel):
    """One turn in a chat conversation, provider-agnostic.

    ``role`` is one of ``"system" | "user" | "assistant"``. The
    Anthropic provider hoists a leading ``system`` message into the
    top-level ``system`` parameter (the Messages API rejects a
    ``role: "system"`` entry inside the messages list); the OpenAI
    provider passes it through untouched.
    """

    role: Literal["system", "user", "assistant"]
    content: str


@runtime_checkable
class LLMProvider(Protocol):
    """Provider-agnostic chat interface.

    Implementations return a single string — the assistant's
    completed reply — for the given conversation. Streaming is an
    explicit non-goal at this layer: the tutor surface persists
    every response as a row in the ``tutor_messages`` table, so
    streaming would force us to either buffer-then-write (no UX
    win) or write incremental rows (a footgun the v1 product
    doesn't need). We can layer a stream variant on top later
    without breaking existing callers.
    """

    name: str

    async def chat(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.2,
    ) -> str: ...


# ---------- Anthropic provider ----------


class AnthropicProvider:
    """Claude via the official :mod:`anthropic` SDK.

    The constructor is lazy — the SDK import is deferred until
    :meth:`chat` is first called, so a worker boot that never asks
    the tutor anything doesn't pay the import cost. Same pattern
    :class:`~app.services.embeddings.LocalEmbeddingProvider` uses
    for ``sentence_transformers``.
    """

    name: str = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_ANTHROPIC_MODEL,
        api_base: str | None = None,
        max_tokens: int = 1024,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._api_base = api_base
        self._max_tokens = max_tokens
        self._client: object | None = None

    def _get_client(self) -> object:
        if self._client is None:
            from anthropic import Anthropic  # type: ignore[import-not-found]

            kwargs: dict[str, object] = {"api_key": self._api_key}
            if self._api_base:
                kwargs["base_url"] = self._api_base
            self._client = Anthropic(**kwargs)
        return self._client

    async def chat(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.2,
    ) -> str:
        if not self._api_key:
            raise RuntimeError(
                "Anthropic provider selected but ANTHROPIC_API_KEY is unset"
            )

        # The Messages API takes ``system`` as a top-level parameter;
        # only ``user`` / ``assistant`` turns are allowed inside
        # ``messages``. We concatenate every leading system turn into
        # one string so the system prompt stays deterministic across
        # providers even if a caller (or future tool-use prompt) ever
        # pushes multiple system messages.
        system_parts = [m.content for m in messages if m.role == "system"]
        system = "\n\n".join(system_parts) if system_parts else ""
        turns = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role != "system"
        ]

        client = self._get_client()
        max_tokens = self._max_tokens
        model = self._model

        def _call() -> str:
            kwargs: dict[str, object] = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": turns,
            }
            if system:
                kwargs["system"] = system
            response = client.messages.create(**kwargs)  # type: ignore[attr-defined]
            # The response carries a list of content blocks; in the
            # non-tool / non-thinking path it's exactly one ``text``
            # block. Be defensive: join every text block we see and
            # ignore anything else (e.g. ``tool_use`` blocks a future
            # tool-augmented prompt could surface).
            parts: list[str] = []
            for block in response.content:
                text = getattr(block, "text", None)
                if text:
                    parts.append(text)
            return "".join(parts)

        return await asyncio.to_thread(_call)


# ---------- OpenAI provider ----------


class OpenAIProvider:
    """OpenAI Chat Completions, default ``gpt-4o-mini``.

    Mirrors :class:`AnthropicProvider` in spirit: deferred SDK import,
    synchronous client run on a worker thread so the FastAPI event
    loop stays free. The Chat Completions endpoint takes the system
    role inline, so we pass the message list through unchanged.
    """

    name: str = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_OPENAI_MODEL,
        api_base: str | None = None,
        max_tokens: int = 1024,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._api_base = api_base
        self._max_tokens = max_tokens
        self._client: object | None = None

    def _get_client(self) -> object:
        if self._client is None:
            from openai import OpenAI  # type: ignore[import-not-found]

            kwargs: dict[str, object] = {"api_key": self._api_key}
            if self._api_base:
                kwargs["base_url"] = self._api_base
            self._client = OpenAI(**kwargs)
        return self._client

    async def chat(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.2,
    ) -> str:
        if not self._api_key:
            raise RuntimeError(
                "OpenAI provider selected but OPENAI_API_KEY is unset"
            )

        client = self._get_client()
        payload = [{"role": m.role, "content": m.content} for m in messages]
        model = self._model
        max_tokens = self._max_tokens

        def _call() -> str:
            completion = client.chat.completions.create(  # type: ignore[attr-defined]
                model=model,
                messages=payload,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            choice = completion.choices[0]
            content = getattr(choice.message, "content", "") or ""
            return content

        return await asyncio.to_thread(_call)


# ---------- Noop provider (tests) ----------


class NoopProvider:
    """Deterministic, network-free stub for tests.

    Returns a canned reply that:

    1. Always begins with :data:`NOOP_RESPONSE_PREFIX` so tests can
       assert that the tutor pipeline (and the persisted assistant
       message) round-tripped through the provider rather than
       short-circuiting somewhere.
    2. Echoes the user's question so a test that asks "what is X?"
       can reasonably assert "the answer mentions X".
    3. Emits one ``[L:lesson_id]`` citation token for every lesson
       id found in the system prompt's context block. The tutor
       service builds the context with ``Lesson L<lesson_id>:``
       headers, so the noop provider parses those headers back out
       to produce realistic citation output. Tests exercise the
       citation parser without needing a live LLM.

    If no lesson ids are advertised in the system prompt (i.e.
    retrieval returned nothing), emits :data:`NOOP_REFUSAL` so the
    tutor service's refusal path is exercisable without
    monkeypatching the retrieval helper.
    """

    name: str = "noop"

    async def chat(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.2,
    ) -> str:
        del temperature  # noop ignores temperature
        system = next((m.content for m in messages if m.role == "system"), "")
        user = next(
            (m.content for m in reversed(messages) if m.role == "user"),
            "",
        )

        # Harvest lesson ids the system prompt's context section
        # advertises. The tutor service emits one block per chunk
        # prefixed with ``Lesson L<id>:``; we pluck those out so
        # the canned response can cite them.
        lesson_ids: list[str] = []
        for raw_line in system.splitlines():
            line = raw_line.strip()
            if line.startswith("Lesson L"):
                head = line.split(":", 1)[0]  # "Lesson L<id>"
                token = head.removeprefix("Lesson ").strip()  # "L<id>"
                if token.startswith("L") and len(token) > 1:
                    lesson_id = token[1:]
                    if lesson_id and lesson_id not in lesson_ids:
                        lesson_ids.append(lesson_id)

        if not lesson_ids:
            return NOOP_REFUSAL

        citations = " ".join(f"[L:{lid}]" for lid in lesson_ids)
        snippet = (user[:120] + "…") if len(user) > 120 else user
        return f"{NOOP_RESPONSE_PREFIX}{snippet} {citations}".strip()


# ---------- Selection ----------


def get_provider() -> LLMProvider:
    """Return the configured tutor LLM provider.

    Resolved each call so a test that swaps ``LLM_PROVIDER`` via
    ``monkeypatch.setenv`` + ``get_settings.cache_clear()`` picks up
    the new provider on the next request without restarting the
    process — the pattern documented for the embedding selector and
    the search backend.
    """
    s = get_settings()
    kind = s.llm_provider
    if kind == "noop":
        return NoopProvider()
    if kind == "openai":
        api_key = s.openai_api_key.get_secret_value() if s.openai_api_key else ""
        return OpenAIProvider(
            api_key=api_key,
            model=s.llm_model or DEFAULT_OPENAI_MODEL,
            api_base=s.openai_api_base,
            max_tokens=s.llm_max_tokens,
        )
    # default — "anthropic"
    api_key = s.anthropic_api_key.get_secret_value() if s.anthropic_api_key else ""
    return AnthropicProvider(
        api_key=api_key,
        model=s.llm_model or DEFAULT_ANTHROPIC_MODEL,
        api_base=s.anthropic_api_base,
        max_tokens=s.llm_max_tokens,
    )


__all__ = [
    "AnthropicProvider",
    "ChatMessage",
    "DEFAULT_ANTHROPIC_MODEL",
    "DEFAULT_OPENAI_MODEL",
    "LLMProvider",
    "NOOP_REFUSAL",
    "NOOP_RESPONSE_PREFIX",
    "NoopProvider",
    "OpenAIProvider",
    "get_provider",
]
