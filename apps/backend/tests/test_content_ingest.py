"""Phase E3 — content-ingest service + API tests.

We never call any external service. Every extractor is exercised
through a monkeypatched fetcher so the suite stays hermetic. The
endpoint tests cover detection, preview, and commit; the unit tests
cover URL parsing, chunking, and the three source-specific block →
draft transformations.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course, CourseStatus, Difficulty, Subject
from app.models.user import Role, User
from app.services import content_ingest

# ---------- detect_source ----------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
        ("https://youtu.be/dQw4w9WgXcQ", "youtube"),
        ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "youtube"),
        ("https://www.notion.so/Some-Page-abcdef0123456789abcdef0123456789", "notion"),
        ("https://docs.google.com/document/d/abc123_-xyz9876543210/edit", "google_docs"),
        ("https://example.com/random", "unknown"),
        ("not even a url", "unknown"),
        ("", "unknown"),
    ],
)
def test_detect_source(url: str, expected: str) -> None:
    assert content_ingest.detect_source(url) == expected


# ---------- URL parsers ----------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch?v=tooshort", None),
        ("https://www.youtube.com/feed/trending", None),
    ],
)
def test_extract_youtube_video_id(url: str, expected: str | None) -> None:
    assert content_ingest.extract_youtube_video_id(url) == expected


def test_extract_notion_page_id_handles_dashed_and_undashed() -> None:
    dashed = "https://www.notion.so/Public-Page-abcdef01-2345-6789-abcd-ef0123456789"
    assert content_ingest.extract_notion_page_id(dashed) == "abcdef0123456789abcdef0123456789"
    undashed = "https://www.notion.so/abcdef0123456789abcdef0123456789"
    assert content_ingest.extract_notion_page_id(undashed) == "abcdef0123456789abcdef0123456789"


def test_extract_google_docs_id() -> None:
    url = "https://docs.google.com/document/d/abc123_-XYZ9876543210/edit?usp=sharing"
    assert content_ingest.extract_google_docs_id(url) == "abc123_-XYZ9876543210"
    assert content_ingest.extract_google_docs_id("https://docs.google.com/spreadsheets/d/x") is None


# ---------- Chunker ----------


def test_chunk_transcript_groups_into_target_windows() -> None:
    segments = [
        content_ingest._TranscriptSegment(text=f"line {i}", start=float(i * 60)) for i in range(15)
    ]
    chunks = content_ingest._chunk_transcript(segments, target_seconds=240.0)
    # 15 minutes / 4 minutes ≈ 4 chunks
    assert len(chunks) >= 3
    # First chunk anchors at the first segment.
    assert chunks[0][0] == 0.0
    # No empty chunks.
    assert all(text.strip() for _, text in chunks)


def test_chunk_transcript_empty() -> None:
    assert content_ingest._chunk_transcript([]) == []


# ---------- YouTube extractor ----------


def _fake_youtube_segments() -> list[dict[str, Any]]:
    """A synthetic ~12-minute transcript for mocking."""
    return [
        {"text": f"sentence number {i}.", "start": float(i * 30), "duration": 30.0}
        for i in range(24)
    ]


def test_extract_youtube_builds_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end through ``extract_youtube`` with the HTTP layer mocked."""

    # youtube-transcript-api 1.x switched to an instance-method API:
    # ``YouTubeTranscriptApi().fetch(video_id)`` returns an object
    # exposing ``.to_raw_data()`` -> list[dict[text/start/duration]].
    # The fake class mirrors that shape so the production code path
    # under test runs unchanged.
    class _FakeFetchedTranscript:
        def __init__(self, segments: list[dict[str, Any]]) -> None:
            self._segments = segments

        def to_raw_data(self) -> list[dict[str, Any]]:
            return self._segments

    fake_api_class = type(
        "FakeYouTubeTranscriptApi",
        (),
        {"fetch": lambda self, video_id: _FakeFetchedTranscript(_fake_youtube_segments())},
    )
    # The function does ``from youtube_transcript_api import YouTubeTranscriptApi``
    # at call time, so monkeypatch the symbol on the (possibly real)
    # module — and if the module isn't installed, register a stub.
    import sys
    import types

    if "youtube_transcript_api" not in sys.modules:
        sys.modules["youtube_transcript_api"] = types.ModuleType("youtube_transcript_api")
    sys.modules["youtube_transcript_api"].YouTubeTranscriptApi = fake_api_class  # type: ignore[attr-defined]

    # Skip the oEmbed network call.
    monkeypatch.setattr(content_ingest, "_fetch_youtube_title", lambda vid: "Fake video")

    payload = content_ingest.extract_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert payload.source == "youtube"
    assert payload.title == "Fake video"
    assert len(payload.modules) == 1
    mod = payload.modules[0]
    assert mod.lessons, "must produce at least one lesson"
    for lesson in mod.lessons:
        # Every lesson must carry the timestamp anchor.
        assert lesson.anchor and "&t=" in lesson.anchor
        assert lesson.type == "text"
        assert lesson.title.startswith(("01", "02", "03", "04", "05", "06", "07", "08", "09"))


