"""AI-assisted course authoring (Phase E2).

Every test routes through a scripted LLM provider that returns
caller-supplied JSON strings, so the suite never touches a network.
The provider matches :class:`app.services.llm.LLMProvider`'s Protocol
(``async def chat(messages, temperature=0.2) -> str``) so we can
hand it back from ``get_provider`` without touching the real
selector logic.
"""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Lesson, LessonType, Module, Subject
from app.models.user import Role
from app.services import ai_authoring, llm


class _ScriptedProvider:
    """Plays back a queue of canned replies.

    Each ``chat`` call pops the head of the queue. We assert (loudly)
    when the queue is empty so a test that under-scripts the queue
    fails with a clear message rather than a silent KeyError or a
    real network call.
    """

    name = "scripted"

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.calls: list[list[llm.ChatMessage]] = []

    async def chat(
        self,
        messages: list[llm.ChatMessage],
        temperature: float = 0.2,
    ) -> str:
        del temperature
        self.calls.append(messages)
        if not self._replies:
            raise AssertionError(
                "ScriptedProvider queue exhausted — test under-scripted the LLM."
            )
        return self._replies.pop(0)


def _install(monkeypatch: pytest.MonkeyPatch, replies: list[str]) -> _ScriptedProvider:
    prov = _ScriptedProvider(replies)
    monkeypatch.setattr(llm, "get_provider", lambda: prov)
    return prov


_VALID_OUTLINE = {
    "title": "FastAPI in 90 Minutes",
    "overview": "A focused intro to building APIs with FastAPI.",
    "modules": [
        {
            "title": "Setup",
            "lessons": [
                {"title": "Install Python 3.13", "type": "text"},
                {"title": "Install FastAPI", "type": "text"},
                {"title": "Setup quiz", "type": "quiz"},
            ],
        },
        {
            "title": "First endpoint",
            "lessons": [
                {"title": "Hello world endpoint", "type": "text"},
                {"title": "Endpoint quiz", "type": "quiz"},
            ],
        },
    ],
}


_VALID_LESSON_DOC = {
    "type": "doc",
    "content": [
        {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [{"type": "text", "text": "Overview"}],
        },
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "Body text here."}],
        },
    ],
}


_VALID_QUIZ = {
    "questions": [
        {
            "id": "q1",
            "prompt": "What is FastAPI?",
            "kind": "single",
            "choices": [
                {"id": "a", "text": "A Python web framework"},
                {"id": "b", "text": "A JavaScript library"},
                {"id": "c", "text": "A database"},
            ],
            "answer_keys": ["a"],
        },
        {
            "id": "q2",
            "prompt": "Which protocol does it speak?",
            "kind": "single",
            "choices": [
                {"id": "a", "text": "HTTP"},
                {"id": "b", "text": "SMTP"},
                {"id": "c", "text": "FTP"},
            ],
            "answer_keys": ["a"],
        },
    ]
}


# ---------- Service-level (no HTTP) ----------


async def test_generate_outline_parses_canned_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, [json.dumps(_VALID_OUTLINE)])
    outline = await ai_authoring.generate_outline("Teach FastAPI to absolute beginners.")
    assert outline.title == "FastAPI in 90 Minutes"
    assert len(outline.modules) == 2
    assert outline.modules[0].lessons[0].type == "text"
    assert outline.modules[0].lessons[-1].type == "quiz"


async def test_generate_outline_retries_on_malformed_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # First reply is unparseable JSON (truncated); second is valid.
    prov = _install(
        monkeypatch,
        ["{not valid json,", json.dumps(_VALID_OUTLINE)],
    )
    outline = await ai_authoring.generate_outline("Teach FastAPI.")
    assert outline.title == "FastAPI in 90 Minutes"
    # Retry path: the model saw the assistant turn + a corrective
    # user turn quoting the error.
    assert len(prov.calls) == 2
    retry_messages = prov.calls[1]
    roles = [m.role for m in retry_messages]
    # The retry conversation always carries system + user + assistant
    # (the broken reply) + user (the corrective).
    assert roles == ["system", "user", "assistant", "user"]
    assert "could not be parsed" in retry_messages[-1].content


async def test_generate_outline_surfaces_failure_after_two_bad_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, ["not json", "still not json"])
    from app.core.errors import ValidationAppError

    with pytest.raises(ValidationAppError) as exc:
        await ai_authoring.generate_outline("Teach FastAPI.")
    assert exc.value.code == "ai.bad_output"


async def test_generate_outline_rejects_invalid_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Title is empty (violates min_length=1). The retry returns the
    # canonical valid outline so we exercise the recovery path.
    bad = {"title": "", "overview": "x", "modules": []}
    _install(monkeypatch, [json.dumps(bad), json.dumps(_VALID_OUTLINE)])
    outline = await ai_authoring.generate_outline("brief")
    assert outline.title == "FastAPI in 90 Minutes"


async def test_generate_outline_strips_markdown_fences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fenced = "```json\n" + json.dumps(_VALID_OUTLINE) + "\n```"
    _install(monkeypatch, [fenced])
    outline = await ai_authoring.generate_outline("brief")
    assert outline.modules[0].title == "Setup"


