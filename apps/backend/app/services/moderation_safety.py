"""Advisory moderation classifier (ADR-0026 §"Classifier" / R-C1′).

**Advisory triage only.** The classifier sets a queue-priority signal and a
``classifier_signal`` payload stored on the ``ModerationEvent`` — it is NEVER a
security boundary and NEVER auto-approves (R-C1′: a weak heuristic must not be
the publish gate). The recommended state is at most ``pending_review``; only an
explicit admin action sets ``approved`` (S6).

**Fail-closed.** Any error in the heuristic resolves to ``pending_review`` with
``fail_closed=True`` (R-U5) — a broken classifier must never let content slip
to a less-reviewed state.

The default implementation is a deterministic keyword heuristic over
title + overview + outcomes against a small blocklist. An LLM variant is
deliberately off by default (cost + non-determinism + it still must not be the
gate).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.course import ModerationState

# A small, deterministic blocklist used only to RAISE queue priority — never to
# auto-reject. Real taxonomy/severity classification + the csam/illegal
# quarantine decision are admin actions (S6); this is triage signal only.
_BLOCKLIST: tuple[str, ...] = (
    "csam",
    "child sexual",
    "bomb",
    "explosive",
    "weaponize",
    "terror",
    "gore",
    "how to make a weapon",
)


@dataclass(frozen=True)
class ClassifierSignal:
    """Advisory triage output stored on the moderation event."""

    # The MOST permissive state the classifier may ever recommend is
    # pending_review — it can never recommend ``approved`` (R-C1′).
    recommended_state: ModerationState = ModerationState.pending_review
    flagged: bool = False
    fail_closed: bool = False
    matched_terms: list[str] = field(default_factory=list)

    def to_payload(self) -> dict:
        """JSON-serialisable shape for ``ModerationEvent.classifier_signal``."""
        return {
            "recommended_state": str(self.recommended_state),
            "flagged": self.flagged,
            "fail_closed": self.fail_closed,
            "matched_terms": list(self.matched_terms),
            "advisory_only": True,
        }


def _score(*, title: str, overview: str, outcomes: list[str]) -> list[str]:
    """Return the blocklist terms found in the combined text (deterministic)."""
    haystack = " ".join([title or "", overview or "", *(outcomes or [])]).lower()
    return [term for term in _BLOCKLIST if term in haystack]


def classify(*, title: str, overview: str, outcomes: list[str]) -> ClassifierSignal:
    """Advisory triage. NEVER returns ``approved``; fails closed to pending.

    The recommended state is ``pending_review`` regardless of the score — the
    score only sets ``flagged`` (queue priority). Any exception resolves to a
    fail-closed ``pending_review`` signal.
    """
    try:
        matched = _score(title=title, overview=overview, outcomes=outcomes)
    except Exception:
        # Fail closed — never let a broken classifier downgrade review (R-U5).
        return ClassifierSignal(
            recommended_state=ModerationState.pending_review,
            flagged=True,
            fail_closed=True,
        )
    return ClassifierSignal(
        recommended_state=ModerationState.pending_review,  # never approved (R-C1′)
        flagged=bool(matched),
        matched_terms=matched,
    )
