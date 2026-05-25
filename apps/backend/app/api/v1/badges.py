"""Public Open Badges 3.0 / W3C VC endpoints.

Two public, rate-limited reads:

* ``GET /credentials/{certificate_id}`` returns the signed OB3 JSON-LD
  credential, ``Content-Type: application/ld+json``. Anyone with a
  certificate ID can fetch and verify it offline given the issuer
  public key. No PII beyond what was already in the credential at
  issue time — the same data the existing PDF download exposes.
* ``GET /credentials/{certificate_id}/verify`` re-verifies the
  embedded signature server-side and returns a small summary. The
  client could verify offline too; this exists for browser
  consumers that don't want to ship a JOSE library.

Both endpoints share the rate-limit posture of the legacy
``/certificates/verify/{id}`` endpoint (Fix B2): certificate IDs are
opaque 21-char nanoids, but anyone walking the keyspace at scale
could harvest learner/achievement pairs. Sixty hits per minute per
identity matches what an HR verifier will plausibly do — anything
above is a scraper.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DBSession
from app.core.errors import NotFoundError
from app.core.ratelimit import limiter
from app.models.course import Course, Enrollment
from app.models.user import User
from app.services import badges as badges_service

router = APIRouter()


class CredentialVerifyOut(BaseModel):
    """Tiny human-friendly summary of a verify call.

    We intentionally do NOT echo the full credential here — clients
    that need the credential should call the ``/credentials/{id}``
    endpoint directly. The split keeps each surface single-purpose
    and lets a future caching layer cache each independently.
    """

    valid: bool
    issuer: str | None = None
    achievement_name: str | None = None
    learner_name: str | None = None


async def _load_credential(db: DBSession, certificate_id: str) -> tuple[Enrollment, Course, User]:
    """Resolve a ``certificate_id`` to the rows that produced it."""
    row = (
        await db.execute(
            select(Enrollment, Course, User)
            .join(Course, Course.id == Enrollment.course_id)
            .join(User, User.id == Enrollment.user_id)
            .where(Enrollment.certificate_id == certificate_id)
        )
    ).first()
    if not row:
        raise NotFoundError("Credential not found", code="badge.not_found")
    return row  # type: ignore[return-value]


@router.get("/{certificate_id}", response_class=Response)
@limiter.limit("60/minute")
async def get_credential(
    certificate_id: str,
    db: DBSession,
    request: Request,
    response: Response,
) -> Response:
    """Return the signed OB3 credential as ``application/ld+json``.

    If the row predates Phase E5 and has no stored credential we
    mint one on the fly so the endpoint stays useful for historical
    certificates. The on-the-fly mint is *not* persisted back to the
    row from a GET — that would turn a read into a write — but a
    subsequent course completion or admin action can re-issue.
    """
    enrollment, course, user = await _load_credential(db, certificate_id)
    credential: dict[str, Any]
    if enrollment.badge_credential:
        credential = dict(enrollment.badge_credential)
    else:
        credential = badges_service.issue_for_enrollment(
            enrollment=enrollment,
            user=user,
            course=course,
        )
    return Response(
        # Pydantic / FastAPI's default JSON serializer happens to emit
        # the same key order we stored on insert because we use the
        # raw dict; that's fine for HTTP but does NOT round-trip back
        # to the same signature bytes after re-canonicalization. The
        # verify endpoint always re-canonicalizes, so order doesn't
        # matter for verification — it only matters that the bytes we
        # *signed* are the bytes we *re-canonicalize*, which is what
        # ``sign_credential`` / ``verify_credential`` guarantee.
        content=json.dumps(credential, ensure_ascii=False),
        media_type="application/ld+json",
        headers={"Cache-Control": "public, max-age=60"},
    )


@router.get("/{certificate_id}/verify", response_model=CredentialVerifyOut)
@limiter.limit("60/minute")
async def verify_credential(
    certificate_id: str,
    db: DBSession,
    request: Request,
    response: Response,
) -> CredentialVerifyOut:
    """Re-verify a stored credential server-side."""
    enrollment, course, user = await _load_credential(db, certificate_id)
    credential = enrollment.badge_credential or badges_service.issue_for_enrollment(
        enrollment=enrollment,
        user=user,
        course=course,
    )
    valid = badges_service.verify(credential)
    issuer = credential.get("issuer") if isinstance(credential, dict) else None
    issuer_id: str | None = None
    if isinstance(issuer, dict):
        raw_id = issuer.get("id")
        issuer_id = raw_id if isinstance(raw_id, str) else None
    return CredentialVerifyOut(
        valid=valid,
        issuer=issuer_id,
        achievement_name=course.title,
        learner_name=user.full_name or "Learner",
    )
