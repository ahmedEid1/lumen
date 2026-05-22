"""High-level notification helpers (Phase H6).

Most callsites still create notifications via
:mod:`app.repositories.notifications` directly — that's the per-user
dispatch-aware path. This module owns the *fan-out* helpers that need
to talk to the User repository to figure out who to notify:

* :func:`notify_admins` — write the same notification row for every
  active user with ``role == admin``. Used by the security-alarm path
  (refresh-token reuse) and reserved for any future "tell the operator
  something important happened" use case.

The helper is **best-effort**. Notifications are observability, not
business logic — a Postgres hiccup or a stray foreign-key surprise on
the admin row must never break the auth path. We catch everything,
log it via structlog, and let the caller move on.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.notification import NotificationKind
from app.models.user import Role, User
from app.repositories import notifications as notifications_repo

log = get_logger(__name__)


async def notify_admins(
    db: AsyncSession,
    *,
    kind: NotificationKind | str,
    title: str,
    body: str = "",
    data: dict[str, Any] | None = None,
) -> int:
    """Create a notification row for every active admin user.

    Returns the number of admins successfully notified — zero on full
    failure (the auth path doesn't care; the count is for tests + the
    admin observability surface in H7). The function never raises:

    * No admin exists → log a warning, return 0.
    * Postgres / dispatch failure mid-loop → log per-failure, keep going.
    * Whole-loop failure (e.g., connection dropped) → log, return 0.

    ``kind`` may be passed as the ``NotificationKind`` enum or a raw
    string. The :class:`Notification` model stores it as a 40-char
    VARCHAR, so a new security sub-kind (``security.refresh_reuse``)
    persists fine without an enum migration — keeping this helper
    decoupled from the enum lets H6 ship before the catalogue is
    formalised.
    """
    try:
        stmt = select(User).where(User.role == Role.admin, User.is_active.is_(True))
        admins = list((await db.execute(stmt)).scalars().all())
    except Exception as exc:  # pragma: no cover — DB-level oddity
        log.warning("notify_admins_lookup_failed", error=str(exc), kind=str(kind))
        return 0

    if not admins:
        log.warning("notify_admins_no_admins_found", kind=str(kind), title=title)
        return 0

    # The Notification model declares ``kind`` as ``Mapped[NotificationKind]``
    # but the column itself is a plain ``String(40)``. Passing a raw
    # string slips through; passing the enum value is identical. We
    # normalise to a string so the type checker doesn't complain when
    # the caller hands in a kind that isn't in the enum yet (e.g. the
    # new ``security.refresh_reuse`` sub-kind).
    kind_value = kind.value if isinstance(kind, NotificationKind) else str(kind)
    sent = 0
    for admin in admins:
        try:
            await notifications_repo.create(
                db,
                user_id=admin.id,
                # ``NotificationKind`` is a ``StrEnum`` whose underlying
                # value is a plain string, so SQLAlchemy accepts a raw
                # string here without a coercion. We pass through ``kind_value``
                # so a freshly-coined sub-kind doesn't require a code change
                # in the enum at the same time.
                kind=kind_value,  # type: ignore[arg-type]
                title=title,
                body=body,
                data=data or {},
            )
            sent += 1
        except Exception as exc:  # pragma: no cover — per-admin write hiccup
            log.warning(
                "notify_admins_write_failed",
                admin_id=admin.id,
                kind=kind_value,
                error=str(exc),
            )
    return sent
