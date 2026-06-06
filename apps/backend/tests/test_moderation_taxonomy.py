"""S6.1 — moderation/suspension reason taxonomy + report-content sanitizer.

One source of truth for the reason taxonomy (FR-SUSP-03 set ∪ hard-removal
set) and the inert-text ``sanitize_note`` used by reports, suspensions, and
moderation actions (FR-MOD-13 / FR-SUSP-03). DR-18-R2 splits the
hard-removal set from the quarantine set: ``severe_abuse`` is hard-removal
only (owner keeps view/edit), never quarantine — only ``csam``/``illegal``
quarantine.

Pure-unit: no DB.
"""

from __future__ import annotations

from app.services.moderation_taxonomy import (
    HARD_REMOVAL_REASONS,
    QUARANTINE_REASONS,
    ReasonCode,
    sanitize_note,
)

# ---------------------------------------------------------------------------
# sanitize_note (FR-MOD-13 / FR-SUSP-03)
# ---------------------------------------------------------------------------


def test_sanitize_note_strips_markup_and_caps():
    """HTML/control chars are inertly escaped/stripped; >max_len is truncated."""
    raw = "<script>alert('x')</script>"
    out = sanitize_note(raw)
    assert out is not None
    # No raw angle-bracket markup survives — the tag cannot render.
    assert "<script>" not in out
    assert "</script>" not in out
    assert "<" not in out and ">" not in out

    # Control characters are stripped (NUL, bell, vertical tab, form feed).
    dirty = "hello\x00\x07\x0b\x0cworld"
    cleaned = sanitize_note(dirty)
    assert cleaned is not None
    assert "\x00" not in cleaned
    assert "\x07" not in cleaned
    assert "hello" in cleaned and "world" in cleaned

    # A 5000-char note is truncated to <= 1000 (default cap).
    long_note = "a" * 5000
    capped = sanitize_note(long_note)
    assert capped is not None
    assert len(capped) <= 1000

    # Explicit max_len is honoured.
    assert len(sanitize_note("b" * 100, max_len=20) or "") <= 20


def test_sanitize_note_none_and_blank():
    """None passes through as None; an all-whitespace note collapses to None."""
    assert sanitize_note(None) is None
    assert sanitize_note("   ") is None
    assert sanitize_note("\t\n  ") is None


def test_sanitize_note_preserves_plain_text():
    """Ordinary text (incl. newlines/tabs as whitespace) survives, trimmed."""
    out = sanitize_note("  This course promotes spam.\nReally.  ")
    assert out == "This course promotes spam.\nReally."


def test_sanitize_note_escapes_ampersand_and_quotes():
    """Ampersands and quotes are HTML-escaped so the text is inert when echoed."""
    out = sanitize_note('A & B "quoted"')
    assert out is not None
    assert "&amp;" in out
    # The literal raw double-quote must not survive un-escaped.
    assert "&quot;" in out or "&#x27;" in out or '"' not in out


# ---------------------------------------------------------------------------
# Taxonomy membership (DR-18-R2 scope split)
# ---------------------------------------------------------------------------


def test_reason_taxonomy_membership():
    # csam + illegal quarantine (full lockout).
    assert ReasonCode.csam in QUARANTINE_REASONS
    assert ReasonCode.illegal in QUARANTINE_REASONS
    # severe_abuse is hard-removal-ONLY, never quarantine (owner keeps view/edit).
    assert ReasonCode.severe_abuse in HARD_REMOVAL_REASONS
    assert ReasonCode.severe_abuse not in QUARANTINE_REASONS
    # csam + illegal are also in the hard-removal set (superset relationship).
    assert ReasonCode.csam in HARD_REMOVAL_REASONS
    assert ReasonCode.illegal in HARD_REMOVAL_REASONS
    # spam is in neither (a soft delist/dismiss reason).
    assert ReasonCode.spam not in QUARANTINE_REASONS
    assert ReasonCode.spam not in HARD_REMOVAL_REASONS


def test_quarantine_is_subset_of_hard_removal():
    """Every quarantine reason is also a hard-removal reason (DR-18-R2)."""
    assert QUARANTINE_REASONS <= HARD_REMOVAL_REASONS


def test_reason_code_is_str_enum_with_full_set():
    """The full FR-SUSP-03 ∪ hard-removal taxonomy is present and string-valued."""
    expected = {
        "spam",
        "abuse",
        "fraud",
        "tos_violation",
        "copyright",
        "security",
        "illegal",
        "csam",
        "severe_abuse",
        "other",
    }
    assert {r.value for r in ReasonCode} == expected
    # StrEnum: a member compares equal to its string value (Pydantic coercion).
    assert ReasonCode.csam == "csam"
    assert ReasonCode("spam") is ReasonCode.spam
