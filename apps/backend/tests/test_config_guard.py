"""Settings refuses to advertise itself as production-ready with dev defaults."""

from __future__ import annotations

import pytest

from app.core.config import Environment, Settings


def _settings(**overrides):
    base = {
        "env": Environment.production,
        "secret_key": "change-me",
        "jwt_secret": "change-me",
        "s3_secret_access_key": "lumen-secret",
        "cors_origins": ["https://lumen.example.com"],
    }
    base.update(overrides)
    return Settings(**base)


def test_production_with_default_jwt_is_rejected() -> None:
    s = _settings()
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        s.assert_production_ready()


def test_production_with_default_secret_is_rejected() -> None:
    s = _settings(jwt_secret="real-secret-value", secret_key="change-me")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        s.assert_production_ready()


def test_production_with_localhost_cors_is_rejected() -> None:
    s = _settings(
        jwt_secret="real-jwt-secret",
        secret_key="real-app-secret",
        s3_secret_access_key="real-s3-secret",
        cors_origins=["http://localhost:3000"],
    )
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        s.assert_production_ready()


def test_production_with_real_values_passes() -> None:
    s = _settings(
        jwt_secret="real-jwt-secret",
        secret_key="real-app-secret",
        s3_secret_access_key="real-s3-secret",
        cors_origins=["https://lumen.example.com"],
        # A web_base_url guard rejects the localhost default in
        # production; provide a real one so the test reaches the
        # green path.
        web_base_url="https://lumen.example.com",
        # Phase E5 added a parallel guard for the OB3 issuer URL —
        # localhost in production would make issued credentials
        # unverifiable externally. Provide a real one.
        badges_issuer_url="https://lumen.example.com",
    )
    # Should not raise.
    s.assert_production_ready()


def test_non_production_skips_check() -> None:
    s = Settings(env=Environment.development)  # uses dev defaults
    s.assert_production_ready()  # no-op outside production
