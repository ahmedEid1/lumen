"""Email tasks."""

from __future__ import annotations

from app.services.email import send_email
from app.workers.celery_app import celery


@celery.task(name="app.workers.tasks.email.send", autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def send(to: str, subject: str, text: str, html: str | None = None) -> None:
    send_email(to=to, subject=subject, text=text, html=html)
