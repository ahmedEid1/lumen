"""Capability predicates — the single home for authorization intent.

S7-pre.2 / ADR-0025 §D2. Pure functions over the loaded ``User`` + global
``Settings``. There is **no** per-user permission table (R-CAP): suspension
(``is_active=False``) is the single per-user revocation axis, so every
predicate is ``False`` for a suspended (or deleted-tombstone) user.

Design rules (ADR-0025 §D2):

* ``admin`` is always active and passes every capability; guarded
  capabilities additionally treat ``u.is_admin()`` as a pass.
* Default-granted to every active user: author, clone, publish-public,
  BYOK. (Each still has its own quota/ownership checks at the call site —
  these predicates answer "is the door open at all", not "within quota".)
* ``can_ingest_url`` is **closed by construction**: active AND admin AND the
  global ``Settings.ingest_url_enabled`` flag (default ``False``). The
  two-role collapse does NOT auto-open URL ingest — the danger is SSRF, not
  identity, so it stays admin-only + flag-off until the SSRF-hardening ADR
  lands (R-M12, FR-SEC-02).
* ``can_use_mcp_authoring`` is gated by the global ``mcp_authoring_enabled``
  flag (default ``True``) — replaces the old ``is_instructor`` MCP gate.

The deps in ``app.api.deps`` and the MCP principal are thin wrappers over
these; service entries re-check them so authorization isn't route-only.
"""

from __future__ import annotations

from typing import Any

from app.models.user import User


def _active(u: User) -> bool:
    """Suspension (``is_active=False``) is the single revocation axis (R-CAP)."""
    return bool(u.is_active)


def can_author(u: User) -> bool:
    """Any active user may author courses/lessons/AI-authoring."""
    return _active(u)


def can_clone(u: User) -> bool:
    """Any active user may clone a publicly-listed course (quota at call site)."""
    return _active(u)


def can_publish_public(u: User) -> bool:
    """Any active user may publish publicly (quota + moderation at call site)."""
    return _active(u)


def can_use_byok(u: User) -> bool:
    """BYOK reachability = active (suspension-only revocation, R-CAP).

    FR-BYOK-22's per-user revoke column is dropped (R-CAP) — suspension
    covers abuse.
    """
    return _active(u)


def can_view_course_analytics(u: User, course: Any) -> bool:
    """Owner-or-admin only (the analytics route's service-layer re-check)."""
    if not _active(u):
        return False
    return u.is_admin() or getattr(course, "owner_id", None) == u.id


def can_use_mcp_authoring(u: User, settings: Any) -> bool:
    """Active user AND the global ``mcp_authoring_enabled`` flag (default ON)."""
    return _active(u) and bool(getattr(settings, "mcp_authoring_enabled", False))


def can_ingest_url(u: User, settings: Any) -> bool:
    """Active AND admin AND the global ``ingest_url_enabled`` flag (default OFF).

    Closed by construction until SSRF hardening (R-M12). Not per-user, not
    auto-opened by the role collapse.
    """
    return _active(u) and u.is_admin() and bool(getattr(settings, "ingest_url_enabled", False))
