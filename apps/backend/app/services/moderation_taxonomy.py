"""Shared moderation/suspension reason taxonomy + inert-text sanitizer (S6.1).

The **single** place the reason taxonomy lives — shared by course moderation
(ADR-0026 §4 transition table) AND user suspension (FR-SUSP-03). Folding both
into one ``StrEnum`` keeps the csam/illegal/severe_abuse hard-removal split
consistent across the two surfaces.

DR-18-R2 scope split (the load-bearing distinction):

* ``QUARANTINE_REASONS = {csam, illegal}`` — the full-quarantine path. The
  ``courses.quarantined`` column (S2.10 / 0044) is set ``True`` ONLY for these,
  and it is the single source of truth for both the Python ``can_view_course``
  and the SQL ``publicly_listed_sql`` / ``retrieval_acl_clause`` owner-branch:
  even the owner and enrolled learners lose access (R-C6′).
* ``HARD_REMOVAL_REASONS = {csam, illegal, severe_abuse}`` — reasons that
  hard-remove (soft-delete + revoke enrolled access). ``severe_abuse`` is
  hard-removal **only**: the owner keeps view/edit (the tutor-disable signal is
  a separate ``moderation_event.reason_code`` read per ADR-0026 §3), so it is
  **never** in ``QUARANTINE_REASONS``.

``sanitize_note`` (FR-MOD-13 / FR-SUSP-03) renders untrusted reporter/admin
note text inert: it strips control characters, HTML-escapes markup so it can
never render, and length-caps. It is applied before any note is persisted
(``course_reports.note``, ``moderation_events.note``) so the admin UI can echo
the stored value verbatim without an XSS vector.
"""

from __future__ import annotations

import html
import re
from enum import StrEnum

#: Max length of a persisted note (FR-MOD-13 / FR-SUSP-03). The DB columns are
#: ``Text`` so this is a product cap, not a storage limit — it bounds abuse
#: (a 1 MB "note") and keeps the admin queue render cheap.
DEFAULT_NOTE_MAX_LEN = 1000


class ReasonCode(StrEnum):
    """The unified moderation + suspension reason taxonomy (FR-SUSP-03 ∪
    hard-removal). ``StrEnum`` so it coerces cleanly through Pydantic v2 request
    bodies and serialises to its string value in JSON / the audit ``data``.
    """

    spam = "spam"
    abuse = "abuse"
    fraud = "fraud"
    tos_violation = "tos_violation"
    copyright = "copyright"
    security = "security"
    illegal = "illegal"
    csam = "csam"
    severe_abuse = "severe_abuse"
    other = "other"


#: csam/illegal → full quarantine (``courses.quarantined = True``; even the
#: owner and enrolled learners lose access — R-C6′ / DR-18-R2). NEVER includes
#: ``severe_abuse``.
QUARANTINE_REASONS: frozenset[ReasonCode] = frozenset({ReasonCode.csam, ReasonCode.illegal})

#: Reasons that trigger a hard removal (soft-delete + revoke enrolled access).
#: Superset of ``QUARANTINE_REASONS`` plus ``severe_abuse`` (owner keeps
#: view/edit; not quarantined).
HARD_REMOVAL_REASONS: frozenset[ReasonCode] = frozenset(
    {ReasonCode.csam, ReasonCode.illegal, ReasonCode.severe_abuse}
)


# Control characters to strip: everything in the C0/C1 ranges EXCEPT the
# benign whitespace we want to keep (tab \x09, newline \x0a, carriage
# return \x0d). \x0b (vertical tab) and \x0c (form feed) are stripped — they
# are whitespace but can break terminal/CSV renders and carry no meaning here.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_note(text: str | None, *, max_len: int = DEFAULT_NOTE_MAX_LEN) -> str | None:
    """Render an untrusted note inert and length-capped (FR-MOD-13).

    Returns ``None`` for ``None`` or an all-whitespace note. Otherwise:

    1. strip control characters (NUL, bell, vertical tab, form feed, …) while
       keeping ``\\t``/``\\n``/``\\r`` so multi-line notes survive;
    2. HTML-escape ``& < > " '`` so any markup is displayed as literal text and
       can never render (XSS-safe when echoed in the admin UI);
    3. trim surrounding whitespace;
    4. truncate to ``max_len`` characters.

    The escape happens *after* trimming so the cap counts the escaped form
    (entities like ``&amp;`` are longer than the source) — the stored value
    never exceeds ``max_len``.
    """
    if text is None:
        return None
    stripped = _CONTROL_CHARS.sub("", text).strip()
    if not stripped:
        return None
    inert = html.escape(stripped, quote=True)
    if len(inert) > max_len:
        inert = inert[:max_len]
    return inert
