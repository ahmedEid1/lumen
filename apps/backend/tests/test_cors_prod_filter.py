"""H6 — CORS lockdown in production.

The CORS allow-list comes from ``CORS_ORIGINS`` env. Outside
production it's used as-is so the test suite's ``http://testserver``
and the docker-compose ``http://web:3000`` keep working. In
production ``_filter_prod_cors_origins`` strips:

* ``localhost`` / ``127.0.0.1`` / ``0.0.0.0`` / ``::1`` (any port, any scheme)
* the reserved ``.test`` TLD (RFC 2606)

If the filtered list ends up empty in production, ``create_app``
refuses to boot. The filter itself is pure so we test it directly;
the fail-boot path runs against the app factory with monkeypatched
settings.
"""

from __future__ import annotations

import pytest

from app.main import _filter_prod_cors_origins

# ---------- Filter behaviour ----------


def test_filter_passes_through_outside_prod() -> None:
    origins = [
        "http://localhost:3000",
        "http://web:3000",
        "http://testserver",
        "https://example.test",
        "https://lumen.example.com",
    ]
    assert _filter_prod_cors_origins(origins, is_prod=False) == origins


def test_filter_strips_localhost_in_prod() -> None:
    out = _filter_prod_cors_origins(
        ["http://localhost:3000", "https://lumen.example.com"],
        is_prod=True,
    )
    assert out == ["https://lumen.example.com"]


def test_filter_strips_loopback_ip_in_prod() -> None:
    out = _filter_prod_cors_origins(
        [
            "http://127.0.0.1",
            "http://127.0.0.1:3000",
            "https://lumen.example.com",
        ],
        is_prod=True,
    )
    assert out == ["https://lumen.example.com"]


def test_filter_strips_ipv6_loopback_in_prod() -> None:
    out = _filter_prod_cors_origins(
        ["http://[::1]:3000", "https://lumen.example.com"],
        is_prod=True,
    )
    assert out == ["https://lumen.example.com"]


def test_filter_strips_zero_bind_address_in_prod() -> None:
    out = _filter_prod_cors_origins(
        ["http://0.0.0.0", "https://lumen.example.com"],
        is_prod=True,
    )
    assert out == ["https://lumen.example.com"]


def test_filter_strips_test_tld_in_prod() -> None:
    out = _filter_prod_cors_origins(
        ["https://api.lumen.test", "https://lumen.example.com"],
        is_prod=True,
    )
    assert out == ["https://lumen.example.com"]


def test_filter_keeps_real_origins_in_prod() -> None:
    """Real public origins pass through untouched in production."""
    origins = [
        "https://lumen.example.com",
        "https://app.example.com",
        "https://www.example.org",
    ]
    assert _filter_prod_cors_origins(origins, is_prod=True) == origins


def test_filter_handles_trailing_slash() -> None:
    """Trailing slashes are stripped — CORSMiddleware compares without them."""
    out = _filter_prod_cors_origins(
        ["https://lumen.example.com/"],
        is_prod=True,
    )
    assert out == ["https://lumen.example.com"]


def test_filter_handles_empty_input() -> None:
    assert _filter_prod_cors_origins([], is_prod=True) == []
    assert _filter_prod_cors_origins([""], is_prod=True) == []
    assert _filter_prod_cors_origins(["   "], is_prod=True) == []


def test_filter_does_not_match_test_in_path() -> None:
    """A real prod domain whose path contains 'test' must not get stripped."""
    out = _filter_prod_cors_origins(
        ["https://lumen.example.com/test"],
        is_prod=True,
    )
    # Path is preserved; what matters is the host didn't end in ``.test``.
    assert any("lumen.example.com" in o for o in out)


def test_filter_does_not_mutate_input() -> None:
    origins = ["http://localhost:3000", "https://lumen.example.com"]
    snapshot = list(origins)
    _filter_prod_cors_origins(origins, is_prod=True)
    assert origins == snapshot


# ---------- Empty-list fail-boot ----------


def test_app_boot_fails_when_prod_cors_filters_to_empty(monkeypatch) -> None:
    """create_app raises RuntimeError if every CORS origin is stripped in prod."""
    from app.core.config import Environment, Settings, get_settings
    from app.main import create_app

    # Build a Settings shaped like a real production environment so the
    # subsequent prod_guards calls don't trip on something unrelated.
    # The fixture conftest already sets long SECRET_KEY / JWT_SECRET via
    # ``os.environ`` so the secret-strength guard passes; we just need
    # to flip ``env`` and ``cors_origins`` for the duration of this test.
    monkeypatch.setenv("ENV", "production")
    # Every entry is a loopback / .test origin — the filter empties the list.
    monkeypatch.setenv(
        "CORS_ORIGINS",
        '["http://localhost:3000","http://127.0.0.1","https://lumen.test"]',
    )
    # Other prod-guard inputs need real-looking values so the boot
    # reaches the CORS-empty check rather than failing earlier.
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db-prod.example.com:5432/lumen")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("WEB_BASE_URL", "https://lumen.example.com")
    monkeypatch.setenv("BADGES_ISSUER_URL", "https://lumen.example.com")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "real-secret-please")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    try:
        # ``settings`` is captured at module import in main.py, so we
        # also need to patch the module-level reference.
        import app.main as main_mod

        new_settings = Settings()
        assert new_settings.env == Environment.production
        monkeypatch.setattr(main_mod, "settings", new_settings)
        with pytest.raises(RuntimeError, match="Production CORS_ORIGINS"):
            create_app()
    finally:
        # Bring the cached settings back to test defaults so later
        # tests in the session don't see the prod values.
        get_settings.cache_clear()  # type: ignore[attr-defined]


def test_app_boots_when_prod_cors_has_real_origin(monkeypatch) -> None:
    """A single real origin alongside loopback entries survives the filter."""
    from app.core.config import Settings, get_settings
    from app.main import create_app

    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv(
        "CORS_ORIGINS",
        '["http://localhost:3000","https://lumen.example.com"]',
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db-prod.example.com:5432/lumen")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("WEB_BASE_URL", "https://lumen.example.com")
    monkeypatch.setenv("BADGES_ISSUER_URL", "https://lumen.example.com")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "real-secret-please")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    try:
        import app.main as main_mod

        new_settings = Settings()
        monkeypatch.setattr(main_mod, "settings", new_settings)
        # No raise — the real origin survived the filter.
        app = create_app()
        assert app is not None
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]
