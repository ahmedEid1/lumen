"""Notification management surface — delete, clear, unread-count, mark-unread,
cursor-paged inbox, and the retention prune.

Added in the notifications feature-completeness batch. Design decisions
pinned here (so a future change is deliberate, not drift):

* Hard delete — notifications are ephemeral observability; CLAUDE.md
  reserves soft-delete for Course/Lesson/Review.
* ``security.*`` sub-kind rows ARE deletable — the durable
  ``auth.refresh_reuse`` audit row is the system of record, the bell row
  is a heads-up.
* Clear's default scope is ``read`` — the bulk action can't destroy
  anything actionable unless the caller explicitly opts into ``all``.
* The bare ``GET /me/notifications`` list (newest-50) stays shape-frozen;
  history past 50 is the inbox's job.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationKind
from app.models.user import User


async def _login(client: AsyncClient, user: User) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "Password!1234"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _seed_rows(
    db: AsyncSession,
    *,
    user_id: str,
    n: int,
    kind: str = NotificationKind.enrolled,
    read: bool = False,
    created_at: datetime | None = None,
) -> list[Notification]:
    """Direct model inserts — bypasses the dispatch-aware repo.create so
    tests control read/created state exactly (and can plant open sub-kinds
    without coupling to prefs resolution)."""
    rows = []
    for i in range(n):
        row = Notification(
            user_id=user_id,
            kind=kind,  # type: ignore[arg-type]
            title=f"Seeded {i}",
            body="",
            data={},
            read_at=datetime.now(UTC) if read else None,
        )
        if created_at is not None:
            row.created_at = created_at
        db.add(row)
        rows.append(row)
    await db.commit()
    return rows


# ---------------------------------------------------------------- delete one


async def test_delete_own_notification(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    me = await make_user(email=f"del-{uuid.uuid4().hex[:6]}@lumen.test")
    rows = await _seed_rows(db_session, user_id=me.id, n=2)
    h = await _login(client, me)

    r = await client.delete(f"/api/v1/me/notifications/{rows[0].id}", headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    remaining = await client.get("/api/v1/me/notifications", headers=h)
    ids = [n["id"] for n in remaining.json()]
    assert rows[0].id not in ids and rows[1].id in ids

    # Deleting an unread row moves the badge count.
    count = await client.get("/api/v1/me/notifications/unread-count", headers=h)
    assert count.json() == {"unread_count": 1}


async def test_delete_missing_or_foreign_is_404(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    owner = await make_user(email=f"own-{uuid.uuid4().hex[:6]}@lumen.test")
    intruder = await make_user(email=f"intr-{uuid.uuid4().hex[:6]}@lumen.test")
    (row,) = await _seed_rows(db_session, user_id=owner.id, n=1)
    h = await _login(client, intruder)

    # Foreign id and a made-up id are indistinguishable: 404, never 403.
    foreign = await client.delete(f"/api/v1/me/notifications/{row.id}", headers=h)
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "notification.not_found"
    missing = await client.delete("/api/v1/me/notifications/nope-not-a-real-id", headers=h)
    assert missing.status_code == 404

    # The owner's row survived the intruder's attempt.
    still = await db_session.get(Notification, row.id)
    assert still is not None


async def test_security_subkind_rows_are_deletable(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    """Pinned per the C7 spec decision: the durable auth.refresh_reuse audit
    row is the system of record, so the in-app alarm row has no delete
    protection. If this ever changes it must be a deliberate revisit."""
    me = await make_user(email=f"sec-{uuid.uuid4().hex[:6]}@lumen.test")
    (row,) = await _seed_rows(db_session, user_id=me.id, n=1, kind="security.refresh_reuse")
    row_id = row.id  # snapshot before expire_all — expired attrs sync-load
    h = await _login(client, me)

    r = await client.delete(f"/api/v1/me/notifications/{row_id}", headers=h)
    assert r.status_code == 200
    db_session.expire_all()
    gone = (
        await db_session.execute(select(Notification).where(Notification.id == row_id))
    ).scalar_one_or_none()
    assert gone is None


# ---------------------------------------------------------------- bulk clear


async def test_clear_read_scope_leaves_unread_and_other_users(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    me = await make_user(email=f"clr-{uuid.uuid4().hex[:6]}@lumen.test")
    other = await make_user(email=f"oth-{uuid.uuid4().hex[:6]}@lumen.test")
    await _seed_rows(db_session, user_id=me.id, n=2, read=True)
    keep = await _seed_rows(db_session, user_id=me.id, n=1, read=False)
    await _seed_rows(db_session, user_id=other.id, n=2, read=True)
    h = await _login(client, me)

    r = await client.post("/api/v1/me/notifications/clear", json={"scope": "read"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "deleted": 2}

    mine = (await client.get("/api/v1/me/notifications", headers=h)).json()
    assert [n["id"] for n in mine] == [keep[0].id]

    others = (
        (await db_session.execute(select(Notification).where(Notification.user_id == other.id)))
        .scalars()
        .all()
    )
    assert len(others) == 2  # untouched


async def test_clear_default_scope_is_read(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    me = await make_user(email=f"clrd-{uuid.uuid4().hex[:6]}@lumen.test")
    await _seed_rows(db_session, user_id=me.id, n=1, read=True)
    await _seed_rows(db_session, user_id=me.id, n=1, read=False)
    h = await _login(client, me)

    r = await client.post("/api/v1/me/notifications/clear", json={}, headers=h)
    assert r.status_code == 200
    assert r.json()["deleted"] == 1  # only the read row

    count = await client.get("/api/v1/me/notifications/unread-count", headers=h)
    assert count.json()["unread_count"] == 1


async def test_clear_accepts_bare_post_without_body(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    """Codex review P2: a required body model made the documented default
    scope unreachable (FastAPI 422'd a body-less POST before field defaults
    could apply). A bare POST must behave as scope='read'."""
    me = await make_user(email=f"clrb-{uuid.uuid4().hex[:6]}@lumen.test")
    await _seed_rows(db_session, user_id=me.id, n=1, read=True)
    await _seed_rows(db_session, user_id=me.id, n=1, read=False)
    h = await _login(client, me)

    r = await client.post("/api/v1/me/notifications/clear", headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "deleted": 1}


async def test_clear_all_scope_empties_and_is_idempotent(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    me = await make_user(email=f"clra-{uuid.uuid4().hex[:6]}@lumen.test")
    await _seed_rows(db_session, user_id=me.id, n=2, read=True)
    await _seed_rows(db_session, user_id=me.id, n=3, read=False)
    h = await _login(client, me)

    r = await client.post("/api/v1/me/notifications/clear", json={"scope": "all"}, headers=h)
    assert r.json() == {"ok": True, "deleted": 5}
    assert (await client.get("/api/v1/me/notifications", headers=h)).json() == []

    again = await client.post("/api/v1/me/notifications/clear", json={"scope": "all"}, headers=h)
    assert again.json() == {"ok": True, "deleted": 0}


# ------------------------------------------------------------- unread count


async def test_unread_count_accurate_past_bare_list_cap(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    """The whole point of the endpoint: the bare list caps at 50, so a badge
    derived from it under-counts. The COUNT must not."""
    me = await make_user(email=f"cnt-{uuid.uuid4().hex[:6]}@lumen.test")
    rows = await _seed_rows(db_session, user_id=me.id, n=55)
    h = await _login(client, me)

    bare = (await client.get("/api/v1/me/notifications", headers=h)).json()
    assert len(bare) == 50  # cap unchanged

    count = (await client.get("/api/v1/me/notifications/unread-count", headers=h)).json()
    assert count == {"unread_count": 55}

    await client.post(f"/api/v1/me/notifications/{rows[0].id}/read", headers=h)
    count = (await client.get("/api/v1/me/notifications/unread-count", headers=h)).json()
    assert count == {"unread_count": 54}


async def test_unread_count_excludes_other_users(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    me = await make_user(email=f"cntx-{uuid.uuid4().hex[:6]}@lumen.test")
    other = await make_user(email=f"cnty-{uuid.uuid4().hex[:6]}@lumen.test")
    await _seed_rows(db_session, user_id=me.id, n=2)
    await _seed_rows(db_session, user_id=other.id, n=7)
    h = await _login(client, me)

    count = (await client.get("/api/v1/me/notifications/unread-count", headers=h)).json()
    assert count == {"unread_count": 2}


# -------------------------------------------------------------- mark unread


async def test_mark_unread_round_trip_and_digested_at_untouched(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    me = await make_user(email=f"unr-{uuid.uuid4().hex[:6]}@lumen.test")
    (row,) = await _seed_rows(db_session, user_id=me.id, n=1)
    row_id = row.id  # snapshot before expire_all — expired attrs sync-load
    # Simulate "already emailed by the digest" — un-reading must NOT re-arm
    # digest delivery (the worker bundles on digested_at IS NULL).
    stamped = datetime.now(UTC)
    row.digested_at = stamped
    await db_session.commit()
    h = await _login(client, me)

    assert (
        await client.post(f"/api/v1/me/notifications/{row_id}/read", headers=h)
    ).status_code == 200
    count = (await client.get("/api/v1/me/notifications/unread-count", headers=h)).json()
    assert count["unread_count"] == 0

    assert (
        await client.post(f"/api/v1/me/notifications/{row_id}/unread", headers=h)
    ).status_code == 200
    count = (await client.get("/api/v1/me/notifications/unread-count", headers=h)).json()
    assert count["unread_count"] == 1

    # Idempotent when already unread.
    assert (
        await client.post(f"/api/v1/me/notifications/{row_id}/unread", headers=h)
    ).status_code == 200

    db_session.expire_all()
    fresh = (
        await db_session.execute(select(Notification).where(Notification.id == row_id))
    ).scalar_one()
    assert fresh.read_at is None
    assert fresh.digested_at == stamped


async def test_mark_unread_foreign_is_404(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    owner = await make_user(email=f"unro-{uuid.uuid4().hex[:6]}@lumen.test")
    intruder = await make_user(email=f"unri-{uuid.uuid4().hex[:6]}@lumen.test")
    (row,) = await _seed_rows(db_session, user_id=owner.id, n=1)
    h = await _login(client, intruder)

    r = await client.post(f"/api/v1/me/notifications/{row.id}/unread", headers=h)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "notification.not_found"


# ------------------------------------------------------------- inbox paging


async def test_inbox_cursor_walk_covers_all_rows_no_gaps_no_dupes(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    """55 rows seeded in one transaction share a created_at instant — the id
    tiebreaker must still page deterministically: 20+20+15, union == all."""
    me = await make_user(email=f"inb-{uuid.uuid4().hex[:6]}@lumen.test")
    rows = await _seed_rows(db_session, user_id=me.id, n=55)
    h = await _login(client, me)

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        url = "/api/v1/me/notifications/inbox?limit=20"
        if cursor:
            url += f"&cursor={cursor}"
        page = (await client.get(url, headers=h)).json()
        seen.extend(item["id"] for item in page["items"])
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break
        assert pages < 10, "cursor failed to terminate"

    assert pages == 3
    assert len(seen) == 55 == len(set(seen))  # no dupes, no gaps
    assert set(seen) == {r.id for r in rows}


async def test_inbox_unread_filter(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    me = await make_user(email=f"inbf-{uuid.uuid4().hex[:6]}@lumen.test")
    await _seed_rows(db_session, user_id=me.id, n=2, read=True)
    unread = await _seed_rows(db_session, user_id=me.id, n=3, read=False)
    h = await _login(client, me)

    page = (await client.get("/api/v1/me/notifications/inbox?unread=true", headers=h)).json()
    assert {i["id"] for i in page["items"]} == {r.id for r in unread}
    assert all(i["read_at"] is None for i in page["items"])


async def test_inbox_foreign_cursor_degrades_to_first_page(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    """A cursor pointing at another user's row must not act as an anchor
    (no cross-user keyset oracle) — it degrades to the first page."""
    me = await make_user(email=f"inbc-{uuid.uuid4().hex[:6]}@lumen.test")
    other = await make_user(email=f"inbo-{uuid.uuid4().hex[:6]}@lumen.test")
    mine = await _seed_rows(db_session, user_id=me.id, n=3)
    (theirs,) = await _seed_rows(db_session, user_id=other.id, n=1)
    h = await _login(client, me)

    page = (
        await client.get(f"/api/v1/me/notifications/inbox?cursor={theirs.id}", headers=h)
    ).json()
    assert {i["id"] for i in page["items"]} == {r.id for r in mine}


# ------------------------------------------------ read-all contract freeze


async def test_read_all_wire_payload_unchanged_after_schema_rename(
    client: AsyncClient, auth_headers
) -> None:
    """`response_model` moved from dict to MarkAllReadResult — the JSON keys
    must be byte-identical so old consumers keep working."""
    h = await auth_headers()
    r = await client.post("/api/v1/me/notifications/read-all", headers=h)
    assert r.status_code == 200
    assert set(r.json().keys()) == {"ok", "marked_read"}


# ------------------------------------------------------------ retention prune


async def test_prune_deletes_only_old_read_rows(make_user, db_session: AsyncSession) -> None:
    from app.workers.tasks.notifications_prune import prune_notifications_async

    me = await make_user(email=f"prn-{uuid.uuid4().hex[:6]}@lumen.test")
    old = datetime.now(UTC) - timedelta(days=120)
    pruned_rows = await _seed_rows(db_session, user_id=me.id, n=2, read=True, created_at=old)
    kept_recent_read = await _seed_rows(db_session, user_id=me.id, n=1, read=True)
    kept_old_unread = await _seed_rows(db_session, user_id=me.id, n=1, read=False, created_at=old)
    # Snapshot ids before expire_all — expired attrs sync-load (MissingGreenlet).
    me_id = me.id
    pruned_ids = {r.id for r in pruned_rows}
    kept_ids = {kept_recent_read[0].id, kept_old_unread[0].id}

    pruned = await prune_notifications_async()
    assert pruned == 2

    db_session.expire_all()
    remaining = (
        (await db_session.execute(select(Notification).where(Notification.user_id == me_id)))
        .scalars()
        .all()
    )
    remaining_ids = {r.id for r in remaining}
    assert remaining_ids == kept_ids
    assert not remaining_ids & pruned_ids
