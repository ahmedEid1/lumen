"""Cursor pagination on the admin audit log.

CLAUDE.md specifies "cursor for messages/audit" — chat history
already used it; the audit endpoint now does too. The ``?before=<id>``
filter returns events strictly older than the named anchor, same
shape as ``chat.history``.

Backwards-compatible: the response is still ``list[AuditEventOut]``,
the existing frontend call without ``before`` still gets the head
page. The frontend now paginates by passing the id of the oldest
displayed event.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.user import Role


async def _seed_events(db: AsyncSession, *, actor_id: str, n: int) -> list[str]:
    """Seed N events spread across N seconds so created_at is unique
    and ordering is deterministic. Returns ids in newest-first order."""
    base = datetime.now(UTC)
    events: list[AuditEvent] = []
    for i in range(n):
        ev = AuditEvent(
            actor_id=actor_id,
            action="test.seeded",
            target_type=None,
            target_id=None,
            data={"i": i},
        )
        ev.created_at = base - timedelta(seconds=i)
        db.add(ev)
        events.append(ev)
    await db.commit()
    for ev in events:
        await db.refresh(ev)
    # Sort newest first — matches the endpoint's DESC ordering.
    events.sort(key=lambda e: e.created_at, reverse=True)
    return [e.id for e in events]


async def test_before_cursor_returns_strictly_older_events(
    client: AsyncClient, auth_headers, db_session: AsyncSession, make_user
) -> None:
    admin = await auth_headers(role=Role.admin)
    actor = await make_user()
    ids = await _seed_events(db_session, actor_id=actor.id, n=8)

    # Page 1: head, limit 3 → newest three.
    head = await client.get(
        "/api/v1/admin/audit?limit=3&action=test.seeded", headers=admin
    )
    assert head.status_code == 200
    head_ids = [e["id"] for e in head.json()]
    assert head_ids == ids[:3]

    # Page 2: cursor on the last id of page 1 → next three strictly older.
    page2 = await client.get(
        f"/api/v1/admin/audit?limit=3&action=test.seeded&before={head_ids[-1]}",
        headers=admin,
    )
    assert page2.status_code == 200
    page2_ids = [e["id"] for e in page2.json()]
    assert page2_ids == ids[3:6]
    # The cursor anchor itself must NOT reappear.
    assert head_ids[-1] not in page2_ids


async def test_unknown_before_cursor_returns_unfiltered_page(
    client: AsyncClient, auth_headers, db_session: AsyncSession, make_user
) -> None:
    """An unknown cursor id is treated as "no anchor" — same as if the
    caller omitted it. We don't 404 because the cursor is opaque and a
    deleted-event race shouldn't blow up the pager UI."""
    admin = await auth_headers(role=Role.admin)
    actor = await make_user()
    await _seed_events(db_session, actor_id=actor.id, n=3)

    r = await client.get(
        "/api/v1/admin/audit?limit=10&action=test.seeded&before=ghost-id",
        headers=admin,
    )
    assert r.status_code == 200
    assert len(r.json()) == 3


async def test_audit_requires_admin(
    client: AsyncClient, auth_headers
) -> None:
    """Sanity: the cursor work didn't accidentally relax the admin gate."""
    instructor = await auth_headers(role=Role.instructor)
    r = await client.get("/api/v1/admin/audit", headers=instructor)
    assert r.status_code == 403


async def test_response_shape_unchanged(
    client: AsyncClient, auth_headers, db_session: AsyncSession, make_user
) -> None:
    """The `?before` query param was added without changing the
    response shape, so the existing frontend call (no `before`) keeps
    working with no breaking client change. Lock that in."""
    admin = await auth_headers(role=Role.admin)
    actor = await make_user()
    await _seed_events(db_session, actor_id=actor.id, n=2)

    r = await client.get("/api/v1/admin/audit", headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    # And each item has the documented event shape.
    assert all({"id", "actor_id", "action", "created_at", "data"} <= set(e.keys()) for e in body)
