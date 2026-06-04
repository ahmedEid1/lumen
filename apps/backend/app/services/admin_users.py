"""Admin user-management service layer (S6.6 / S6.7).

The admin-authority lifecycle actions on *other* users:

* ``set_admin`` — grant/revoke the admin role (FR-ADMIN-01), guarded by the
  last-admin invariant (FR-ADMIN-03);
* ``suspend`` / ``reinstate`` — the first-class suspension lifecycle
  (FR-SUSP-01/02), sharing ``is_active`` with deletion but distinguished by
  ``deleted_at IS NULL`` (ADR-0030 §D3).

All invariants live here (NFR-SEC-3 — checked in the service layer, not just the
route). Each mutation writes an immutable ``AuditEvent`` with ip/ua threaded
from the endpoint (FR-AUDIT-02).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.errors import (
    AccountDeletedIrreversibleError,
    LastAdminError,
)
from app.core.logging import get_logger
from app.models.user import Role
from app.repositories import audit as audit_repo
from app.repositories import users as users_repo
from app.services.moderation_taxonomy import ReasonCode, sanitize_note

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User

log = get_logger(__name__)


async def assert_active_admin_invariant(
    db: AsyncSession, *, excluding_user_id: str, code: str = "user.last_admin"
) -> None:
    """Refuse an action that would drop the active-admin count to zero.

    ``excluding_user_id`` is the user whose admin-ness is being *removed*
    (demoted or suspended): we count the active admins that would remain if that
    user no longer counted. The single source of truth (FR-ADMIN-03) — the
    grant/revoke toggle AND the suspend path both route through here.

    ``code`` lets the suspend path surface ``user.last_admin_active`` while the
    revoke path uses ``user.last_admin`` (both are ``LastAdminError`` / 422).
    """
    remaining = await users_repo.count_active_admins(db, excluding=excluding_user_id)
    if remaining < 1:
        raise LastAdminError("The platform must always have at least one active admin", code=code)


async def set_admin(
    db: AsyncSession,
    *,
    target: User,
    is_admin: bool,
    actor: User,
    ip: str | None = None,
    user_agent: str | None = None,
) -> User:
    """Grant or revoke the admin role on ``target`` (FR-ADMIN-01/03).

    Revoking is refused if it would leave zero active admins (the invariant
    covers self-demotion AND demoting the only *other* admin). A no-op (already
    in the requested state) returns without writing a duplicate audit row.
    """
    desired = Role.admin if is_admin else Role.user
    if target.role == desired:
        # Idempotent — no flip, no audit churn.
        return target

    if not is_admin:
        # Revoking admin: the resulting active-admin count (excluding this
        # target, who is becoming a plain user) must stay ≥ 1.
        await assert_active_admin_invariant(db, excluding_user_id=target.id, code="user.last_admin")

    target.role = desired
    await audit_repo.record(
        db,
        actor_id=actor.id,
        action="admin.user.grant_admin" if is_admin else "admin.user.revoke_admin",
        target_type="user",
        target_id=target.id,
        ip_address=ip,
        user_agent=user_agent,
        data={"is_admin": is_admin},
    )
    return target


async def suspend(
    db: AsyncSession,
    *,
    target: User,
    reason: ReasonCode,
    note: str | None = None,
    actor: User,
    ip: str | None = None,
    user_agent: str | None = None,
) -> User:
    """Suspend a user (FR-SUSP-01/04): ``is_active=False``, revoke all refresh
    tokens, ``deleted_at`` stays null (the suspend-vs-delete discriminator).

    If the target is the last active admin, the suspension is refused with
    ``422 user.last_admin_active`` (reuses the S6.6 invariant). The notification
    carries the taxonomy **label**, never the admin's raw free-text note
    (FR-SUSP-04).
    """
    if target.role == Role.admin and target.is_active:
        await assert_active_admin_invariant(
            db, excluding_user_id=target.id, code="user.last_admin_active"
        )

    target.is_active = False
    # Defence-in-depth: never let a suspend masquerade as / overwrite a tombstone.
    # (delete_account is the only writer of deleted_at.)
    await users_repo.revoke_all_refresh_tokens(db, target.id)

    clean_note = sanitize_note(note)
    await audit_repo.record(
        db,
        actor_id=actor.id,
        action="admin.user.suspend",
        target_type="user",
        target_id=target.id,
        ip_address=ip,
        user_agent=user_agent,
        data={"reason": reason.value, **({"note": clean_note} if clean_note else {})},
    )

    # FR-SUSP-04: notify the suspended user with the taxonomy LABEL only — the
    # admin's raw note never reaches the affected user. Best-effort.
    try:
        from app.repositories import notifications as notifications_repo

        await notifications_repo.create(
            db,
            user_id=target.id,
            kind="account.suspended",  # type: ignore[arg-type]
            title="Your account has been suspended",
            data={"reason": reason.value},
        )
    except Exception as exc:  # pragma: no cover — notification best-effort
        log.warning("suspend_notify_failed", error=str(exc), user_id=target.id)

    return target


async def reinstate(
    db: AsyncSession,
    *,
    target: User,
    actor: User,
    ip: str | None = None,
    user_agent: str | None = None,
) -> User:
    """Reinstate a suspended user (FR-SUSP-02): ``is_active=True``.

    Refresh tokens are NOT restored (the user re-authenticates). Refused with
    ``422 user.deleted_irreversible`` on a tombstoned account (``deleted_at IS
    NOT NULL``) — deletion is terminal (ADR-0030 §D3). Idempotent: reinstating an
    already-active user writes no duplicate audit row.
    """
    if target.deleted_at is not None:
        raise AccountDeletedIrreversibleError(
            "A deleted account cannot be reinstated", code="user.deleted_irreversible"
        )
    if target.is_active:
        # Idempotent — already active, no-op (no duplicate audit).
        return target

    target.is_active = True
    await audit_repo.record(
        db,
        actor_id=actor.id,
        action="admin.user.reinstate",
        target_type="user",
        target_id=target.id,
        ip_address=ip,
        user_agent=user_agent,
    )
    return target
