"""Regression: transactional email links point at the web frontend.

Before iteration 37 both ``/auth/password-reset/request`` and
``email_verify.queue_verification_email`` built their links with
``settings.api_base_url`` — the FastAPI host (port 8000 dev, often
``api.example.com`` prod) — but the actual reset/verify pages are
Next.js routes that only exist on the user-facing web host
(port 3000 dev, ``example.com`` prod). So a user who clicked the link
in their inbox landed on a 404 from the API.

We added ``web_base_url`` to settings and routed both link builders
through it. The production-readiness guard refuses to boot if it's
still the localhost default, mirroring the existing guard for
``cors_origins``.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.config import Environment, Settings


def _patched_settings(**overrides):
    """Build a Settings with required prod secrets so we can exercise
    just the URL-related guards without hitting the secret-default ones."""
    base = {
        "env": Environment.production,
        "secret_key": "real-secret-1234567890",
        "jwt_secret": "real-jwt-1234567890",
        "s3_secret_access_key": "real-s3-secret",
        "cors_origins": ["https://lumen.example"],
        "web_base_url": "https://lumen.example",
        # Phase E5 added a localhost guard for the OB3 issuer URL.
        "badges_issuer_url": "https://lumen.example",
    }
    base.update(overrides)
    return Settings(**base)


def test_assert_production_ready_rejects_localhost_web_base_url():
    s = _patched_settings(web_base_url="http://localhost:3000")
    with pytest.raises(RuntimeError) as exc:
        s.assert_production_ready()
    assert "WEB_BASE_URL" in str(exc.value)


def test_assert_production_ready_accepts_real_web_base_url():
    s = _patched_settings()
    s.assert_production_ready()  # must not raise


async def test_password_reset_link_uses_web_base_url(
    monkeypatch, client, make_user
):
    from app.core import config as cfg_module

    # Override the global settings cache so the endpoint picks up our test URL.
    test_settings = Settings(
        env=Environment.test,
        web_base_url="https://web.example",
        jwt_secret="test-secret",
    )
    monkeypatch.setattr(cfg_module, "get_settings", lambda: test_settings)
    # The endpoint also imports get_settings into the auth module's namespace.
    from app.api.v1 import auth as auth_module

    monkeypatch.setattr(auth_module, "get_settings", lambda: test_settings)

    captured: dict[str, str] = {}

    class _StubSend:
        # the endpoint now sends `html` too; accept and store it so the stub
        # doesn't raise TypeError and silently get swallowed
        # by the password-reset endpoint's broker-tolerant
        # try/except.
        def delay(self, *, to, subject, text, html=None):  # match Celery sig
            captured["to"] = to
            captured["text"] = text
            captured["html"] = html

    import app.workers.tasks.email as email_module

    monkeypatch.setattr(email_module, "send", _StubSend())

    email = f"reset-{uuid.uuid4().hex[:8]}@lumen.test"
    await make_user(email=email, password="Password!1234")
    r = await client.post("/api/v1/auth/password-reset/request", json={"email": email})
    assert r.status_code == 200
    assert "text" in captured, "send.delay was not called — link not generated"
    assert "https://web.example/reset-password?token=" in captured["text"]
    # Belt-and-suspenders: must NOT contain the API host.
    assert "localhost:8000" not in captured["text"]


async def test_email_verify_link_uses_web_base_url(monkeypatch, make_user):
    from app.core import config as cfg_module

    test_settings = Settings(
        env=Environment.test,
        web_base_url="https://web.example",
        jwt_secret="test-secret",
    )
    monkeypatch.setattr(cfg_module, "get_settings", lambda: test_settings)
    from app.services import email_verify as verify_module

    monkeypatch.setattr(verify_module, "get_settings", lambda: test_settings, raising=False)

    class _BrokenSend:
        def delay(self, *, to, subject, text):
            raise RuntimeError("broker offline — fall through to log/return")

    import app.workers.tasks.email as email_module

    monkeypatch.setattr(email_module, "send", _BrokenSend())

    user = await make_user()
    link = verify_module.queue_verification_email(user=user)
    assert link is not None
    assert link.startswith("https://web.example/verify-email?token=")
