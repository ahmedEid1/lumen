"""Regression: the certificate PDF's verify URL must match the public page.

Before iteration 33 the PDF embedded ``verify at /certificates/<id>``,
which 404s — the public verify page is at ``/verify/<id>``. Anyone who
downloaded a certificate and typed the URL would land nowhere.
"""

from __future__ import annotations

from app.workers.tasks.certificates import VERIFY_PATH, render


def test_pdf_embeds_the_public_verify_path() -> None:
    pdf = render(
        learner_name="Lina Park",
        course_title="FastAPI from Zero",
        certificate_id="cert_abc12345",
    )
    assert pdf.startswith(b"%PDF")
    # ReportLab stores text in the PDF binary essentially verbatim (no
    # compression for short strings in default settings), so the string is
    # discoverable as a substring.
    assert b"/verify/cert_abc12345" in pdf, "PDF must point at the public verify page"
    # And the wrong old path must not be present
    assert b"/certificates/cert_abc12345" not in pdf


def test_verify_path_is_a_single_source_of_truth() -> None:
    """If a future change wants to move the public verify page, both the
    PDF text and this constant must move together."""
    assert VERIFY_PATH == "/verify"
