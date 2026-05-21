"""Certificate PDF rendering."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas

from app.core.logging import get_logger
from app.workers.celery_app import celery

log = get_logger(__name__)

# Public, anonymous-friendly verification page. Must match the Next.js
# route at ``apps/frontend/src/app/verify/[id]/page.tsx``.
VERIFY_PATH = "/verify"


@celery.task(name="app.workers.tasks.certificates.render")
def render(*, learner_name: str, course_title: str, certificate_id: str) -> bytes:
    """Render a certificate PDF, return bytes (caller decides storage)."""
    buf = BytesIO()
    pdf = canvas.Canvas(buf, pagesize=landscape(letter))
    width, height = landscape(letter)

    pdf.setFont("Helvetica-Bold", 36)
    pdf.drawCentredString(width / 2, height - 120, "Certificate of Completion")

    pdf.setFont("Helvetica", 16)
    pdf.drawCentredString(width / 2, height - 180, "presented to")

    pdf.setFont("Helvetica-Bold", 28)
    pdf.drawCentredString(width / 2, height - 230, learner_name)

    pdf.setFont("Helvetica", 16)
    pdf.drawCentredString(width / 2, height - 280, "for successfully completing")

    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawCentredString(width / 2, height - 320, course_title)

    pdf.setFont("Helvetica", 12)
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    pdf.drawCentredString(width / 2, 90, f"Issued {today}")
    pdf.drawCentredString(width / 2, 70, f"Certificate ID: {certificate_id}")
    pdf.drawCentredString(
        width / 2, 50, f"Lumen — verify at {VERIFY_PATH}/{certificate_id}"
    )

    pdf.showPage()
    pdf.save()
    log.info("certificate_rendered", certificate_id=certificate_id)
    return buf.getvalue()
