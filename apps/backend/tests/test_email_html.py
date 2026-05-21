"""Branded HTML alongside the plain-text email body.

Iter 83 wraps every transactional email (password reset, verify,
email-change confirm) in a self-contained HTML alternative so it
renders consistently across Gmail / Outlook / Apple Mail. Tests
pin the template structure and the wire-up: the worker stub
receives both ``text`` and ``html`` arguments.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.services.email_template import render_branded_html


# ---------------- pure template ----------------


def test_renders_heading_and_paragraphs() -> None:
    html = render_branded_html(
        heading="Reset your password",
        body_paragraphs=["First para.", "Second para."],
    )
    assert "Reset your password" in html
    assert "First para." in html
    assert "Second para." in html
    # No CTA passed → button section omitted.
    assert "background:#0f172a" not in html


def test_renders_cta_button_and_plain_link() -> None:
    html = render_branded_html(
        heading="Verify",
        body_paragraphs=["Click below."],
        cta_url="https://web.example/verify?token=t1",
        cta_label="Verify email",
    )
    # CTA button is a table-based <a> — most email-client compatible.
    assert "Verify email" in html
    assert 'href="https://web.example/verify?token=t1"' in html
    # The "paste this link" fallback is critical for clients that
    # strip buttons (and for accessibility users on screen readers).
    assert html.count("https://web.example/verify?token=t1") >= 2


def test_escapes_user_supplied_content() -> None:
    html = render_branded_html(
        heading="Hi <script>alert(1)</script>",
        body_paragraphs=["<img src=x onerror=alert(1)>"],
    )
    # Heading and body have to be HTML-escaped — otherwise an attacker
    # who picks a malicious display name could inject script.
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<img" not in html.split("<table")[0]  # no real img in head/header
    assert "&lt;img" in html


# ---------------- wire-up: password reset sends html too ----------------


@pytest.fixture
def _capture_email(monkeypatch):
    """Replace the Celery task's .delay with a sync capture."""
    captured: list[dict] = []

    class _Stub:
        def delay(self, *, to, subject, text, html=None):  # noqa: A002
            captured.append({"to": to, "subject": subject, "text": text, "html": html})

    import app.workers.tasks.email as email_module

    monkeypatch.setattr(email_module, "send", _Stub())
    return captured


async def test_password_reset_request_now_sends_multipart(
    client: AsyncClient, make_user, _capture_email
) -> None:
    email = f"r-{uuid.uuid4().hex[:6]}@lumen.test"
    await make_user(email=email, password="Password!1234")
    r = await client.post(
        "/api/v1/auth/password-reset/request", json={"email": email}
    )
    assert r.status_code == 200
    assert _capture_email, "no email queued"
    msg = _capture_email[0]
    # Plain text still sent (clients that don't render HTML).
    assert "reset" in msg["text"].lower()
    # HTML alternative is the iter 83 addition — pin its shape.
    assert msg["html"] is not None
    assert "Reset password" in msg["html"]
    assert "/reset-password?token=" in msg["html"]
