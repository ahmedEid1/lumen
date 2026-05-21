"""Admin search reindex action."""

from __future__ import annotations

from httpx import AsyncClient

from app.models.user import Role


async def test_reindex_requires_admin(client: AsyncClient, auth_headers) -> None:
    student = await auth_headers(role=Role.student)
    r = await client.post("/api/v1/admin/search/reindex", headers=student)
    assert r.status_code == 403


async def test_reindex_writes_audit_row(client: AsyncClient, auth_headers) -> None:
    admin = await auth_headers(role=Role.admin)
    r = await client.post("/api/v1/admin/search/reindex", headers=admin)
    assert r.status_code == 202

    audit = await client.get("/api/v1/admin/audit?action=admin.search.reindex", headers=admin)
    assert audit.status_code == 200
    assert any(e["action"] == "admin.search.reindex" for e in audit.json())
