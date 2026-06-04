"""Account lifecycle service: self-serve deletion + cooperative cancellation.

ADR-0030. Self-serve ``DELETE /me`` is **anonymize-in-place**: we never call
``session.delete(user)``. The ``users`` row persists forever as an anonymized
tombstone; every FK graph stays intact (lineage, audit, cost integrity); PII is
irreversibly scrubbed. Suspension (admin) shares ``is_active`` but is reversible
— the single discriminator is ``deleted_at IS NULL``.

The choreography (D2) runs inside the request's single transaction so any
failure rolls everything back — no half-tombstone. The **core** PII scrub +
deactivate is un-guarded (must succeed); only the optional sibling-table steps
are narrowly try-guarded (catch only ``ProgrammingError``/``UndefinedTable``/
``ImportError``) so a not-yet-landed sibling table never blocks the core scrub
(open-risk 1).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select, update
from sqlalchemy.exc import ProgrammingError

from app.core.errors import AccessRevokedError, UnauthorizedError
from app.core.logging import get_logger
from app.core.security import hash_password, verify_password
from app.repositories import audit as audit_repo
from app.repositories import users as users_repo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User

log = get_logger(__name__)

#: Sentinel written into a clone's ``origin_owner_name_snapshot`` when its origin
#: owner deletes their account (R-M13). The serializer (DR-19, S6.10) renders it
#: as the localized "a deleted user" label at READ time, so even if this one-time
#: scrub never ran (migration ordering), provenance still anonymizes.
DELETED_OWNER_SNAPSHOT = "\x00deleted_user"

#: The narrow set of exceptions a sibling-table step may swallow (open-risk 1).
#: NEVER a blanket ``Exception`` — that could hide a real bug and leave un-
#: scrubbed PII. ``ProgrammingError`` covers Postgres ``UndefinedTable`` /
#: ``UndefinedColumn``; ``ImportError`` covers a not-yet-landed model module.
_OPTIONAL_STEP_ERRORS = (ProgrammingError, ImportError)


async def assert_account_active(db: AsyncSession, user_id: str) -> None:
    """R-S10 cooperative-cancellation primitive.

    Re-reads ``is_active`` from the DB (NOT the session identity map, which may be
    stale) and raises ``AccessRevokedError`` (403 ``account.access_revoked``) if
    the account flipped to inactive (suspend or delete) mid-flight, or vanished.
    Fail-closed: a missing row is treated as revoked. Wired at the streaming
    tutor heartbeat and at build/clone phase fences — every future foreground LLM
    feature must adopt it (CHARTER risk / open-risk 3).
    """
    from app.models.user import User

    is_active = (
        await db.execute(select(User.is_active).where(User.id == user_id))
    ).scalar_one_or_none()
    if not is_active:
        raise AccessRevokedError("Account access has been revoked", code="account.access_revoked")


async def delete_account(
    db: AsyncSession,
    *,
    user: User,
    password: str,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Anonymize-in-place self-serve deletion (ADR-0030 §D2, R-M3').

    The 11-step D2 order — authn → audit-first → scrub PII + ``deleted_at`` →
    deactivate → purge sessions → [guarded] BYOK purge → MCP revoke → owned-
    course delist+soft-delete → provenance anonymize → discussion soft-delete →
    review soft-delete. Steps 6–11 are independently try-guarded against missing
    sibling tables; the core (steps 1–5) is un-guarded.
    """
    # ---- Step 1. Authn re-check (the destructive-action confirmation) ----
    if not verify_password(password, user.password_hash):
        raise UnauthorizedError("Password is incorrect", code="auth.invalid_credentials")

    # ---- Step 2. Audit FIRST (before scrub, while the row is identifiable) ----
    await audit_repo.record(
        db,
        actor_id=user.id,
        action="user.deleted",
        target_type="user",
        target_id=user.id,
        ip_address=ip,
        user_agent=user_agent,
    )

    uid = user.id

    # ---- Step 3. Scrub PII on the users row + set the tombstone marker ----
    user.email = f"deleted-{uid}@lumen.invalid"
    user.full_name = ""  # rendered display name is a constant (D5)
    user.avatar_url = None
    user.bio = None
    user.password_hash = hash_password("!disabled!" + uid)  # unusable
    user.email_verified_at = None
    await users_repo.mark_deleted(db, user)  # deleted_at = now()

    # ---- Step 4. Deactivate (next request 401s; login/refresh blocked) ----
    user.is_active = False
    await db.flush()

    # ---- Step 5. Purge sessions (revoke then hard-delete the residue) ----
    await users_repo.revoke_all_refresh_tokens(db, uid)
    await users_repo.purge_refresh_tokens(db, uid)

    # ---- Step 6. Purge BYOK credentials (hard delete of key material) ----
    await _purge_byok_credentials(db, uid)

    # ---- Step 7. Revoke MCP clients ----
    await _revoke_mcp_clients(db, uid)

    # ---- Step 8. Owned courses: force-private + soft-delete (delist) ----
    await _delist_owned_courses(db, uid)

    # ---- Step 9. Anonymize provenance snapshots (R-M13) ----
    await _anonymize_provenance(db, uid)

    # ---- Step 10. Soft-delete authored discussions/replies ----
    await _soft_delete_discussions(db, uid)

    # ---- Step 11. Soft-delete authored reviews ----
    await _soft_delete_reviews(db, uid)


