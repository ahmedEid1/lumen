from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.email_type import Email
from app.models.user import Role

#: The single-sourced i18n KEY (ADR-0030 §D5 / DR-19) emitted in any author/owner
#: name field whose underlying row is tombstoned. The frontend resolves it to
#: "a deleted user" / "مستخدم محذوف"; the backend never stores a localized
#: string. Read-time rendering means PII anonymizes even if the one-time scrub
#: didn't run (robust to migration ordering).
DELETED_USER_LABEL = "common.deletedUser"

#: The provenance sentinel written by ``account.delete_account`` into a clone's
#: ``origin_owner_name_snapshot``. Re-declared here (not imported) to avoid a
#: schema→service import cycle; kept in lockstep with
#: ``app.services.account.DELETED_OWNER_SNAPSHOT``. Uses ``\x01`` (SOH), not
#: ``\x00`` (NUL) — Postgres ``text``/``varchar`` cannot store a NUL byte, so the
#: written sentinel is ``\x01``-prefixed (S4 integration; see account.py).
_OWNER_SNAPSHOT_SENTINEL = "\x01deleted_user"


def resolve_owner_display_name(snapshot: str | None, *, owner_is_deleted: bool = False) -> str:
    """Render a course-provenance owner name at READ time (DR-19).

    Returns the localized deleted-user label key when the origin owner is
    tombstoned OR the stored snapshot equals the deletion sentinel OR the
    snapshot is empty — otherwise the snapshot verbatim. The ``owner_is_deleted``
    branch is the read-time guarantee: even if the one-time snapshot scrub never
    ran (the snapshot still holds the real name), a deleted owner anonymizes.
    """
    if owner_is_deleted:
        return DELETED_USER_LABEL
    if not snapshot or snapshot == _OWNER_SNAPSHOT_SENTINEL:
        return DELETED_USER_LABEL
    return snapshot


class UserPublic(BaseModel):
    """Profile fields safe to expose to anyone.

    DR-19 read-time anonymization: when validated from a tombstoned ORM ``User``
    (``deleted_at IS NOT NULL``), the name is replaced by the ``common.deletedUser``
    label key and all other PII (avatar, bio) is suppressed — so any author/owner-
    bearing DTO that nests ``UserPublic`` (``ReviewOut``, discussion DTOs, course
    ``owner``) anonymizes a deleted user with no per-DTO branch.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    full_name: str
    avatar_url: str | None = None
    bio: str | None = None
    role: Role

    @model_validator(mode="before")
    @classmethod
    def _anonymize_tombstone(cls, data: Any) -> Any:
        # Only act when validating from an ORM object (from_attributes path) that
        # carries a ``deleted_at`` attribute. A plain dict (already-serialized)
        # passes through untouched.
        deleted_at = getattr(data, "deleted_at", None)
        if deleted_at is None:
            return data
        return {
            "id": getattr(data, "id", ""),
            "full_name": DELETED_USER_LABEL,
            "avatar_url": None,
            "bio": None,
            "role": getattr(data, "role", Role.user),
        }


class UserOut(UserPublic):
    """Profile fields for the authenticated user."""

    email: Email
    is_active: bool
    email_verified_at: datetime | None = None
    created_at: datetime


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    bio: str | None = Field(default=None, max_length=1000)
    avatar_url: str | None = Field(default=None, max_length=500)
