"""Open Badges 3.0 / W3C VC — issuance, verification, endpoints."""

from __future__ import annotations

import copy
import json
import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import badges_keys
from app.models.course import Course, CourseStatus, Enrollment, Subject
from app.models.user import Role, User
from app.services import badges as badges_service


@pytest.fixture(autouse=True)
def _reset_badge_key_cache():
    """Fresh cached signing key per test so settings flips can land."""
    badges_keys.reset_for_tests()
    yield
    badges_keys.reset_for_tests()


async def _seed_completed_enrollment(
    db: AsyncSession,
) -> tuple[User, Course, Enrollment]:
    """Create the minimum row set the badge service expects.

    We don't go through the API here because the issuance hook is
    wired up at completion time and we want to test the badges
    primitives directly. The integration path (real lesson
    completion) is exercised in ``test_certificates.py`` and
    indirectly by ``test_issue_endpoint_returns_jsonld``.
    """
    subject = Subject(title="Programming", slug=f"prog-{uuid.uuid4().hex[:6]}")
    db.add(subject)
    await db.flush()
    user = User(
        email=f"badge-{uuid.uuid4().hex[:6]}@lumen.test",
        password_hash="x",
        full_name="Ada Lovelace",
        role=Role.student,
    )
    db.add(user)
    await db.flush()
    course = Course(
        owner_id=user.id,
        subject_id=subject.id,
        title="Analytical Engines",
        slug=f"engines-{uuid.uuid4().hex[:6]}",
        overview="An exploration of mechanical computation.",
        status=CourseStatus.published,
    )
    db.add(course)
    await db.flush()
    enrollment = Enrollment(
        user_id=user.id,
        course_id=course.id,
        completed_at=datetime.now(UTC),
        certificate_id=f"cert_{uuid.uuid4().hex}",
    )
    db.add(enrollment)
    await db.commit()
    await db.refresh(enrollment)
    return user, course, enrollment


async def test_issue_then_verify_roundtrip(db_session: AsyncSession) -> None:
    user, course, enrollment = await _seed_completed_enrollment(db_session)

    credential = badges_service.issue_for_enrollment(
        enrollment=enrollment, user=user, course=course
    )

    # Shape: must be a proper OB3 credential payload.
    assert credential["type"] == ["VerifiableCredential", "OpenBadgeCredential"]
    assert credential["@context"][0] == "https://www.w3.org/ns/credentials/v2"
    assert "OpenBadgeCredential" in credential["type"]
    assert credential["credentialSubject"]["name"] == "Ada Lovelace"
    assert credential["credentialSubject"]["achievement"]["name"] == course.title

    # Proof: DataIntegrityProof + eddsa-jcs-2022 + z-prefixed signature.
    proof = credential["proof"]
    assert proof["type"] == "DataIntegrityProof"
    assert proof["cryptosuite"] == "eddsa-jcs-2022"
    assert proof["proofPurpose"] == "assertionMethod"
    assert proof["proofValue"].startswith("z")

    # Roundtrip: verify the credential we just signed.
    assert badges_service.verify(credential) is True


async def test_tampered_credential_fails_verification(
    db_session: AsyncSession,
) -> None:
    """Any post-sign mutation to the payload must break the signature.

    Specifically tests the load-bearing claim — the learner name on
    ``credentialSubject``. If JCS canonicalization is correct, a
    one-character change anywhere in the signed payload must flip
    verification to ``False``.
    """
    user, course, enrollment = await _seed_completed_enrollment(db_session)
    credential = badges_service.issue_for_enrollment(
        enrollment=enrollment, user=user, course=course
    )
    assert badges_service.verify(credential) is True

    tampered = copy.deepcopy(credential)
    tampered["credentialSubject"]["name"] = "Eve Eavesdropper"
    assert badges_service.verify(tampered) is False

    # Proof tampering (flip one base64 char) also breaks verification.
    tampered2 = copy.deepcopy(credential)
    sig = tampered2["proof"]["proofValue"]
    # Flip a middle character; preserve length so b64 decode still works.
    middle = len(sig) // 2
    flipped_char = "B" if sig[middle] != "B" else "C"
    tampered2["proof"]["proofValue"] = sig[:middle] + flipped_char + sig[middle + 1 :]
    assert badges_service.verify(tampered2) is False


