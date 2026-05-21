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
        f"/api/v1/admin/subjects/{sub_id}", json={"title": "DevOps", "slug": "dev-ops"}, headers=admin
    )
    assert upd.status_code == 200
    assert upd.json()["slug"] == "dev-ops"

    deleted = await client.delete(f"/api/v1/admin/subjects/{sub_id}", headers=admin)
    assert deleted.status_code == 200


async def test_admin_can_promote_users(client: AsyncClient, auth_headers, make_user) -> None:
    admin = await auth_headers(role=Role.admin)
    student = await make_user(email="promote@lumen.test", password="Password!1234")

    promote = await client.patch(
        f"/api/v1/admin/users/{student.id}/role", json={"role": "instructor"}, headers=admin
    )
    assert promote.status_code == 200
    assert promote.json()["role"] == "instructor"


async def test_admin_cannot_self_demote(client: AsyncClient, auth_headers, db_session) -> None:
    admin = await auth_headers(role=Role.admin)
    # Pull the admin's id from /auth/me
    me = await client.get("/api/v1/auth/me", headers=admin)
    aid = me.json()["id"]
    r = await client.patch(
        f"/api/v1/admin/users/{aid}/role", json={"role": "student"}, headers=admin
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "user.self_demote"


async def test_audit_log_lists(client: AsyncClient, auth_headers) -> None:
    admin = await auth_headers(role=Role.admin)
    r = await client.get("/api/v1/admin/audit", headers=admin)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
