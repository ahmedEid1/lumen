"""CI grep-guard #2: no un-allowlisted ``enforce_acl=False`` (PR-2 / ADR-0029 D8).

``find_relevant_chunks(..., enforce_acl=False)`` bypasses the data-level RAG
ACL. It is legitimate in exactly ONE place — the owner-proven inline-index
fallback (``find_relevant_chunks_inline_fallback``), where
``can_view_course`` has already established the caller may see the course. Any
new ``enforce_acl=False`` call site outside the allowlist is a potential
cross-user private-chunk leak and fails this guard.

Mirror of ``test_no_raw_published_checks``: marker-comment allowlist
(``# noqa: enforce-acl — ...``), double-backtick prose ignored, walks
``app/`` only.
"""

from __future__ import annotations

import re
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent.parent / "app"
_EXCLUDED_DIR_NAMES = {"__pycache__"}

# Match ``enforce_acl=False`` / ``enforce_acl = False`` (whitespace tolerant).
_RE_ENFORCE_FALSE = re.compile(r"enforce_acl\s*=\s*False")
# The allowlist marker carried on the single legitimate bypass line.
_MARKER = "# noqa: enforce-acl"
# Ignore double-backtick prose spans (docstrings naming the param).
_RE_BACKTICK_SPAN = re.compile(r"``[^`]*``")


def _scan() -> list[tuple[str, int, str]]:
    offenders: list[tuple[str, int, str]] = []
    for path in _APP_ROOT.rglob("*.py"):
        if any(part in _EXCLUDED_DIR_NAMES for part in path.parts):
            continue
        rel = str(path.relative_to(_APP_ROOT.parent))
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            scannable = _RE_BACKTICK_SPAN.sub("", line)
            if _RE_ENFORCE_FALSE.search(scannable) and _MARKER not in line:
                offenders.append((rel, lineno, line.strip()))
    return offenders


def test_no_unallowlisted_enforce_acl_false() -> None:
    offenders = _scan()
    if offenders:
        rendered = "\n".join(f"  {f}:{n}: {ln}" for f, n, ln in offenders)
        raise AssertionError(
            "`enforce_acl=False` found outside the allowlist. This bypasses the "
            "RAG retrieval ACL and risks a cross-user private-chunk leak. The ONLY "
            "legitimate site is the owner-proven inline-index fallback; mark it with "
            "'# noqa: enforce-acl — <reason>'. Offenders:\n" + rendered
        )


def test_inline_fallback_is_the_one_allowlisted_site() -> None:
    """Sanity: exactly one allowlisted bypass exists, in embeddings_retrieval."""
    allowlisted: list[str] = []
    for path in _APP_ROOT.rglob("*.py"):
        if any(part in _EXCLUDED_DIR_NAMES for part in path.parts):
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            scannable = _RE_BACKTICK_SPAN.sub("", line)
            if _RE_ENFORCE_FALSE.search(scannable) and _MARKER in line:
                allowlisted.append(str(path.relative_to(_APP_ROOT.parent)))
    assert allowlisted == ["app/services/embeddings_retrieval.py"], allowlisted