def test_extract_youtube_bad_url_raises() -> None:
    from app.core.errors import ValidationAppError

    with pytest.raises(ValidationAppError) as exc:
        content_ingest.extract_youtube("https://www.youtube.com/feed/library")
    assert exc.value.code == "ingest.youtube.bad_url"


# ---------- Notion extractor ----------


def _fake_notion_blocks() -> list[dict[str, Any]]:
    """A mini Notion tree: 1 H1 → 2 H2 → 2 paragraphs each."""

    def block(btype: str, text: str) -> dict[str, Any]:
        return {
            "type": btype,
            btype: {"rich_text": [{"plain_text": text}]},
        }

    return [
        block("heading_1", "Intro to Foo"),
        block("heading_2", "Why Foo"),
        block("paragraph", "Foo exists because of bar."),
        block("paragraph", "Bar would not exist without foo."),
        block("heading_2", "How Foo Works"),
        block("paragraph", "Foo operates by inspecting bar."),
    ]


def test_extract_notion_builds_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(content_ingest, "_fetch_notion_blocks", lambda pid: _fake_notion_blocks())
    payload = content_ingest.extract_notion(
        "https://www.notion.so/Some-abcdef0123456789abcdef0123456789"
    )
    assert payload.source == "notion"
    assert payload.title == "Intro to Foo"
    assert len(payload.modules) == 1
    mod = payload.modules[0]
    assert mod.title == "Intro to Foo"
    titles = [l.title for l in mod.lessons]
    assert "Why Foo" in titles
    assert "How Foo Works" in titles


def test_extract_notion_bad_url_raises() -> None:
    from app.core.errors import ValidationAppError

    with pytest.raises(ValidationAppError) as exc:
        content_ingest.extract_notion("https://www.notion.so/")
    assert exc.value.code == "ingest.notion.bad_url"


# ---------- Google Docs extractor ----------


_SAMPLE_GOOGLE_DOC = """Welcome to the example doc

INTRODUCTION

This is the introduction paragraph of the document.
It spans several lines but it's one paragraph.

CHAPTER ONE

Setup:
Step one is to install everything.

Practice:
Step two is to practice every day.

CHAPTER TWO

A second chapter follows the first.
"""


def test_extract_google_docs_splits_by_caps_headings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(content_ingest, "_fetch_google_docs_text", lambda did: _SAMPLE_GOOGLE_DOC)
    payload = content_ingest.extract_google_docs(
        "https://docs.google.com/document/d/abc123_-XYZ9876543210/edit"
    )
    assert payload.source == "google_docs"
    titles = [m.title for m in payload.modules]
    # Title-cased version of the all-caps headings.
    assert "Introduction" in titles
    assert "Chapter One" in titles
    assert "Chapter Two" in titles
    # Lesson sub-headings inside Chapter One detected by ``:`` rule.
    ch1 = next(m for m in payload.modules if m.title == "Chapter One")
    lesson_titles = [l.title for l in ch1.lessons]
    assert "Setup" in lesson_titles
    assert "Practice" in lesson_titles


def test_extract_google_docs_no_headings_one_lesson(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        content_ingest,
        "_fetch_google_docs_text",
        lambda did: "just a single block of text that has no headings whatsoever.",
    )
    payload = content_ingest.extract_google_docs(
        "https://docs.google.com/document/d/abc123_-XYZ9876543210/edit"
    )
    assert len(payload.modules) == 1
    assert len(payload.modules[0].lessons) == 1


