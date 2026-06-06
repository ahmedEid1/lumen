"""S2.9 — advisory moderation classifier (moderation_safety).

Pure-unit (no DB). The classifier is **advisory triage only** (R-C1′): it sets
a queue-priority signal, NEVER auto-approves, and **fails closed to
pending_review** on any error. These tests pin that it never returns an
``approved`` recommendation and that an exception path still yields a
pending-review signal.
"""

from __future__ import annotations

from app.models.course import ModerationState
from app.services import moderation_safety as ms


def test_clean_content_is_advisory_not_approved():
    signal = ms.classify(title="Intro to Python", overview="Learn the basics.", outcomes=["loops"])
    # Advisory only: a clean course is suggested for normal review, never auto-approved.
    assert signal.recommended_state == ModerationState.pending_review
    assert signal.flagged is False


def test_blocklisted_content_flags_but_never_approves():
    signal = ms.classify(
        title="How to make a bomb",
        overview="step by step explosives",
        outcomes=["weaponize"],
    )
    assert signal.flagged is True
    assert signal.recommended_state == ModerationState.pending_review
    assert signal.recommended_state != ModerationState.approved


def test_classifier_never_returns_approved_for_any_input():
    for title in ("", "x" * 500, "normal course", "violence gore csam"):
        signal = ms.classify(title=title, overview="", outcomes=[])
        assert signal.recommended_state != ModerationState.approved


def test_classifier_fails_closed_to_pending_on_error(monkeypatch):
    """If the heuristic raises, the public entrypoint returns pending_review."""

    def _boom(*a, **k):
        raise RuntimeError("classifier broke")

    monkeypatch.setattr(ms, "_score", _boom)
    signal = ms.classify(title="anything", overview="", outcomes=[])
    assert signal.recommended_state == ModerationState.pending_review
    assert signal.fail_closed is True
