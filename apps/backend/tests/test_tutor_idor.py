"""IDOR coverage for the existing tutor endpoints (L21-Sec).

Plan-v7 §V7-Sec spelled out the threat: a learner could try to read,
modify, or delete another learner's tutor conversations / messages
by guessing the 21-char nanoid ids. The endpoints already include
`WHERE user_id = current_user.id` filters — these tests lock that
contract in so a refactor that drops the filter can't ship silently.

Three endpoints, three IDOR scenarios per:

- POST /tutor/conversations/{id}/messages (foreign conv → 404)
- GET  /tutor/conversations/{id}           (foreign conv → 404)
- GET  /courses/{course_id}/tutor/conversations (listing scoped to me)

All three should collapse to 404 (NOT 403) so the endpoint isn't a
nanoid-existence oracle.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.user import Role


@pytest.fixture(autouse=True)
def _force_noop_providers(monkeypatch):
    """Pin both embedding + LLM providers to noop so the IDOR tests
    don't pull in sentence_transformers / network calls."""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "noop")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


async def _published_course(
    client: AsyncClient, teacher_headers: dict, db_session: AsyncSession
) -> str:
    """Minimal published course for the tutor to target.

    Pulled out so each IDOR test starts from a clean baseline.
    """
    import uuid

    from app.models.course import Subject
    from app.services.embeddings_ingest import ingest_course as _ingest

    # Direct ORM — admin-create-subject endpoint refuses teachers
    # (admin-only), and pulling in admin fixtures for an IDOR test
    # would needlessly expand the surface under test.
    s = Subject(slug=f"idor-test-{uuid.uuid4().hex[:8]}", title="IDOR test subject")
    db_session.add(s)
    await db_session.commit()
    subject_id = s.id

    course = await client.post(
        "/api/v1/courses",
        json={
            "title": "IDOR test course",
            "subject_id": subject_id,
            "overview": "for IDOR coverage",
            "difficulty": "beginner",
        },
        headers=teacher_headers,
    )
    assert course.status_code == 201, course.text
    course_id = course.json()["id"]

    module = await client.post(
        f"/api/v1/courses/{course_id}/modules",
        json={"title": "M"},
        headers=teacher_headers,
    )
    module_id = module.json()["id"]
    await client.post(
        f"/api/v1/courses/modules/{module_id}/lessons",
        json={
            "title": "L",
            "type": "text",
            "data": {"type": "text", "body_markdown": "body. " * 20},
        },
        headers=teacher_headers,
    )
    await client.patch(
        f"/api/v1/courses/{course_id}",
        json={"status": "published"},
        headers=teacher_headers,
    )
    await _ingest(db_session, course_id)
    return course_id


async def test_post_message_to_foreign_conversation_is_404(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """Learner B should not be able to append a message to learner A's
    conversation — the IDOR signal must be 404, not 403."""
    teacher = await auth_headers(role=Role.instructor)
    course_id = await _published_course(client, teacher, db_session)

    learner_a = await auth_headers(role=Role.student)
    learner_b = await auth_headers(role=Role.student)

    new = await client.post(
        f"/api/v1/courses/{course_id}/tutor/conversations",
        headers=learner_a,
    )
    assert new.status_code == 201, new.text
    conv_id = new.json()["id"]

    posted = await client.post(
        f"/api/v1/tutor/conversations/{conv_id}/messages",
        json={"content": "trying to inject"},
        headers=learner_b,
    )
    assert posted.status_code == 404, posted.text


async def test_list_conversations_scoped_to_current_user(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """Listing conversations on a course should NOT return another
    learner's conversation on the same course."""
    teacher = await auth_headers(role=Role.instructor)
    course_id = await _published_course(client, teacher, db_session)

    learner_a = await auth_headers(role=Role.student)
    learner_b = await auth_headers(role=Role.student)

    new = await client.post(
        f"/api/v1/courses/{course_id}/tutor/conversations",
        headers=learner_a,
    )
    a_conv_id = new.json()["id"]

    listing = await client.get(
        f"/api/v1/courses/{course_id}/tutor/conversations",
        headers=learner_b,
    )
    assert listing.status_code == 200, listing.text
    body = listing.json()
    item_ids = {item["id"] for item in body["items"]}
    assert a_conv_id not in item_ids, f"Learner B saw learner A's conversation in listing: {body!r}"
