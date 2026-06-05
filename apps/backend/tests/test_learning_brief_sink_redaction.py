"""S3 privacy-contract sink tests — the raw goal never escapes (FR-PRIV-01).

Charter decision 2 / FR-PRIV-01 / DR-22: the learner's raw goal text is
field-encrypted at rest and must NEVER appear in logs, traces, repr,
serialization, or admin-facing views. These tests mirror the BYOK
sink-redaction suite (``test_byok_sink_redaction.py``): a sentinel goal is
driven through each visible sink and asserted absent.

Unlike a BYOK key (caught value-by-value by the structlog value-redaction
processor), the goal's defense is *architectural* — it lives only as ciphertext
on the model and as a transient decrypt inside the in-request prompt builder.
So these tests assert the sinks that touch a brief (its repr, its ORM column
state, the structured DTO it serializes to, and a structlog line that binds the
whole object) never carry the plaintext.
"""

from __future__ import annotations

import io
import json
import logging

import pytest
import structlog

from app.core import logging as app_logging
from app.core import secrets_crypto
from app.models.learning_brief import LearningBrief
from app.schemas.learning_brief import BriefOut

# A distinctive sentinel goal — any leak is unmistakable (BYOK SENTINEL idiom).
SENTINEL_GOAL = "GOAL-SENTINEL-do-not-leak: master quantum error correction"


@pytest.fixture
def captured_logs():
    """structlog → JSON buffer with the value-redaction processor installed
    (the same fixture shape as test_byok_sink_redaction)."""
    buf = io.StringIO()
    structlog.reset_defaults()
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            app_logging.value_redaction_processor,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=buf),
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=False,
    )
    yield buf
    structlog.reset_defaults()


def _brief_with_goal() -> LearningBrief:
    # JSONB server-defaults only fire on a DB insert; set them explicitly for
    # the in-memory object so BriefOut.model_validate sees real lists/dicts.
    return LearningBrief(
        id="briefSINK",
        owner_id="ownerSINK",
        source_goal_enc=secrets_crypto.encrypt(SENTINEL_GOAL.encode("utf-8")),
        goal_summary="A non-sensitive paraphrase",
        level="advanced",
        desired_outcomes=[],
        format_prefs={},
    )


def test_goal_absent_from_repr_and_str():
    brief = _brief_with_goal()
    assert SENTINEL_GOAL not in repr(brief)
    assert SENTINEL_GOAL not in str(brief)


def test_goal_absent_from_orm_column_dump():
    """A logger / serializer that walks ``__dict__`` (sans SA internals) must
    not surface the plaintext — only the ciphertext blob is present."""
    brief = _brief_with_goal()
    flat = repr({k: v for k, v in brief.__dict__.items() if not k.startswith("_sa_")})
    assert SENTINEL_GOAL not in flat


def test_goal_absent_from_brief_out_serialization():
    """The public DTO carries structured fields only — no raw goal / ciphertext
    (FR-PRIV-01). model_dump(mode="json") is the wire shape an admin/API sees."""
    brief = _brief_with_goal()
    brief.finalized_at = None
    dumped = BriefOut.model_validate(brief).model_dump(mode="json")
    flat = json.dumps(dumped)
    assert SENTINEL_GOAL not in flat
    assert "source_goal_enc" not in dumped
    assert "goal" not in dumped


def test_goal_absent_when_brief_logged_as_event_value(captured_logs):
    """Binding the whole brief object into a structlog line must not leak the
    goal — repr is the rendering structlog uses for a non-primitive value."""
    brief = _brief_with_goal()
    log = structlog.get_logger()
    log.info("goal_session_started", brief=brief, brief_id=brief.id)
    out = captured_logs.getvalue()
    assert SENTINEL_GOAL not in out
    # The non-sensitive id is fine to log (and useful for debugging).
    assert "briefSINK" in out


def test_ciphertext_decrypts_back_to_goal():
    """Sanity: the ciphertext IS the goal (so the absence above is meaningful,
    not just an empty blob)."""
    brief = _brief_with_goal()
    assert secrets_crypto.decrypt(brief.source_goal_enc).decode("utf-8") == SENTINEL_GOAL