async def test_missing_credential_returns_404(client: AsyncClient) -> None:
    """The endpoint is public; an unknown ID is 404, not 401."""
    r = await client.get("/api/v1/credentials/cert_does-not-exist")
    assert r.status_code == 404, r.text
    body = r.json()
    assert body["error"]["code"] == "badge.not_found"


async def test_issue_endpoint_returns_jsonld(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """GET /credentials/{id} returns the signed JSON-LD payload."""
    user, course, enrollment = await _seed_completed_enrollment(db_session)
    # Populate the stored credential as the enrollment service would.
    enrollment.badge_credential = badges_service.issue_for_enrollment(
        enrollment=enrollment, user=user, course=course
    )
    await db_session.commit()

    r = await client.get(f"/api/v1/credentials/{enrollment.certificate_id}")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/ld+json")
    body = json.loads(r.text)
    assert body["type"] == ["VerifiableCredential", "OpenBadgeCredential"]
    # The body we serve must verify with the same key.
    assert badges_service.verify(body) is True


async def test_verify_endpoint_returns_summary(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user, course, enrollment = await _seed_completed_enrollment(db_session)
    enrollment.badge_credential = badges_service.issue_for_enrollment(
        enrollment=enrollment, user=user, course=course
    )
    await db_session.commit()

    r = await client.get(f"/api/v1/credentials/{enrollment.certificate_id}/verify")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid"] is True
    assert body["achievement_name"] == course.title
    assert body["learner_name"] == "Ada Lovelace"


async def test_verify_endpoint_detects_stored_tamper(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """If a stored credential was somehow mutated, the verify endpoint
    must return ``valid=false`` rather than serving a false positive."""
    user, course, enrollment = await _seed_completed_enrollment(db_session)
    credential = badges_service.issue_for_enrollment(
        enrollment=enrollment, user=user, course=course
    )
    # Mutate the stored JSON to simulate DB-side corruption / tampering.
    credential["credentialSubject"]["name"] = "Mallory"
    enrollment.badge_credential = credential
    await db_session.commit()

    r = await client.get(f"/api/v1/credentials/{enrollment.certificate_id}/verify")
    assert r.status_code == 200, r.text
    assert r.json()["valid"] is False


async def test_credentials_endpoint_is_rate_limited(client: AsyncClient) -> None:
    """Public endpoints get a per-identity cap to blunt enumeration.

    Same posture as ``/certificates/verify/{id}`` from rebuild Fix B2:
    a 60/minute cap is generous for an HR reviewer pasting a stack
    of credentials and below the threshold a scraper needs.
    """
    last = None
    for _ in range(65):
        last = await client.get("/api/v1/credentials/cert_does-not-exist")
    assert last is not None
    assert last.status_code == 429, last.text
    assert last.json()["error"]["code"] == "rate_limited"


async def test_credential_minted_on_lesson_completion(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """The full happy path: complete a course → enrollment row has
    both ``certificate_id`` and a valid ``badge_credential``."""
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = Subject(title="Math", slug=f"math-{uuid.uuid4().hex[:6]}")
    db_session.add(subject)
    await db_session.commit()

    create = await client.post(
        "/api/v1/courses",
        json={"title": "OB3 course", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    m = (
        await client.post(
            f"/api/v1/courses/{course_id}/modules",
            json={"title": "M"},
            headers=teacher,
        )
    ).json()
    lesson = (
        await client.post(
            f"/api/v1/courses/modules/{m['id']}/lessons",
            json={
                "title": "L",
                "type": "text",
                "data": {"type": "text", "body_markdown": "x"},
            },
            headers=teacher,
        )
    ).json()
    await client.patch(
        f"/api/v1/courses/{course_id}",
        json={"status": "published"},
        headers=teacher,
    )
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)
    await client.post(
        f"/api/v1/me/progress/lessons/{lesson['id']}",
        json={"completed": True},
        headers=student,
    )

    # The enrollment row should now carry both artifacts.
    row = (
        await db_session.execute(
            __import_select_for_course(course_id)
        )
    ).scalar_one()
    assert row.certificate_id is not None
    assert row.badge_credential is not None
    assert badges_service.verify(row.badge_credential) is True


def __import_select_for_course(course_id: str):
    """Inline helper for the integration test above.

    Tucked into a function so the top-level import block of this
    test file stays focused on what the issue/verify tests use.
    """
    from sqlalchemy import select

    return select(Enrollment).where(Enrollment.course_id == course_id)
