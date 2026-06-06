"""Admin endpoints: subjects, tags, users, audit."""

from __future__ import annotations

from httpx import AsyncClient

from app.models.user import Role


async def test_admin_required_for_admin_endpoints(client: AsyncClient, auth_headers) -> None:
    student = await auth_headers(role=Role.student)
    r = await client.post("/api/v1/admin/subjects", json={"title": "x"}, headers=student)
    assert r.status_code == 403


async def test_admin_can_crud_subjects(client: AsyncClient, auth_headers) -> None:
    admin = await auth_headers(role=Role.admin)
    create = await client.post("/api/v1/admin/subjects", json={"title": "DevOps"}, headers=admin)
    assert create.status_code == 201
    sub_id = create.json()["id"]
    assert create.json()["slug"] == "devops"

    dup = await client.post("/api/v1/admin/subjects", json={"title": "DevOps"}, headers=admin)
    assert dup.status_code == 409

    upd = await client.patch(
        f"/api/v1/admin/subjects/{sub_id}",
        json={"title": "DevOps", "slug": "dev-ops"},
        headers=admin,
    )
    assert upd.status_code == 200
    assert upd.json()["slug"] == "dev-ops"

    deleted = await client.delete(f"/api/v1/admin/subjects/{sub_id}", headers=admin)
    assert deleted.status_code == 200


async def test_admin_can_promote_users(client: AsyncClient, auth_headers, make_user) -> None:
    # S1.8: the only promotable role is `admin` (the two-role model).
    admin = await auth_headers(role=Role.admin)
    user = await make_user(email="promote@lumen.test", password="Password!1234")

    promote = await client.patch(
        f"/api/v1/admin/users/{user.id}/role", json={"role": "admin"}, headers=admin
    )
    assert promote.status_code == 200
    assert promote.json()["role"] == "admin"


async def test_admin_can_demote_admin_to_user(client: AsyncClient, auth_headers, make_user) -> None:
    # S1.8: an admin can revoke another admin back to `user`.
    admin = await auth_headers(role=Role.admin)
    other = await make_user(email="demote@lumen.test", role=Role.admin)
    r = await client.patch(
        f"/api/v1/admin/users/{other.id}/role", json={"role": "user"}, headers=admin
    )
    assert r.status_code == 200
    assert r.json()["role"] == "user"


async def test_set_user_role_normalizes_legacy_values(
    client: AsyncClient, auth_headers, make_user
) -> None:
    # S6.6 / FR-ADMIN-02: during the migration window a legacy
    # `student`/`instructor` write is NORMALIZED to `user` (not rejected) so
    # old clients don't 422 mid-rollout. The post-Phase-D 422 path is gated by
    # `strict_legacy_role_rejection` (see test_admin_grant_revoke.py).
    admin = await auth_headers(role=Role.admin)
    target = await make_user(email="legacy-write@lumen.test")
    for legacy in ("student", "instructor"):
        r = await client.patch(
            f"/api/v1/admin/users/{target.id}/role", json={"role": legacy}, headers=admin
        )
        assert r.status_code == 200, f"{legacy} should normalize to user"
        assert r.json()["role"] == "user"
    ok = await client.patch(
        f"/api/v1/admin/users/{target.id}/role", json={"role": "user"}, headers=admin
    )
    assert ok.status_code == 200
    assert ok.json()["role"] == "user"


async def test_admin_cannot_self_demote(client: AsyncClient, auth_headers, db_session) -> None:
    admin = await auth_headers(role=Role.admin)
    # Pull the admin's id from /auth/me
    me = await client.get("/api/v1/auth/me", headers=admin)
    aid = me.json()["id"]
    # S6.6: self-demote of the last active admin trips the authoritative
    # last-admin invariant (which subsumes the old self-demote guard).
    r = await client.patch(f"/api/v1/admin/users/{aid}/role", json={"role": "user"}, headers=admin)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "user.last_admin"


async def test_audit_log_lists(client: AsyncClient, auth_headers) -> None:
    admin = await auth_headers(role=Role.admin)
    r = await client.get("/api/v1/admin/audit", headers=admin)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_list_users_returns_paginated_envelope(
    client: AsyncClient, auth_headers, make_user
) -> None:
    """W11 F6: `/admin/users` returns the offset+page envelope and honors
    `page`/`page_size` — not a bare array, not an ignored page size."""
    admin = await auth_headers(role=Role.admin)
    # Seed enough users to force a second page (admin acct + N more > page_size).
    for i in range(6):
        await make_user(email=f"pager-{i}@lumen.test", full_name=f"Pager {i}")

    r1 = await client.get("/api/v1/admin/users?page=1&page_size=5", headers=admin)
    assert r1.status_code == 200
    body = r1.json()
    # Envelope shape (mirrors frontend `Page<UserAdminOut>` + endpoints.ts).
    assert set(body) >= {"items", "total", "page", "page_size"}
    assert body["page"] == 1
    assert body["page_size"] == 5
    assert len(body["items"]) == 5  # page_size is RESPECTED (the F6 bug ignored it)
    assert body["total"] >= 7  # admin + 6 seeded
    # Each item carries the documented UserAdminOut fields (no empty rows).
    first = body["items"][0]
    assert set(first) >= {"id", "email", "full_name", "role", "is_active", "last_login_at"}

    # Page 2 returns the remaining users and no overlap with page 1.
    r2 = await client.get("/api/v1/admin/users?page=2&page_size=5", headers=admin)
    assert r2.status_code == 200
    page2 = r2.json()
    assert page2["page"] == 2
    ids1 = {u["id"] for u in body["items"]}
    ids2 = {u["id"] for u in page2["items"]}
    assert ids1.isdisjoint(ids2)


async def test_list_users_q_filters_and_counts(
    client: AsyncClient, auth_headers, make_user
) -> None:
    """`q` filters email/full_name and `total` reflects the filtered count."""
    admin = await auth_headers(role=Role.admin)
    await make_user(email="needle@lumen.test", full_name="Findme Person")
    await make_user(email="other@lumen.test", full_name="Someone Else")

    r = await client.get("/api/v1/admin/users?q=needle&page=1&page_size=50", headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["email"] == "needle@lumen.test"
