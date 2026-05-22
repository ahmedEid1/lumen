"""Schemas for per-kind notification preferences (Phase D4)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.models.notification import NotificationKind


class NotificationDispatch(StrEnum):
    """Per-kind dispatch mode.

    - ``off``: drop the notification entirely (no bell row, no email).
    - ``in_app``: create the row, no email. This is the default — it
      preserves the bell-only behaviour Lumen shipped before D4.
    - ``email_immediate``: create the row *and* enqueue an email send
      immediately when the notification fires.
    - ``digest_daily``: create the row, no immediate email; the daily
      digest worker bundles unread ``digest_daily`` rows into a single
      summary email and stamps ``digested_at`` on each.
    """

    off = "off"
    in_app = "in_app"
    email_immediate = "email_immediate"
    digest_daily = "digest_daily"


# Per-kind dispatch map. We use a free-form ``dict[NotificationKind, ...]``
# rather than one explicit field per kind so that adding a new
# ``NotificationKind`` doesn't require a coordinated schema bump —
# Pydantic validates every key against the enum.
PrefsMap = dict[NotificationKind, NotificationDispatch]


class NotificationPrefs(BaseModel):
    """Public view of a user's notification dispatch preferences.

    Always materialised — even kinds the user has never touched come
    back filled with the default (``in_app``) so the frontend can render
    every row from a single GET.
    """

    model_config = ConfigDict(use_enum_values=False)

    prefs: PrefsMap = Field(
        default_factory=dict,
        description="Dispatch mode per NotificationKind",
    )


class NotificationPrefsUpdate(BaseModel):
    """Payload for ``PUT /me/notifications/prefs``.

    Accepts a partial map — only kinds the user wants to change need to
    appear. Kinds omitted from the payload keep their existing value
    (or fall back to ``in_app`` if never set).
    """

    model_config = ConfigDict(use_enum_values=False, extra="forbid")

    prefs: PrefsMap = Field(default_factory=dict)
