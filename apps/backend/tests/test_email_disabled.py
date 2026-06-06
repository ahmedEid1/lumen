"""Graceful degradation when no email provider is configured (P2 backlog).

Prod ships without an SMTP host, so every ``send_email`` raised
``socket.gaierror`` deep in ``smtplib`` and the Celery task burned all
5 autoretries — 7 tracebacks per registration (two-role-rebuild/BACKLOG.md).

The fix gates outbound mail at the *service* level on ``Settings.email_enabled``:
when ``False`` we log one ``email_disabled_skipped`` line and return BEFORE any
SMTP connection, so the task succeeds instead of retry-crashing. This covers
every sender (verify-email, password-reset, digest) without touching enqueue
sites. The enabled path stays byte-identical (still attempts SMTP).
"""

from __future__ import annotations

import smtplib

import app.services.email as email_module
from app.core.config import Environment, Settings


def _settings(*, email_enabled: bool) -> Settings:
    return Settings(env=Environment.test, email_enabled=email_enabled, jwt_secret="test-secret")


def test_disabled_skips_smtp_and_logs(monkeypatch, capsys) -> None:
    """email_enabled=False → no smtplib call, one structured info line, no raise."""
    monkeypatch.setattr(email_module, "get_settings", lambda: _settings(email_enabled=False))

    # Spy on the SMTP constructor: it must NEVER be touched on the disabled path.
    calls: list[tuple] = []

    def _boom(*args, **kwargs):  # pragma: no cover - asserted not-called
        calls.append((args, kwargs))
        raise AssertionError("smtplib.SMTP must not be constructed when email is disabled")

    monkeypatch.setattr(smtplib, "SMTP", _boom)

    # Returns cleanly (no exception, no retry trigger).
    result = email_module.send_email(to="x@lumen.test", subject="Verify your email", text="hello")

    assert result is None
    assert calls == [], "SMTP was constructed on the disabled path"
    # structlog renders one JSON line to stdout; pin the event + its fields.
    out = capsys.readouterr().out
    skip_lines = [ln for ln in out.splitlines() if "email_disabled_skipped" in ln]
    assert len(skip_lines) == 1
    line = skip_lines[0]
    assert "x@lumen.test" in line
    assert "Verify your email" in line


def test_task_succeeds_on_disabled_path(monkeypatch) -> None:
    """The Celery task body returns success (no exception → no autoretry)."""
    monkeypatch.setattr(email_module, "get_settings", lambda: _settings(email_enabled=False))

    def _boom(*args, **kwargs):  # pragma: no cover - asserted not-called
        raise AssertionError("SMTP must not be constructed when email is disabled")

    monkeypatch.setattr(smtplib, "SMTP", _boom)

    from app.workers.tasks.email import send

    # Call the undecorated task body directly — Celery's autoretry only fires
    # on an exception, so a clean return == success.
    assert send.run(to="y@lumen.test", subject="Reset password", text="reset") is None


def test_enabled_path_still_attempts_smtp(monkeypatch) -> None:
    """email_enabled=True → smtplib.SMTP is constructed (enabled path unchanged)."""
    monkeypatch.setattr(email_module, "get_settings", lambda: _settings(email_enabled=True))

    constructed: list[tuple] = []

    class _FakeSMTP:
        def __init__(self, host, port, timeout=None):
            constructed.append((host, port))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, context=None):
            pass

        def login(self, *a, **k):  # pragma: no cover - no username in default settings
            pass

        def send_message(self, msg):
            pass

    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    email_module.send_email(to="z@lumen.test", subject="Hi", text="body")

    assert constructed, "enabled path must attempt an SMTP connection"
