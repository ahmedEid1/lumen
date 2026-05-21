"""Minimal SMTP email sender (sync — call from Celery)."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


def send_email(*, to: str, subject: str, text: str, html: str | None = None) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    try:
        if s.smtp_tls:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as server:
                server.starttls(context=ctx)
                if s.smtp_username:
                    server.login(s.smtp_username, s.smtp_password.get_secret_value())
                server.send_message(msg)
        else:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as server:
                if s.smtp_username:
                    server.login(s.smtp_username, s.smtp_password.get_secret_value())
                server.send_message(msg)
        log.info("email_sent", to=to, subject=subject)
    except Exception:  # pragma: no cover - depends on infra
        log.exception("email_failed", to=to, subject=subject)
        raise
