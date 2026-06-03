"""S5.9 — credential CRUD + validate API (/me/llm-credentials).

DB-backed (runs at make test.api). Covers: masked reads (no key material),
byok.base_url_forbidden on URL fields, model/provider allowlist, idempotency,
patch toggles + ≤1 active, soft-delete, validate anti-oracle caps (R-S4),
redacted probe, capability gate, /me/export exclusion, anon → 401.

The validate probe is stubbed so no network call is made; the redaction
assertion feeds a fake provider raising an error with a vendor request-id and
confirms it never reaches the client.
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.models.user import Role
from app.services import llm_credentials as svc
from app.services.llm import ChatResponse


@pytest.fixture(autouse=True)
def _byok_on(monkeypatch):
    monkeypatch.setenv("FEATURE_BYOK_ENABLED", "true")
    monkeypatch.setenv("BYOK_ALLOW_DERIVED_KEK", "true")  # dev: allow store under derived KEK
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def _stub_validation(monkeypatch):
    """Stub the validate probe so it never hits the network. Returns a
    setter that controls the probe outcome."""

    class _FakeProvider:
        def __init__(self, *, behavior):
            self.behavior = behavior

        async def chat_with_usage(self, messages, temperature=0.0):
            if self.behavior == "ok":
                return ChatResponse(text="ok", prompt_tokens=1, completion_tokens=1, model="m")
            if self.behavior == "auth":
                # SDK-shaped: openai/anthropic raise AuthenticationError on
                # 401 and the service classifies by exception type name.
                class AuthenticationError(Exception):
                    pass

                raise AuthenticationError("x-request-id=req_LEAKME_123 bad key")
            raise RuntimeError("TimeoutError")

    state = {"behavior": "ok"}

    def _fake_build(spec, *, api_key, model):
        return _FakeProvider(behavior=state["behavior"])

    monkeypatch.setattr(svc, "build_provider_from_spec", _fake_build)
    return state


async def _auth(client, make_user, *, role=Role.student):
    import uuid

    email = f"byok-{uuid.uuid4().hex[:8]}@lumen.test"
    await make_user(email=email, password="Password!1234", role=role)
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": "Password!1234"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.asyncio
async def test_put_then_masked_list(client, make_user, _stub_validation) -> None:
    h = await _auth(client, make_user)
    r = await client.put(
        "/api/v1/me/llm-credentials/openai",
        json={"model": "gpt-4o-mini", "api_key": "sk-SENTINEL-DO-NOT-LEAK-00001234"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["last4"] == "1234"
    assert "api_key" not in body and "enc_blob" not in body and "key_version" not in body

    lst = await client.get("/api/v1/me/llm-credentials", headers=h)
    assert lst.status_code == 200
    [cred] = lst.json()
    assert cred["last4"] == "1234"
    assert "SENTINEL" not in str(cred)
    assert "api_key" not in cred


@pytest.mark.asyncio
async def test_url_field_rejected(client, make_user) -> None:
    h = await _auth(client, make_user)
    for field in ("base_url", "api_base", "host", "url"):
        r = await client.put(
            "/api/v1/me/llm-credentials/openai",
            json={"model": "gpt-4o-mini", "api_key": "sk-xxxxxxxxxxxxxxxxxxxx", field: "https://x"},
            headers=h,
        )
        assert r.status_code == 422, (field, r.text)
        assert r.json()["error"]["code"] == "byok.base_url_forbidden"


@pytest.mark.asyncio
async def test_model_and_provider_allowlist(client, make_user) -> None:
    h = await _auth(client, make_user)
    bad_model = await client.put(
        "/api/v1/me/llm-credentials/openai",
        json={"model": "gpt-NOPE", "api_key": "sk-xxxxxxxxxxxxxxxxxxxx"},
        headers=h,
    )
    assert bad_model.status_code == 422
    assert bad_model.json()["error"]["code"] == "byok.model_not_allowed"

    bad_prov = await client.put(
        "/api/v1/me/llm-credentials/nope",
        json={"model": "gpt-4o-mini", "api_key": "sk-xxxxxxxxxxxxxxxxxxxx"},
        headers=h,
    )
    assert bad_prov.status_code == 422
    assert bad_prov.json()["error"]["code"] == "byok.provider_not_allowed"


@pytest.mark.asyncio
async def test_idempotent_upsert(client, make_user, _stub_validation) -> None:
    h = await _auth(client, make_user)
    payload = {"model": "gpt-4o-mini", "api_key": "sk-SAME-KEY-0000000000001234"}
    await client.put("/api/v1/me/llm-credentials/openai", json=payload, headers=h)
    await client.put("/api/v1/me/llm-credentials/openai", json=payload, headers=h)
    lst = (await client.get("/api/v1/me/llm-credentials", headers=h)).json()
    assert len(lst) == 1


@pytest.mark.asyncio
async def test_patch_active_demotes_prior(client, make_user, _stub_validation) -> None:
    h = await _auth(client, make_user)
    await client.put(
        "/api/v1/me/llm-credentials/openai",
        json={"model": "gpt-4o-mini", "api_key": "sk-aaaaaaaaaaaaaaaaaaaa"},
        headers=h,
    )
    await client.put(
        "/api/v1/me/llm-credentials/groq",
        json={"model": "llama-3.3-70b-versatile", "api_key": "gsk_bbbbbbbbbbbbbbbbbbbb"},
        headers=h,
    )
    await client.patch("/api/v1/me/llm-credentials/openai", json={"is_active": True}, headers=h)
    await client.patch("/api/v1/me/llm-credentials/groq", json={"is_active": True}, headers=h)
    lst = (await client.get("/api/v1/me/llm-credentials", headers=h)).json()
    active = [c for c in lst if c["is_active"]]
    assert len(active) == 1 and active[0]["provider"] == "groq"


@pytest.mark.asyncio
async def test_delete_soft_deletes(client, make_user, _stub_validation) -> None:
    h = await _auth(client, make_user)
    await client.put(
        "/api/v1/me/llm-credentials/openai",
        json={"model": "gpt-4o-mini", "api_key": "sk-aaaaaaaaaaaaaaaaaaaa"},
        headers=h,
    )
    r = await client.delete("/api/v1/me/llm-credentials/openai", headers=h)
    assert r.status_code == 200
    lst = (await client.get("/api/v1/me/llm-credentials", headers=h)).json()
    assert lst == []


@pytest.mark.asyncio
async def test_validate_must_store_first(client, make_user) -> None:
    h = await _auth(client, make_user)
    r = await client.post("/api/v1/me/llm-credentials/openai/validate", headers=h)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "byok.credential_not_found"


@pytest.mark.asyncio
async def test_validate_redacts_vendor_error(client, make_user, _stub_validation) -> None:
    h = await _auth(client, make_user)
    _stub_validation["behavior"] = "ok"  # auto-validate on create succeeds
    await client.put(
        "/api/v1/me/llm-credentials/openai",
        json={"model": "gpt-4o-mini", "api_key": "sk-aaaaaaaaaaaaaaaaaaaa"},
        headers=h,
    )
    _stub_validation["behavior"] = "auth"  # now make the probe fail with a leaky error
    r = await client.post("/api/v1/me/llm-credentials/openai/validate", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "invalid"
    assert "req_LEAKME" not in str(body)
    assert "x-request-id" not in str(body)
    assert "request-id" not in str(body).lower()


@pytest.mark.asyncio
async def test_validate_rate_limited(client, make_user, _stub_validation) -> None:
    h = await _auth(client, make_user)
    await client.put(
        "/api/v1/me/llm-credentials/openai",
        json={"model": "gpt-4o-mini", "api_key": "sk-aaaaaaaaaaaaaaaaaaaa"},
        headers=h,
    )
    # auto-validate on create already counts as 1 toward the ≤5/10min cap.
    # Subsequent manual validations trip once the window count hits 5.
    last = None
    for _ in range(6):
        last = await client.post("/api/v1/me/llm-credentials/openai/validate", headers=h)
    assert last is not None and last.status_code == 429
    assert last.json()["error"]["code"] == "byok.validate_rate_limited"


@pytest.mark.asyncio
async def test_suspended_user_forbidden(client, make_user, db_session, _stub_validation) -> None:
    import uuid

    from app.models.user import User

    email = f"susp-{uuid.uuid4().hex[:8]}@lumen.test"
    user = await make_user(email=email, password="Password!1234")
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": "Password!1234"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    # suspend
    fetched = await db_session.get(User, user.id)
    fetched.is_active = False
    await db_session.commit()
    # A suspended user fails auth (get_current_user drops inactive) → 401.
    resp = await client.put(
        "/api/v1/me/llm-credentials/openai",
        json={"model": "gpt-4o-mini", "api_key": "sk-aaaaaaaaaaaaaaaaaaaa"},
        headers=h,
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_anonymous_unauthorized(client) -> None:
    r = await client.get("/api/v1/me/llm-credentials")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_export_excludes_credentials(client, make_user, _stub_validation) -> None:
    h = await _auth(client, make_user)
    await client.put(
        "/api/v1/me/llm-credentials/openai",
        json={"model": "gpt-4o-mini", "api_key": "sk-SENTINEL-EXPORT-00001234"},
        headers=h,
    )
    exp = await client.get("/api/v1/users/me/export", headers=h)
    assert exp.status_code == 200
    assert "SENTINEL" not in exp.text
    assert "llm_credential" not in exp.text.lower()
    assert "api_key" not in exp.text