# ---------------------------------------------------------------------------
# Optional sibling-table steps — each narrowly try-guarded (open-risk 1).
# A not-yet-landed table/column makes the step a no-op; it NEVER blocks the
# core scrub above. The guard catches ONLY ProgrammingError/ImportError.
# ---------------------------------------------------------------------------


async def _purge_byok_credentials(db: AsyncSession, user_id: str) -> None:
    """Hard-delete every stored BYOK credential (FR-BYOK-18, D-58).

    Account deletion is terminal — this is a hard delete of key material, not the
    soft-delete used by ``DELETE /me/llm-credentials/{provider}``. ``llm_calls``
    rows (no key, plain-string user_id) are kept for cost history.
    """
    try:
        from sqlalchemy import delete as sa_delete

        from app.models.user_llm_credential import UserLLMCredential

        await db.execute(sa_delete(UserLLMCredential).where(UserLLMCredential.user_id == user_id))
    except _OPTIONAL_STEP_ERRORS as exc:  # pragma: no cover — pre-S5 tolerance
        log.warning("delete_account_byok_purge_skipped", error=str(exc), user_id=user_id)


async def _revoke_mcp_clients(db: AsyncSession, user_id: str) -> None:
    """Set ``revoked_at`` on the user's MCP clients (kills programmatic access)."""
    try:
        from app.models.mcp_client import McpClient

        await db.execute(
            update(McpClient)
            .where(McpClient.owner_user_id == user_id, McpClient.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
    except _OPTIONAL_STEP_ERRORS as exc:  # pragma: no cover — model tolerance
        log.warning("delete_account_mcp_revoke_skipped", error=str(exc), user_id=user_id)


async def _delist_owned_courses(db: AsyncSession, user_id: str) -> None:
    """Force every live owned course private + soft-delete it (delist).

    ``moderation_state`` is left UNCHANGED (sticky, R-C2) — we delist via
    ``visibility=private`` + ``deleted_at`` so ``is_publicly_listed`` is
    unambiguously false. Other users' enrollments/certs are preserved (FR-DEL-02);
    existing clones are unaffected (FR-DEL-01).
    """
    try:
        from app.models.course import Course, Visibility

        await db.execute(
            update(Course)
            .where(Course.owner_id == user_id, Course.deleted_at.is_(None))
            .values(visibility=Visibility.private, deleted_at=datetime.now(UTC))
        )
    except _OPTIONAL_STEP_ERRORS as exc:  # pragma: no cover — column tolerance
        # Fall back to soft-delete only if the visibility column is absent.
        log.warning("delete_account_delist_fallback", error=str(exc), user_id=user_id)
        try:
            from app.models.course import Course

            await db.execute(
                update(Course)
                .where(Course.owner_id == user_id, Course.deleted_at.is_(None))
                .values(deleted_at=datetime.now(UTC))
            )
        except _OPTIONAL_STEP_ERRORS as exc2:  # pragma: no cover
            log.warning("delete_account_delist_skipped", error=str(exc2), user_id=user_id)


async def _anonymize_provenance(db: AsyncSession, user_id: str) -> None:
    """Sentinel the provenance snapshot of clones of this user's courses.

    Tolerant of missing provenance columns pre-S4 (clone). Read-time rendering
    (DR-19 / S6.10) is the robust guarantee; this one-time scrub is best-effort.
    """
    try:
        from app.models.course import Course

        await db.execute(
            update(Course)
            .where(Course.origin_owner_id == user_id)
            .values(origin_owner_name_snapshot=DELETED_OWNER_SNAPSHOT)
        )
    except _OPTIONAL_STEP_ERRORS as exc:  # pragma: no cover — pre-S4 tolerance
        log.warning("delete_account_provenance_skipped", error=str(exc), user_id=user_id)
    except AttributeError as exc:  # pragma: no cover — column not mapped yet
        log.warning("delete_account_provenance_no_column", error=str(exc), user_id=user_id)


async def _soft_delete_discussions(db: AsyncSession, user_id: str) -> None:
    """Soft-delete the user's discussions + replies (hide authored Q&A text).

    ``author_id`` stays pointing at the tombstone (anonymize-in-place); only the
    body is hidden.
    """
    try:
        from app.models.discussion import Discussion, DiscussionReply

        now = datetime.now(UTC)
        await db.execute(
            update(Discussion)
            .where(Discussion.author_id == user_id, Discussion.deleted_at.is_(None))
            .values(deleted_at=now)
        )
        await db.execute(
            update(DiscussionReply)
            .where(DiscussionReply.author_id == user_id, DiscussionReply.deleted_at.is_(None))
            .values(deleted_at=now)
        )
    except _OPTIONAL_STEP_ERRORS as exc:  # pragma: no cover — model tolerance
        log.warning("delete_account_discussion_skipped", error=str(exc), user_id=user_id)


async def _soft_delete_reviews(db: AsyncSession, user_id: str) -> None:
    """Soft-delete the user's reviews (author pointer kept at the tombstone)."""
    try:
        from app.models.course import Review

        await db.execute(
            update(Review)
            .where(Review.author_id == user_id, Review.deleted_at.is_(None))
            .values(deleted_at=datetime.now(UTC))
        )
    except _OPTIONAL_STEP_ERRORS as exc:  # pragma: no cover — model tolerance
        log.warning("delete_account_review_skipped", error=str(exc), user_id=user_id)
