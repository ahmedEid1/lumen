"""Embedding provider interface + concrete implementations.

Rebuild Phase E0. The ingest + retrieval pipeline talks to one
abstract ``EmbeddingProvider`` so the rest of the codebase doesn't
care whether we're calling a local sentence-transformer, OpenAI's
API, or a deterministic test stub. Concrete providers:

* :class:`LocalEmbeddingProvider` — wraps
  ``sentence-transformers/all-MiniLM-L6-v2`` (384-dim). The
  ``sentence_transformers`` import is deferred until first
  ``embed()`` call so a worker boot that never embeds anything stays
  light (the package pulls in ``torch``, which is ~200MB and slow to
  import).
* :class:`OpenAIEmbeddingProvider` — calls
  ``text-embedding-3-small`` with ``dimensions=384`` so the output
  matches our column shape. Network failures bubble up; the Celery
  task that calls this has its own retry policy.
* :class:`NoopEmbeddingProvider` — deterministic zero-vector
  generator (with a fixed-seed perturbation so different texts get
  different zero-vectors, useful for cosine-distance ordering tests).

Selection is by :attr:`Settings.embedding_provider` and resolved
lazily by :func:`get_provider` — re-reading settings means tests that
swap providers via ``monkeypatch.setenv`` + ``get_settings.cache_clear()``
pick up the new provider on the next call without process restart.
"""

from __future__ import annotations

import hashlib
from typing import Protocol, runtime_checkable

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.lesson_chunk import EMBEDDING_DIM

log = get_logger(__name__)


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Provider-agnostic embedding interface.

    Implementations must return one ``list[float]`` of length
    :data:`~app.models.lesson_chunk.EMBEDDING_DIM` per input string,
    in the same order. ``embed`` may be called with an empty list and
    must return ``[]`` in that case (no network calls).
    """

    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


# ---------- Local sentence-transformers provider ----------


class LocalEmbeddingProvider:
    """Embeds via a local ``sentence_transformers`` model.

    The model object is lazily constructed the first time ``embed``
    runs — ``sentence_transformers`` is heavy to import (torch,
    huggingface-hub, tokenizers) and most worker invocations don't
    actually embed anything (email send, certificate render, …). By
    deferring, the worker container's cold-start stays fast and we
    only pay the import cost when ingest actually fires.
    """

    dim: int = EMBEDDING_DIM

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: object | None = None

    def _load(self) -> object:
        if self._model is None:
            # Deferred import — see class docstring.
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

            log.info("embedding_model_loading", model=self._model_name)
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        # ``encode`` returns numpy arrays; ``.tolist()`` collapses to
        # plain Python lists so the SQLAlchemy ``Vector`` adapter
        # doesn't have to think about numpy dtype.
        vectors = model.encode(  # type: ignore[attr-defined]
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return [list(map(float, v)) for v in vectors.tolist()]


# ---------- OpenAI provider ----------


class OpenAIEmbeddingProvider:
    """Embeds via OpenAI's ``text-embedding-3-small`` model.

    We pass ``dimensions=384`` so the truncated output matches the
    ``vector(384)`` column shape used by both local and noop
    providers. That lets operators flip
    ``EMBEDDING_PROVIDER=local|openai`` without a re-index — the
    stored vectors aren't *identical*, but they live in the same
    metric space-of-the-column and existing chunks can be searched
    until a publish-triggered re-ingest rewrites them.
    """

    dim: int = EMBEDDING_DIM

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        api_base: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._api_base = api_base.rstrip("/")
        self._timeout = timeout_seconds

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self._api_key:
            raise RuntimeError(
                "OpenAI embedding provider selected but OPENAI_API_KEY is unset"
            )
        # Synchronous httpx — this provider runs inside Celery worker
        # contexts (and the retrieval helper's sync bridge), not the
        # FastAPI request loop, so blocking I/O here is fine.
        with httpx.Client(timeout=self._timeout) as client:
            res = client.post(
                f"{self._api_base}/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "input": texts,
                    "dimensions": EMBEDDING_DIM,
                },
            )
            res.raise_for_status()
            data = res.json()
        # OpenAI's response is ``{"data": [{"embedding": [...], "index": N}, ...]}``
        # in insertion order. Re-sort by ``index`` defensively so the
        # caller's ``texts[i] ↔ vectors[i]`` invariant holds.
        rows = sorted(data["data"], key=lambda row: row["index"])
        return [list(map(float, row["embedding"])) for row in rows]


# ---------- Noop provider (tests) ----------


class NoopEmbeddingProvider:
    """Deterministic, network-free embedding stub for tests.

    Returns a 384-dim vector that's mostly zeros but seeded from a
    SHA-256 of the input string so different texts get *different*
    zero-vectors (otherwise every cosine distance would be undefined
    and retrieval-ordering tests couldn't assert anything).

    Determinism rules:

    * Same text → same vector across processes.
    * Different text → different vector.
    * All vectors are L2-normalised so cosine distance is well-defined
      (no NaN from a literal-zero vector).
    """

    dim: int = EMBEDDING_DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        for text in texts:
            # Hash → 32 bytes → take first 16 bytes, expand to 384
            # floats by repetition. The repetition is fine for a stub:
            # we only need each input to map to a *distinct* unit
            # vector, not to a high-quality embedding.
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            seed = list(digest[:16])
            vec = [(seed[i % 16] / 255.0) for i in range(EMBEDDING_DIM)]
            # L2-normalise so cosine distance never divides by zero.
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            out.append([v / norm for v in vec])
        return out


# ---------- Selection ----------


def get_provider() -> EmbeddingProvider:
    """Return the configured provider.

    Resolved each call so tests can swap providers mid-run via
    ``monkeypatch.setenv("EMBEDDING_PROVIDER", ...)`` +
    ``get_settings.cache_clear()`` — the env-flip-then-cache-clear
    pattern Lumen uses for any Settings field that has alternate
    implementations behind it.
    """
    s = get_settings()
    kind = s.embedding_provider
    if kind == "noop":
        return NoopEmbeddingProvider()
    if kind == "openai":
        # Prefer embedding-specific overrides if set — lets the embedding
        # call hit a different OpenAI-compatible endpoint (e.g. Cloudflare
        # Workers AI) than the LLM (e.g. Groq). Falls back to the shared
        # ``openai_api_*`` so existing single-provider setups don't change.
        emb_key_secret = s.embedding_openai_api_key or s.openai_api_key
        api_key = emb_key_secret.get_secret_value() if emb_key_secret else ""
        api_base = s.embedding_openai_api_base or s.openai_api_base
        return OpenAIEmbeddingProvider(
            api_key=api_key,
            model=s.embedding_model_openai,
            api_base=api_base,
        )
    # default — "local"
    return LocalEmbeddingProvider(s.embedding_model_local)
