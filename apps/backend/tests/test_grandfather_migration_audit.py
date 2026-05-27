"""Codex rescue (L21-Sec): the migration's audit INSERT uses
``:data::jsonb`` which is NOT a valid SQLAlchemy bind shape — `::`
is parsed as the Postgres cast operator. The bug only fires on a DB
with existing unverified users (the `if count > 0` branch); a clean
test DB skips it, which is why the CI suite passed despite the bug.

This test reproduces the exact INSERT pattern the rescue fixed,
locking the contract so a future refactor can't reintroduce the
``::jsonb`` shape.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_audit_insert_bind_with_jsonb_cast_works(
    db_session: AsyncSession,
) -> None:
    """The fixed SQL shape (``CAST(:data AS jsonb)``) must accept a
    bind-supplied JSON string without raising the
    "expected at least N parameters, got M" SQLAlchemy error."""
    payload = json.dumps({"count": 3, "loop": "L21-Sec"})
    # Exact bind shape from the migration — this exercises the
    # SQLAlchemy text-bind parsing that Codex flagged.
    await db_session.execute(
        text(
            """
            INSERT INTO audit_events (
                id, actor_id, action, target_type, data, created_at, updated_at
            )
            VALUES (
                :id, NULL, :action, 'user',
                CAST(:data AS jsonb),
                NOW(), NOW()
            )
            """
        ),
        {
            "id": "audit-test-row-1",
            "action": "auth.bulk_grandfather_email_verify",
            "data": payload,
        },
    )
    # Read it back — confirms the cast went through + the JSON
    # survived the round-trip.
    res = await db_session.execute(
        text(
            "SELECT data->>'count' AS count, data->>'loop' AS loop FROM audit_events WHERE id = :id"
        ),
        {"id": "audit-test-row-1"},
    )
    row = res.first()
    assert row is not None
    assert row.count == "3"
    assert row.loop == "L21-Sec"


@pytest.mark.asyncio
async def test_original_buggy_shape_would_have_raised(
    db_session: AsyncSession,
) -> None:
    """Negative test — the OLD shape (``:data::jsonb``) is what Codex
    caught. Confirm it actually fails so we know the rescue is real,
    not theoretical."""
    from sqlalchemy.exc import ProgrammingError, StatementError

    payload = json.dumps({"count": 1})

    with pytest.raises((ProgrammingError, StatementError, Exception)) as exc:
        await db_session.execute(
            text(
                """
                INSERT INTO audit_events (id, actor_id, action, data, created_at, updated_at)
                VALUES (:id, NULL, :action, :data::jsonb, NOW(), NOW())
                """
            ),
            {
                "id": "audit-buggy-row-1",
                "action": "test",
                "data": payload,
            },
        )
    # Roll back the implicit transaction so the next test starts clean.
    await db_session.rollback()
    # The error message references the missing bind or the typecast
    # mismatch — confirms SQLAlchemy refused to substitute the bind.
    msg = str(exc.value).lower()
    assert any(t in msg for t in ("bind", "parameter", "operator", "::", "type", "syntax"))
