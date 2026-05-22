"""Per-kind notification preferences (Phase D4).

The user model carries a JSONB ``notification_prefs`` column that
stores a sparse map of ``NotificationKind -> NotificationDispatch``.
This module is the *only* place that resolves the merge between the
stored sparse map and the system defaults, so the rest of the codebase
can ask one question — "given this user and this kind, what should I
do?" — without reasoning about defaults.

Defaults preserve pre-D4 behaviour: every kind defaults to
``in_app`` so existing users keep the bell-only experience unless
they opt in to email.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.notification import NotificationKind
from app.models.user import User
from app.schemas.notification_prefs import NotificationDispatch

DEFAULT_DISPATCH: NotificationDispatch = NotificationDispatch.in_app


def _coerce_dispatch(value: Any) -> NotificationDispatch:
    """Best-effort coercion of a stored value into a dispatch enum.

    The JSONB column is opaque to SQLAlchemy so we can't rely on enum
    validation at the ORM layer. Treat anything we don't recognise as
    the default rather than letting a stale row crash a notification
    write — this is a frequently-hit hot path.
    """
    try:
        return NotificationDispatch(value)
    except (ValueError, TypeError):
        return DEFAULT_DISPATCH


def resolve_dispatch(
    user: User, kind: NotificationKind | str
) -> NotificationDispatch:
    """Return the dispatch mode for ``user`` × ``kind`` with defaults applied.

    Accepts both the :class:`NotificationKind` enum (the original
    contract) and a raw string. The string form supports H6's
    ``security.refresh_reuse`` sub-kind, which isn't in the enum yet
    but persists fine because the column is a plain ``String(40)``.
    For any string that doesn't have an explicit user pref, the
    default dispatch kicks in (in-app, no email).
    """
    key = kind.value if isinstance(kind, NotificationKind) else str(kind)
    stored = (user.notification_prefs or {}).get(key)
    if stored is None:
        return DEFAULT_DISPATCH
    return _coerce_dispatch(stored)


def get_prefs(user: User) -> dict[NotificationKind, NotificationDispatch]:
    """Materialise the complete dispatch map for the user.

    Every :class:`NotificationKind` is present in the returned dict —
    kinds the user has never touched come back as
    :data:`DEFAULT_DISPATCH` so the UI can render a single form from
    one round trip.
    """
    stored = user.notification_prefs or {}
    out: dict[NotificationKind, NotificationDispatch] = {}
    for kind in NotificationKind:
        raw = stored.get(kind.value)
        out[kind] = DEFAULT_DISPATCH if raw is None else _coerce_dispatch(raw)
    return out


async def update_prefs(
    db: AsyncSession,
    *,
    user: User,
    prefs: dict[NotificationKind, NotificationDispatch],
) -> dict[NotificationKind, NotificationDispatch]:
    """Merge a partial update into the user's stored prefs.

    Only kinds present in ``prefs`` are touched; everything else keeps
    its existing stored value (or the default, if absent). The merged
    result is written back to the JSONB column and returned in
    materialised form.
    """
    current: dict[str, str] = dict(user.notification_prefs or {})
    for kind, dispatch in prefs.items():
        current[kind.value] = dispatch.value
    user.notification_prefs = current
    # JSONB mutations on a dict-in-place aren't auto-detected by the
    # SQLAlchemy ORM. ``flag_modified`` ensures the UPDATE is emitted
    # even when the column was previously ``{}`` and the dict identity
    # didn't change between the read and the write.
    flag_modified(user, "notification_prefs")
    await db.flush()
    return get_prefs(user)
