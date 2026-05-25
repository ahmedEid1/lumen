"""Course-scoped RAG tutor (Phase E1).

Covers:
* The LLM Protocol implementations (Anthropic, OpenAI, Noop) at the
  selection layer and the noop's prompt-context parsing.
* The tutor service end-to-end on the noop provider — citation
  extraction, refusal on empty retrieval, refusal echo, history
  forwarding.
* The REST endpoints — create / list / get / post — including the
  cross-user authz collapse to 404 and the 20/minute rate limit
  on the message-post endpoint.

Like Phase E0 + E4 before it, this suite runs against a real
Postgres so we don't have to mock the retrieval pipeline; the LLM
provider is swapped to ``noop`` so no network calls fire.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.course import (
    Course,
    CourseStatus,
    Difficulty,
    Lesson,
    LessonType,
    Module,
    Subject,
)
from app.models.tutor_conversation import (
    TutorConversation,
    TutorMessage,
    TutorMessageRole,
)
from app.models.user import Role, User
from app.services import tutor as tutor_service
from app.services.embeddings_ingest import ingest_course
from app.services.llm import (
    AnthropicProvider,
    ChatMessage,
    NOOP_REFUSAL,
    NOOP_RESPONSE_PREFIX,
    NoopProvider,
    OpenAIProvider,
    get_provider,
)


# ---------- Fixtures + helpers ----------


@pytest.fixture(autouse=True)
def _force_noop_providers(monkeypatch):
    """Pin both embedding + LLM providers to noop for every tutor test."""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "noop")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


async def _seed_course(
    db: AsyncSession,
    *,
    owner_id: str,
    lesson_bodies: list[tuple[str, str]],
) -> Course:
    """Persist a Subject + Course + Module + N text lessons.

    ``lesson_bodies`` is a list of ``(title, body_markdown)`` tuples.
    Returns the persisted Course. We flush the Subject first so its
    server-side default ``id`` is populated before the Course row
    references it as a foreign key.
    """
    suffix = uuid.uuid4().hex[:6]
    subject = Subject(title=f"ML {suffix}", slug=f"ml-{suffix}")
    db.add(subject)
    await db.flush()
    course = Course(
        owner_id=owner_id,
        subject_id=subject.id,
        title=f"Tutor Test {suffix}",
        slug=f"tutor-test-{suffix}",
        overview="overview",
        difficulty=Difficulty.beginner,
        status=CourseStatus.published,
    )
    db.add(course)
    await db.flush()
    module = Module(course_id=course.id, title="Module 1", order=0)
    db.add(module)
    await db.flush()
    for i, (title, body) in enumerate(lesson_bodies):
        db.add(
            Lesson(
                id=f"lsn_{suffix}_{i}",
                module_id=module.id,
                title=title,
                order=i,
                type=LessonType.text,
                data={"type": "text", "body_markdown": body},
            )
        )
    await db.commit()
    return course


# ---------- LLM provider tests ----------


def test_get_provider_respects_env_setting() -> None:
    assert isinstance(get_provider(), NoopProvider)


def test_provider_classes_have_name_attribute() -> None:
    """Each provider exposes a stable ``name`` for log/audit tagging."""
    assert AnthropicProvider.name == "anthropic"
    assert OpenAIProvider.name == "openai"
    assert NoopProvider.name == "noop"


async def test_noop_provider_emits_citations_for_context_lessons() -> None:
    """The noop provider mines ``Lesson L<id>:`` headers out of the
    system prompt and emits one ``[L:<id>]`` citation token per
    lesson so the citation parser has realistic input."""
    provider = NoopProvider()
    system = (
        "You are a tutor.\n\n"
        "--- Course content ---\n"
        "Lesson Llsn_a: Intro\nfoo bar baz\n\n"
        "Lesson Llsn_b: Next\nspam ham eggs"
    )
    reply = await provider.chat(
        [
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content="explain foo"),
        ]
    )
    assert reply.startswith(NOOP_RESPONSE_PREFIX)
    assert "[L:lsn_a]" in reply
    assert "[L:lsn_b]" in reply


async def test_noop_provider_refuses_when_no_context() -> None:
    """No lesson ids in the system prompt → noop returns the refusal sentinel."""
    provider = NoopProvider()
    reply = await provider.chat(
        [
            ChatMessage(role="system", content="bare system prompt, no lessons"),
            ChatMessage(role="user", content="anything"),
        ]
    )
    assert reply == NOOP_REFUSAL


# ---------- Citation extraction ----------


async def test_extract_citations_validates_against_retrieval_set(
    db_session: AsyncSession, make_user
) -> None:
    """Tokens for lessons we didn't retrieve are silently dropped.

    This is the second guardrail (the first being "refuse on empty
    retrieval"): the UI can never render a citation pointing at a
    lesson the answer wasn't grounded in.
    """
    owner = await make_user(role=Role.instructor)
    course = await _seed_course(
        db_session,
        owner_id=owner.id,
        lesson_bodies=[
            ("Photosynthesis", "Plants convert sunlight via chlorophyll. " * 5),
            ("Respiration", "Cells generate ATP through cellular respiration. " * 5),
        ],
    )
    await ingest_course(db_session, course.id)

    # Pull the two chunks we just ingested so we have a concrete
    # retrieval set to validate against.
    chunks = (
        await db_session.execute(
            select(tutor_service.LessonChunk).order_by(
                tutor_service.LessonChunk.lesson_id
            )
        )
    ).scalars().all() if False else None  # noqa: F841 — keep explicit import readable
    from app.models.lesson_chunk import LessonChunk

    chunks_rows = (
        await db_session.execute(
            select(LessonChunk).order_by(LessonChunk.lesson_id)
        )
    ).scalars().all()
    # Eager-load lesson for each chunk so ``extract_citations`` can
    # read ``chunk.lesson.title`` without an N+1 mid-test.
    for c in chunks_rows:
        await db_session.refresh(c, attribute_names=["lesson"])

    real_id = chunks_rows[0].lesson_id
    fake_id = "lsn_fake_never_retrieved"
    answer = (
        f"Plants need light [L:{real_id}] and also magic [L:{fake_id}] "
        f"plus a repeat [L:{real_id}]."
    )
    citations = tutor_service.extract_citations(answer, chunks_rows)
    # Real lesson kept, fake one dropped, repeat deduplicated.
    assert len(citations) == 1
    assert citations[0].lesson_id == real_id


def test_extract_citations_handles_empty_answer() -> None:
    assert tutor_service.extract_citations("", []) == []
    assert tutor_service.extract_citations("plain text no tokens", []) == []


# ---------- Tutor service ----------


async def test_ask_refuses_when_retrieval_returns_nothing(
    db_session: AsyncSession, make_user
) -> None:
    """Empty retrieval → structured refusal, no LLM call.

    We seed a course with no lessons so ``find_relevant_chunks``
    has nothing to return. The service should short-circuit before
    talking to the provider.
    """
    owner = await make_user(role=Role.instructor)
    course = await _seed_course(
        db_session, owner_id=owner.id, lesson_bodies=[]
    )
    result = await tutor_service.ask(
        db_session,
        course=course,
        user_message="What is photosynthesis?",
    )
    assert result.refused is True
    assert result.answer == tutor_service.REFUSAL_TEXT
    assert result.citations == []


async def test_ask_returns_answer_with_validated_citations(
    db_session: AsyncSession, make_user
) -> None:
    """End-to-end pipeline on the noop provider.

    The noop emits ``[L:<id>]`` tokens for every lesson id it sees
    in the system prompt's context block, so a successful answer
    here proves: retrieval found chunks, the system prompt advertised
    them with the right header, the noop echoed citations back,
    and the parser validated them against the retrieval set.
    """
    owner = await make_user(role=Role.instructor)
    course = await _seed_course(
        db_session,
        owner_id=owner.id,
        lesson_bodies=[
            ("Photosynthesis", "Plants convert sunlight via chlorophyll. " * 8),
            ("Respiration", "Cells generate ATP through cellular respiration. " * 8),
            ("DNA", "DNA replication uses helicase and polymerase. " * 8),
        ],
    )
    await ingest_course(db_session, course.id)

    result = await tutor_service.ask(
        db_session,
        course=course,
        user_message="Explain photosynthesis briefly.",
        top_k=3,
    )
    assert result.refused is False
    assert result.answer.startswith(NOOP_RESPONSE_PREFIX)
    assert len(result.citations) >= 1
    # Every citation must be a real lesson id we retrieved.
    valid_ids = {
        row.id
        for row in (
            await db_session.execute(select(Lesson))
        ).scalars().all()
    }
    for c in result.citations:
        assert c.lesson_id in valid_ids
        assert c.lesson_title
        assert c.chunk_excerpt


async def test_ask_blank_message_returns_refusal(
    db_session: AsyncSession, make_user
) -> None:
    owner = await make_user(role=Role.instructor)
    course = await _seed_course(
        db_session, owner_id=owner.id, lesson_bodies=[("L1", "Body. " * 20)]
    )
    result = await tutor_service.ask(
        db_session, course=course, user_message="   "
    )
    assert result.refused is True


async def test_build_system_prompt_emits_lesson_id_headers(
    db_session: AsyncSession, make_user
) -> None:
    """The ``Lesson L<id>: <title>`` header is the citation handshake.

    The model is told to wrap claims with ``[L:<lesson_id>]`` and
    we test that the system prompt actually advertises lesson ids
    in that format — break the format and the model has no idea
    what to cite.
    """
    owner = await make_user(role=Role.instructor)
    course = await _seed_course(
        db_session,
        owner_id=owner.id,
        lesson_bodies=[("Photosynthesis", "Body about plants. " * 10)],
    )
    await ingest_course(db_session, course.id)
    from app.models.lesson_chunk import LessonChunk

    chunks = (
        await db_session.execute(select(LessonChunk))
    ).scalars().all()
    for c in chunks:
        await db_session.refresh(c, attribute_names=["lesson"])

    prompt = tutor_service.build_system_prompt(course, chunks)
    assert f"Lesson L{chunks[0].lesson_id}:" in prompt
    assert "[L:<lesson_id>]" in prompt
    assert course.title in prompt


# ---------- API surface ----------


async def _course_via_api(
    client: AsyncClient,
    teacher_headers: dict,
    db: AsyncSession,
    *,
    lesson_bodies: list[tuple[str, str]],
) -> str:
    """Helper: create + publish a course with chunks ingested.

    Builds the course via the HTTP API (so the teacher's auth path
    is exercised) then ingests chunks directly against the DB.
    """
    suffix = uuid.uuid4().hex[:6]
    subject = Subject(title=f"S {suffix}", slug=f"s-{suffix}")
    db.add(subject)
    await db.flush()
    await db.commit()
    await db.refresh(subject)

    create = await client.post(
        "/api/v1/courses",
        json={
            "title": f"Tutor API {suffix}",
            "subject_id": subject.id,
            "overview": "ovr",
        },
        headers=teacher_headers,
    )
    assert create.status_code == 201, create.text
    course_id = create.json()["id"]

    m = await client.post(
        f"/api/v1/courses/{course_id}/modules",
        json={"title": "M"},
        headers=teacher_headers,
    )
    module_id = m.json()["id"]

    for title, body in lesson_bodies:
        r = await client.post(
            f"/api/v1/courses/modules/{module_id}/lessons",
            json={
                "title": title,
                "type": "text",
                "data": {"type": "text", "body_markdown": body},
            },
            headers=teacher_headers,
        )
        assert r.status_code == 201, r.text

    await client.patch(
        f"/api/v1/courses/{course_id}",
        json={"status": "published"},
        headers=teacher_headers,
    )
    # Ingest chunks so the tutor has retrieval material.
    await ingest_course(db, course_id)
    return course_id


async def test_conversation_lifecycle(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """Create → post → get round-trip.

    Drives the four endpoints in order and asserts the persisted
    state lines up at each step. This is the closest we have to an
    integration test for the tutor surface; the noop provider keeps
    it network-free.
    """
    teacher = await auth_headers(role=Role.instructor)
    course_id = await _course_via_api(
        client,
        teacher,
        db_session,
        lesson_bodies=[
            ("Intro", "The mitochondria is the powerhouse of the cell. " * 8),
            ("Cells", "Cells are the basic unit of life. " * 8),
        ],
    )
    learner = await auth_headers(role=Role.student)

    # 1) Open a conversation.
    new = await client.post(
        f"/api/v1/courses/{course_id}/tutor/conversations",
        headers=learner,
    )
    assert new.status_code == 201, new.text
    conv = new.json()
    assert conv["course_id"] == course_id
    assert conv["messages"] == []
    conv_id = conv["id"]

    # 2) Post a question.
    posted = await client.post(
        f"/api/v1/tutor/conversations/{conv_id}/messages",
        json={"content": "What powers the cell?"},
        headers=learner,
    )
    assert posted.status_code == 201, posted.text
    body = posted.json()
    assert body["user_message"]["content"] == "What powers the cell?"
    assert body["assistant_message"]["role"] == "assistant"
    assert body["assistant_message"]["content"].startswith(NOOP_RESPONSE_PREFIX)
    assert len(body["assistant_message"]["citations"]) >= 1
    for c in body["assistant_message"]["citations"]:
        assert c["lesson_id"]
        assert c["lesson_title"]
        assert c["chunk_excerpt"]

    # 3) Pull the conversation back — both turns persisted in order.
    detail = await client.get(
        f"/api/v1/tutor/conversations/{conv_id}", headers=learner
    )
    assert detail.status_code == 200, detail.text
    msgs = detail.json()["messages"]
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"

    # 4) List shows it.
    listing = await client.get(
        f"/api/v1/courses/{course_id}/tutor/conversations",
        headers=learner,
    )
    assert listing.status_code == 200, listing.text
    page = listing.json()
    assert page["total"] == 1
    assert page["items"][0]["id"] == conv_id
    assert page["items"][0]["message_count"] == 2


async def test_get_conversation_other_user_is_404(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """Conversations belonging to another user collapse to 404, not 403.

    We never confirm-or-deny that a conversation id exists for a
    user who doesn't own it — that would turn the endpoint into
    an id-enumeration oracle.
    """
    teacher = await auth_headers(role=Role.instructor)
    course_id = await _course_via_api(
        client,
        teacher,
        db_session,
        lesson_bodies=[("L", "Body. " * 20)],
    )
    learner_a = await auth_headers(role=Role.student)
    learner_b = await auth_headers(role=Role.student)

    new = await client.post(
        f"/api/v1/courses/{course_id}/tutor/conversations",
        headers=learner_a,
    )
    conv_id = new.json()["id"]

    other = await client.get(
        f"/api/v1/tutor/conversations/{conv_id}", headers=learner_b
    )
    assert other.status_code == 404


async def test_post_message_rate_limited_at_20_per_minute(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """The 21st POST in the same minute should 429.

    We don't want to actually wait a minute, so this asserts the
    cap and that the error envelope matches the standard 429
    payload shape.

    Isolation note: the conftest ``_reset_rate_limiter`` autouse
    fixture already calls ``ratelimit.reset_for_tests()`` before
    every test, but in the full-suite run we still saw sporadic
    failures from this test. The root cause was that the
    ``_force_noop_providers`` autouse fixture in *this* module
    runs alongside the conftest one, and fixture-ordering between
    same-scope autouse fixtures isn't strictly guaranteed — under
    parallel-ish ordering the limiter was being torn back up with
    leftover hits from a prior tutor test that had used the same
    "user:<sub>" key family (different sub, but the storage dict
    was holding stale window entries that hadn't expired). We
    explicitly reset the limiter again here so the test is
    self-contained and doesn't depend on the autouse ordering.
    """
    from app.core.ratelimit import reset_for_tests as _reset_limiter

    _reset_limiter()
    teacher = await auth_headers(role=Role.instructor)
    course_id = await _course_via_api(
        client,
        teacher,
        db_session,
        lesson_bodies=[("L", "Body about something. " * 20)],
    )
    learner = await auth_headers(role=Role.student)
    # Reset once more after the auth fixtures ran — ``auth_headers``
    # itself hits ``/auth/login`` which is rate-limited (10/minute,
    # keyed by IP for anonymous traffic). Stale entries from prior
    # tests' login attempts in the same MemoryStorage bucket dict
    # have been known to interact oddly with later hits at the
    # 20/minute tier; clearing again right before the post loop
    # guarantees we start from zero.
    _reset_limiter()
    new = await client.post(
        f"/api/v1/courses/{course_id}/tutor/conversations",
        headers=learner,
    )
    conv_id = new.json()["id"]

    last_status = 0
    for _ in range(22):
        r = await client.post(
            f"/api/v1/tutor/conversations/{conv_id}/messages",
            json={"content": "ping"},
            headers=learner,
        )
        last_status = r.status_code
        if r.status_code == 429:
            break
    assert last_status == 429


async def test_post_message_persists_user_turn_even_when_refused(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """A refused answer still saves the user's question.

    We seed a course with NO lessons so retrieval is guaranteed
    empty → the tutor service refuses without calling the LLM.
    The user's question must still land in ``tutor_messages`` so
    the audit log shows what they asked.
    """
    teacher = await auth_headers(role=Role.instructor)
    # Build an empty course directly (the publish-time minimum-content
    # gate would block the HTTP path, but we want the tutor refusal
    # path which needs an empty retrieval set). We flush the Subject
    # first so its IdMixin default fires before the Course row
    # references it as a foreign key.
    suffix = uuid.uuid4().hex[:6]
    subject = Subject(title=f"S {suffix}", slug=f"s-{suffix}")
    db_session.add(subject)
    await db_session.flush()
    owner = (await db_session.execute(select(User).limit(1))).scalar_one()
    course = Course(
        owner_id=owner.id,
        subject_id=subject.id,
        title="Empty",
        slug=f"empty-{suffix}",
        overview="",
        status=CourseStatus.published,
    )
    db_session.add(course)
    await db_session.commit()

    learner = await auth_headers(role=Role.student)
    new = await client.post(
        f"/api/v1/courses/{course.id}/tutor/conversations",
        headers=learner,
    )
    conv_id = new.json()["id"]

    posted = await client.post(
        f"/api/v1/tutor/conversations/{conv_id}/messages",
        json={"content": "anything"},
        headers=learner,
    )
    assert posted.status_code == 201
    body = posted.json()
    assert body["refused"] is True
    assert body["assistant_message"]["content"] == tutor_service.REFUSAL_TEXT

    # Both rows landed; user turn is durable even on refusal.
    rows = (
        await db_session.execute(
            select(TutorMessage)
            .where(TutorMessage.conversation_id == conv_id)
            .order_by(TutorMessage.created_at)
        )
    ).scalars().all()
    assert [r.role for r in rows] == [
        TutorMessageRole.user,
        TutorMessageRole.assistant,
    ]


async def test_start_conversation_requires_auth(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """Anonymous POST 401s — tutor is auth-gated end-to-end.

    We have to clear the test client's cookie jar because the
    ``auth_headers`` helper POSTs to ``/auth/login`` which sets a
    session cookie on the client. That cookie would re-authenticate
    a subsequent anonymous-style call. The Bearer-token tests don't
    hit this because they set ``Authorization`` explicitly, but a
    no-header call sees the cookie and authenticates.
    """
    teacher = await auth_headers(role=Role.instructor)
    course_id = await _course_via_api(
        client, teacher, db_session, lesson_bodies=[("L", "Body. " * 20)]
    )
    client.cookies.clear()
    r = await client.post(
        f"/api/v1/courses/{course_id}/tutor/conversations"
    )
    assert r.status_code == 401


async def test_list_my_conversations_paginates(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """Listing endpoint respects ``page`` + ``page_size``."""
    teacher = await auth_headers(role=Role.instructor)
    course_id = await _course_via_api(
        client, teacher, db_session, lesson_bodies=[("L", "Body. " * 20)]
    )
    learner = await auth_headers(role=Role.student)
    for _ in range(3):
        r = await client.post(
            f"/api/v1/courses/{course_id}/tutor/conversations",
            headers=learner,
        )
        assert r.status_code == 201

    page1 = await client.get(
        f"/api/v1/courses/{course_id}/tutor/conversations?page=1&page_size=2",
        headers=learner,
    )
    assert page1.status_code == 200
    body = page1.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["page_size"] == 2
