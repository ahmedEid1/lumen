"""Open Badges 3.0 / W3C VC issuance and verification.

OB3 is a W3C Verifiable Credentials v2 profile for digital learning
credentials. Compared to the legacy "URL plus PDF" path, an OB3
credential is a signed JSON-LD document a third party (an employer,
another LMS, a wallet) can verify offline given just the issuer's
public key. We keep the PDF download as a fallback for human display;
the OB3 JSON is the machine-readable record.

The credential payload follows IMS Global's OB3 v3.0 schema:

  * ``@context`` — the W3C VC v2 context plus the OB3 context, so a
    generic JSON-LD verifier knows how to type-check the document.
  * ``type`` — ``["VerifiableCredential", "OpenBadgeCredential"]``.
  * ``id`` — a Lumen URL that re-issues the JSON when fetched.
  * ``issuer`` — the platform's Profile object (id + name + url).
  * ``validFrom`` — when the learner finished the course.
  * ``credentialSubject`` — *who* earned *what*: the learner's
    platform URL plus an ``Achievement`` block (course title +
    description + criteria narrative).
  * ``proof`` — Ed25519 over JCS-canonicalized bytes; see
    :mod:`app.core.badges_keys`.

The achievement criteria is intentionally generic ("Completed all
lessons in course") rather than per-course because Lumen's completion
criterion *is* uniform: 100% lesson completion. If we ever offer
per-course rubrics, this is where they would go.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.badges_keys import sign_credential, verify_credential
from app.core.config import get_settings
from app.models.course import Course, Enrollment
from app.models.user import User

OB3_CONTEXT = [
    "https://www.w3.org/ns/credentials/v2",
    "https://purl.imsglobal.org/spec/ob/v3p0/context-3.0.3.json",
]


def _issuer_profile() -> dict[str, Any]:
    """Return the issuer Profile object embedded in every credential.

    This is duplicated into each credential rather than referenced by
    URL because OB3 verifiers MAY fetch the issuer URL but MUST NOT
    *require* it — keeping the object inline means a credential can
    be verified end-to-end with no network round-trip beyond the
    public key.
    """
    s = get_settings()
    base = str(s.badges_issuer_url).rstrip("/")
    return {
        "id": base,
        "type": "Profile",
        "name": s.app_name,
        "url": base,
    }


def _credential_id(certificate_id: str) -> str:
    """The credential's own URL — also the canonical fetch endpoint."""
    s = get_settings()
    base = str(s.badges_issuer_url).rstrip("/")
    return f"{base}/api/v1/credentials/{certificate_id}"


def issue_for_enrollment(
    *,
    enrollment: Enrollment,
    user: User,
    course: Course,
) -> dict[str, Any]:
    """Build and sign an OB3 credential for a completed enrollment.

    The caller passes the loaded ``enrollment``, ``user``, and
    ``course`` rows so we don't take an ``AsyncSession`` here — the
    service is a pure builder. The caller is responsible for storing
    the result on ``enrollment.badge_credential``.
    """
    if not enrollment.certificate_id:
        raise ValueError("Enrollment has no certificate_id — cannot issue OB3")
    completed = enrollment.completed_at or datetime.now(UTC)
    issuer_base = str(get_settings().badges_issuer_url).rstrip("/")
    learner_id = f"{issuer_base}/users/{user.id}"
    payload: dict[str, Any] = {
        "@context": OB3_CONTEXT,
        "id": _credential_id(enrollment.certificate_id),
        "type": ["VerifiableCredential", "OpenBadgeCredential"],
        "issuer": _issuer_profile(),
        "validFrom": completed.isoformat(),
        "name": f"Certificate of completion — {course.title}",
        "credentialSubject": {
            "id": learner_id,
            "type": "AchievementSubject",
            "name": user.full_name or "Learner",
            "achievement": {
                "id": f"{issuer_base}/courses/{course.slug}#achievement",
                "type": "Achievement",
                "name": course.title,
                "description": (course.overview or "")[:1000] or course.title,
                "criteria": {
                    "narrative": "Completed all lessons in the course.",
                },
            },
        },
    }
    return sign_credential(payload)


def verify(credential: dict[str, Any]) -> bool:
    """Thin wrapper so callers don't import the keys module directly."""
    return verify_credential(credential)