# ---------- Dispatch ----------


def test_ingest_unknown_source_raises() -> None:
    from app.core.errors import ValidationAppError

    with pytest.raises(ValidationAppError) as exc:
        content_ingest.ingest("https://example.com/not-supported")
    assert exc.value.code == "ingest.unsupported_source"


# ---------- API: /studio/ingest/* ----------
#
# S1.7 / DR-M12 / FR-SEC-02: the ingest routes moved off RequireInstructor to
# RequireIngestUrl — they are now CLOSED by construction (admin-only AND the
# global `ingest_url_enabled` flag, default OFF). The role collapse does NOT
# open the SSRF surface. The happy-path tests therefore run as an admin with
# the flag flipped on; the negative tests assert the closed posture.

from app.core.config import get_settings


@pytest.fixture
def ingest_enabled(monkeypatch: pytest.MonkeyPatch):
    """Turn the global `ingest_url_enabled` flag ON for one test.

    conftest force-clears the Settings cache after env overrides; we mirror
    that so the dependency reads the flipped flag.
    """
    monkeypatch.setenv("INGEST_URL_ENABLED", "true")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


async def _admin_headers(auth_headers) -> dict[str, str]:
    return await auth_headers(role=Role.admin)


async def _make_subject(db: AsyncSession) -> Subject:
    s = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _make_course(db: AsyncSession, owner: User, subject: Subject) -> Course:
    course = Course(
        owner_id=owner.id,
        subject_id=subject.id,
        title="Hello",
        slug=f"hello-{uuid.uuid4().hex[:6]}",
        overview="x",
        difficulty=Difficulty.beginner,
        status=CourseStatus.draft,
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course


async def test_detect_endpoint_open_for_admin_when_flag_on(
    client: AsyncClient, auth_headers, ingest_enabled
) -> None:
    # S1.7: admin + INGEST_URL_ENABLED=true reaches the handler.
    headers = await _admin_headers(auth_headers)
    r = await client.post(
        "/api/v1/studio/ingest/detect",
        json={"url": "https://youtu.be/dQw4w9WgXcQ"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"source": "youtube"}


async def test_ingest_closed_for_regular_user(client: AsyncClient, auth_headers) -> None:
    # S1.7 / FR-SEC-02 negative test: an active `user`-role caller is denied
    # even though authoring is otherwise ungated — ingest stays admin-only.
    headers = await auth_headers(role=Role.user)
    r = await client.post(
        "/api/v1/studio/ingest/detect",
        json={"url": "https://youtu.be/dQw4w9WgXcQ"},
        headers=headers,
    )
    assert r.status_code == 403
    body = r.json()["error"]
    assert body["code"] == "auth.capability"
    assert body["details"]["capability"] == "can_ingest_url"


async def test_ingest_closed_for_admin_when_flag_off(client: AsyncClient, auth_headers) -> None:
    # S1.7: even an admin is denied while the flag is OFF (the default).
    headers = await _admin_headers(auth_headers)
    r = await client.post(
        "/api/v1/studio/ingest/detect",
        json={"url": "https://youtu.be/dQw4w9WgXcQ"},
        headers=headers,
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "auth.capability"
    assert r.json()["error"]["details"]["capability"] == "can_ingest_url"


async def test_preview_endpoint_uses_extractor(
    client: AsyncClient,
    auth_headers,
    ingest_enabled,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The route delegates to ``content_ingest.ingest``; replace it
    with a small fake so the test doesn't depend on the upstream."""

    fake_payload = content_ingest.IngestPayload(
        title="Mocked",
        source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        source="youtube",
        modules=[
            content_ingest.ModuleDraft(
                title="m1",
                lessons=[
                    content_ingest.LessonDraft(title="l1", type="text", body="hi", anchor=None)
                ],
            )
        ],
    )
    # The route imports ``ingest`` at module load → patch it on the
    # endpoint module's namespace, not the service module.
    from app.api.v1 import content_ingest as endpoint_mod

    monkeypatch.setattr(endpoint_mod, "ingest", lambda url: fake_payload)

    headers = await _admin_headers(auth_headers)
    r = await client.post(
        "/api/v1/studio/ingest/preview",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "Mocked"
    assert body["source"] == "youtube"
    assert len(body["modules"]) == 1
    assert body["modules"][0]["lessons"][0]["title"] == "l1"


async def test_preview_unsupported_url_returns_422(
    client: AsyncClient, auth_headers, ingest_enabled
) -> None:
    headers = await _admin_headers(auth_headers)
    r = await client.post(
        "/api/v1/studio/ingest/preview",
        json={"url": "https://example.com/whatever"},
        headers=headers,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "ingest.unsupported_source"


async def test_commit_creates_modules_and_lessons(
    client: AsyncClient, auth_headers, make_user, ingest_enabled, db_session: AsyncSession
) -> None:
    """End-to-end: commit a 2-module, 3-lesson payload and verify the
    syllabus reflects it. Runs as admin with the ingest flag on (S1.7)."""
    headers = await _admin_headers(auth_headers)
    me = await client.get("/api/v1/auth/me", headers=headers)
    owner_id = me.json()["id"]
    owner = await db_session.get(User, owner_id)
    assert owner is not None

    subject = await _make_subject(db_session)
    course = await _make_course(db_session, owner, subject)

    payload = {
        "course_id": course.id,
        "payload": {
            "title": "Imported",
            "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "source": "youtube",
            "modules": [
                {
                    "title": "Chapter A",
                    "lessons": [
                        {"title": "Intro", "type": "text", "body": "alpha", "anchor": None},
                        {"title": "Mid", "type": "text", "body": "beta", "anchor": "https://x/y"},
                    ],
                },
                {
                    "title": "Chapter B",
                    "lessons": [
                        {"title": "End", "type": "text", "body": "gamma", "anchor": None},
                    ],
                },
            ],
        },
    }
    r = await client.post("/api/v1/studio/ingest/commit", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["modules"] == 2
    assert body["lessons"] == 3
    assert body["course_id"] == course.id

    # Re-fetch the course detail and check.
    detail = await client.get(f"/api/v1/courses/{course.id}", headers=headers)
    assert detail.status_code == 200, detail.text
    dbody = detail.json()
    mod_titles = [m["title"] for m in dbody["modules"]]
    assert "Chapter A" in mod_titles
    assert "Chapter B" in mod_titles
    chapter_a = next(m for m in dbody["modules"] if m["title"] == "Chapter A")
    assert {l["title"] for l in chapter_a["lessons"]} == {"Intro", "Mid"}
    mid = next(l for l in chapter_a["lessons"] if l["title"] == "Mid")
    # Anchor was prepended to body markdown.
    assert "https://x/y" in mid["data"]["body_markdown"]


async def test_commit_closed_for_regular_user(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
) -> None:
    """S1.7: the commit route is closed to non-admins (RequireIngestUrl).

    Previously this asserted instructor-B-cannot-commit-into-A's-course; with
    the role collapse, ingest is admin-only and admins bypass ownership, so
    the only reachable denial on `/commit` is the capability gate itself.
    """
    owner_a = await make_user(role=Role.user)
    subject = await _make_subject(db_session)
    course = await _make_course(db_session, owner_a, subject)

    user_b = await auth_headers(role=Role.user)
    payload = {
        "course_id": course.id,
        "payload": {
            "title": "x",
            "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "source": "youtube",
            "modules": [{"title": "m", "lessons": [{"title": "l", "type": "text", "body": "b"}]}],
        },
    }
    r = await client.post("/api/v1/studio/ingest/commit", json=payload, headers=user_b)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "auth.capability"


async def test_commit_unknown_course_returns_404(
    client: AsyncClient, auth_headers, ingest_enabled
) -> None:
    headers = await _admin_headers(auth_headers)
    payload = {
        "course_id": "does-not-exist",
        "payload": {
            "title": "x",
            "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "source": "youtube",
            "modules": [{"title": "m", "lessons": [{"title": "l", "type": "text", "body": "b"}]}],
        },
    }
    r = await client.post("/api/v1/studio/ingest/commit", json=payload, headers=headers)
    assert r.status_code == 404
