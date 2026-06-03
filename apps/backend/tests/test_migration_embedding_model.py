"""S2/RAG.41-43 — lesson_chunks embedding-model migrations (ADR-0029 §D6 / DR-14).

Structural (pure-unit): the three migrations' identity + chain + phase
annotations; 0041 backfill is operator-confirmed (env, not assumed) + skips
when unconfirmed; 0042 builds ix_lessons_module_id_live CONCURRENTLY; 0043 is
Phase D and guards on remaining NULL rows before tightening. Plus the model +
provider shape (embedding_model/embedding_dim nullable; providers expose
model_id).
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

_MIG_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load(stem: str):
    path = next(_MIG_DIR.glob(f"*{stem}*.py"))
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_chain_links_0033_to_0044():
    m41, m42, m43, m44 = _load("0041"), _load("0042"), _load("0043"), _load("0044")
    assert m41.revision == "0041" and m41.down_revision in {"0033"}
    assert m42.revision == "0042" and m42.down_revision == "0041"
    assert m43.revision == "0043" and m43.down_revision == "0042"
    assert m44.revision == "0044" and m44.down_revision in {"0043", "0033"}


def test_phase_annotations():
    assert _load("0041").PHASE == "A"
    assert _load("0042").PHASE == "A"
    assert _load("0043").PHASE == "D"  # NOT-NULL tighten is release-gated


def test_0041_backfill_is_operator_confirmed_and_skippable():
    src = inspect.getsource(_load("0041").upgrade)
    assert "EMBEDDING_BACKFILL_MODEL" in src
    # If unconfirmed, return early (column stays nullable) — never assume.
    assert "return" in src
    assert "nullable=True" in src


def test_0042_concurrent_lessons_live_index():
    m = _load("0042")
    mod_src = inspect.getsource(m)
    up_src = inspect.getsource(m.upgrade)
    assert "ix_lessons_module_id_live" in mod_src
    assert "CONCURRENTLY" in up_src
    assert "WHERE deleted_at IS NULL" in up_src
    assert "autocommit_block" in up_src


def test_0043_guards_on_null_rows_before_tightening():
    src = inspect.getsource(_load("0043").upgrade)
    assert "embedding_model IS NULL" in src
    assert "RuntimeError" in src
    assert "nullable=False" in src


def test_lesson_chunk_model_has_nullable_provenance_columns():
    from app.models.lesson_chunk import LessonChunk

    cols = LessonChunk.__mapper__.columns
    assert "embedding_model" in cols
    assert "embedding_dim" in cols
    # Nullable at the ORM level (mass-invalidation avoidance, R-C3); 0043
    # tightens the DB column once the fleet stamps them.
    assert cols["embedding_model"].nullable is True
    assert cols["embedding_dim"].nullable is True


def test_providers_expose_model_id():
    from app.services.embeddings import (
        LocalEmbeddingProvider,
        NoopEmbeddingProvider,
        OpenAIEmbeddingProvider,
    )

    assert LocalEmbeddingProvider("m").model_id == "m"
    assert NoopEmbeddingProvider().model_id == "noop-stub"
    op = OpenAIEmbeddingProvider(api_key="k", model="text-embedding-3-small", api_base="https://x")
    assert op.model_id == "text-embedding-3-small"