async def test_generate_lesson_body_returns_tiptap_doc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, [json.dumps(_VALID_LESSON_DOC)])
    doc = await ai_authoring.generate_lesson_body("Intro to FastAPI", "course about APIs")
    assert doc["type"] == "doc"
    assert isinstance(doc["content"], list)
    assert doc["content"][0]["type"] == "heading"


async def test_generate_quiz_returns_questions(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, [json.dumps(_VALID_QUIZ)])
    questions = await ai_authoring.generate_quiz(
        lesson_title="What is FastAPI?",
        course_context="course about APIs",
        n=2,
    )
    assert len(questions) == 2
    assert questions[0].id == "q1"
    assert questions[0].answer_keys == ["a"]


# ---------- HTTP-level ----------


async def _make_subject(db: AsyncSession) -> Subject:
    s = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _create_course(
    client: AsyncClient, headers: dict[str, str], subject_id: str
) -> str:
    r = await client.post(
        "/api/v1/courses",
        json={"title": "AI Draft", "subject_id": subject_id, "overview": "stub"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_outline_endpoint_returns_json(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = await auth_headers(role=Role.instructor)
    _install(monkeypatch, [json.dumps(_VALID_OUTLINE)])

    r = await client.post(
        "/api/v1/studio/ai/outline",
        json={"brief": "Teach FastAPI to absolute beginners.", "target_modules": 4},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "FastAPI in 90 Minutes"
    assert len(body["modules"]) == 2


async def test_outline_endpoint_requires_instructor(
    client: AsyncClient,
    auth_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    student = await auth_headers(role=Role.student)
    # Provider must never be called — the role guard rejects first.
    _install(monkeypatch, [])

    r = await client.post(
        "/api/v1/studio/ai/outline",
        json={"brief": "Teach FastAPI."},
        headers=student,
    )
    assert r.status_code == 403, r.text


async def test_lesson_body_endpoint_returns_blocks(
    client: AsyncClient,
    auth_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = await auth_headers(role=Role.instructor)
    _install(monkeypatch, [json.dumps(_VALID_LESSON_DOC)])

    r = await client.post(
        "/api/v1/studio/ai/lesson-body",
        json={"lesson_title": "Intro to FastAPI", "course_context": "course about APIs"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["blocks"]["type"] == "doc"


async def test_quiz_endpoint_returns_questions(
    client: AsyncClient,
    auth_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = await auth_headers(role=Role.instructor)
    _install(monkeypatch, [json.dumps(_VALID_QUIZ)])

    r = await client.post(
        "/api/v1/studio/ai/quiz",
        json={"lesson_title": "What is FastAPI?", "course_context": "ctx", "n": 2},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["questions"]) == 2


async def test_commit_outline_persists_modules_and_lessons(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_id = await _create_course(client, headers, subject.id)
    _install(monkeypatch, [])  # commit never calls the LLM

    r = await client.post(
        "/api/v1/studio/ai/commit-outline",
        json={"course_id": course_id, "outline": _VALID_OUTLINE},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["course_id"] == course_id
    assert len(body["modules"]) == 2
    # First module: 2 text + 1 quiz, ordered.
    first = body["modules"][0]
    assert first["title"] == "Setup"
    assert [lsn["type"] for lsn in first["lessons"]] == ["text", "text", "quiz"]
    assert [lsn["order"] for lsn in first["lessons"]] == [0, 1, 2]

    # Sanity check that the rows actually landed in the DB.
    from sqlalchemy import select

    mods = (
        (
            await db_session.execute(
                select(Module).where(Module.course_id == course_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(mods) == 2
    lessons = (
        (
            await db_session.execute(
                select(Lesson).where(Lesson.module_id == mods[0].id)
            )
        )
        .scalars()
        .all()
    )
    assert len(lessons) == 3
    quiz_lesson = next(lsn for lsn in lessons if lsn.type == LessonType.quiz)
    # Quiz placeholder has at least one valid question so the
    # publish-time minimum-content guard doesn't trip later.
    assert quiz_lesson.data["questions"][0]["id"] == "q1"


async def test_commit_outline_rejects_non_owner(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = await auth_headers(role=Role.instructor)
    other = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_id = await _create_course(client, owner, subject.id)
    _install(monkeypatch, [])

    r = await client.post(
        "/api/v1/studio/ai/commit-outline",
        json={"course_id": course_id, "outline": _VALID_OUTLINE},
        headers=other,
    )
    assert r.status_code == 403, r.text


async def test_outline_endpoint_is_rate_limited(
    client: AsyncClient,
    auth_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = await auth_headers(role=Role.instructor)
    # Six tries in a row — 5/minute lets through 5 and 429s the 6th.
    # Each call needs a fresh canned reply; we script seven so the
    # rate-limiter is the only thing that can stop us.
    _install(monkeypatch, [json.dumps(_VALID_OUTLINE)] * 7)

    last = None
    for _ in range(7):
        last = await client.post(
            "/api/v1/studio/ai/outline",
            json={"brief": "Teach me something."},
            headers=headers,
        )
    assert last is not None
    assert last.status_code == 429, last.text
    assert last.json()["error"]["code"] == "rate_limited"
