"""Phase E3 — multi-modal content ingest.

Turns a single URL (YouTube video, public Notion page, public Google
Doc) into a structured "draft course" the instructor can review and
commit into a real course.

The pipeline has three pieces:

1. ``detect_source(url)`` — cheap regex dispatch. We do this client-side
   too so the studio modal can show "Detected: YouTube" before the
   user clicks Preview.
2. One of ``extract_youtube`` / ``extract_notion`` / ``extract_google_docs``.
   Each one is responsible for hitting the source, getting the
   text-ish content out, splitting it into modules and lessons, and
   returning a typed :class:`IngestPayload`.
3. ``commit_payload`` — write the modules + lessons into a real course.

Auth posture for v1
-------------------

* **YouTube**: ``youtube-transcript-api`` scrapes the public transcript
  feed; no API key required, but YouTube can rate-limit per IP.
* **Notion**: the official integration token is required for *private*
  pages. v1 ships **public-page only**: we hit the public Notion HTML
  endpoint and parse the embedded ``__NEXT_DATA__`` /
  ``window.__INITIAL_STATE__`` blob. If the page is private the user
  sees a friendly error pointing at the public-page limitation, no
  partial draft.
* **Google Docs**: any "anyone with the link" doc exposes a plaintext
  export at ``/document/d/{id}/export?format=txt``. We hit that and
  split by visual heading patterns. Authenticated / Drive-private docs
  are out of scope for v1.

The extractors don't import their backing SDKs at module scope so the
unit tests can run without network and without the optional packages
installed — every extractor checks for its dependency at call time and
raises a clean :class:`ValidationAppError` if it's missing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.models.course import Lesson, LessonType, Module
from app.models.user import User
from app.repositories import courses as courses_repo

log = get_logger(__name__)


# ---------- Source detection ----------

SourceKind = Literal["youtube", "notion", "google_docs", "unknown"]

_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}
_NOTION_HOSTS = {"notion.so", "www.notion.so", "notion.site"}
_GOOGLE_DOCS_HOSTS = {"docs.google.com"}


def detect_source(url: str) -> SourceKind:
    """Return the source kind for a URL.

    Pure-function: no I/O, safe to call client-side from the studio
    modal as a `/preview` precheck. Empty / invalid URLs fall through
    to ``"unknown"`` rather than raising — the caller decides what to
    do with that.
    """
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return "unknown"
    host = (parsed.hostname or "").lower()
    if host in _YOUTUBE_HOSTS:
        return "youtube"
    # *.notion.site is a public-publish CNAME — match the suffix too.
    if host in _NOTION_HOSTS or host.endswith(".notion.site"):
        return "notion"
    if host in _GOOGLE_DOCS_HOSTS:
        # Google Docs share path is /document/d/{id}/...
        if "/document/" in parsed.path:
            return "google_docs"
    return "unknown"


# ---------- Typed payloads ----------


class LessonDraft(BaseModel):
    """One lesson in a draft course."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    # v1 keeps every ingested lesson as a text body — we don't try to
    # transcode YouTube into a Lumen-hosted video, we just link back to
    # the original via ``anchor`` and put the transcript in the body.
    type: Literal["text"] = "text"
    body: str = Field(default="", max_length=200_000)
    # Optional permalink back to the source (YouTube timestamp link,
    # Notion block anchor, Google Docs heading). Surfaced in the UI so
    # the learner can jump to the original.
    anchor: str | None = Field(default=None, max_length=500)


class ModuleDraft(BaseModel):
    """One module + its lessons in a draft course."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    lessons: list[LessonDraft] = Field(default_factory=list, max_length=200)


class IngestPayload(BaseModel):
    """The structured output of any extractor."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    source_url: str = Field(min_length=1, max_length=500)
    source: SourceKind
    modules: list[ModuleDraft] = Field(default_factory=list, max_length=50)


# ---------- YouTube ----------

_YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_youtube_video_id(url: str) -> str | None:
    """Pull the 11-char video id out of any of the YouTube URL shapes.

    Handles:
      * https://www.youtube.com/watch?v=XXX
      * https://youtu.be/XXX
      * https://www.youtube.com/embed/XXX
      * https://www.youtube.com/shorts/XXX
    """
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return None
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/", 1)[0]
        return candidate if _YOUTUBE_ID_RE.match(candidate) else None
    if host in _YOUTUBE_HOSTS:
        if parsed.path == "/watch":
            v = parse_qs(parsed.query).get("v", [None])[0]
            return v if v and _YOUTUBE_ID_RE.match(v) else None
        # /embed/{id}, /shorts/{id}, /v/{id}
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] in {"embed", "shorts", "v"}:
            candidate = parts[1]
            return candidate if _YOUTUBE_ID_RE.match(candidate) else None
    return None


@dataclass(slots=True)
class _TranscriptSegment:
    text: str
    start: float  # seconds


def _fetch_youtube_transcript(video_id: str) -> list[_TranscriptSegment]:
    """Pull the transcript via youtube-transcript-api.

    The package isn't a hard requirement at module-load time so dev
    machines without the optional dep can still import this module.
    Raises ValidationAppError on missing / disabled transcripts so
    the API can surface a clean 422 instead of a 500.
    """
    try:
        from youtube_transcript_api import (  # type: ignore[import-not-found]
            YouTubeTranscriptApi,
        )
    except ImportError as exc:  # pragma: no cover — dep is in pyproject
        raise ValidationAppError(
            "YouTube transcript dependency is not installed",
            code="ingest.youtube.missing_dep",
        ) from exc

    try:
        # youtube-transcript-api 1.x removed the
        # ``YouTubeTranscriptApi.get_transcript`` classmethod in favour
        # of the instance-method ``YouTubeTranscriptApi().fetch(...)``.
        # ``.fetch()`` returns a ``FetchedTranscript`` whose snippets
        # are ``FetchedTranscriptSnippet`` objects (``.text`` /
        # ``.start`` / ``.duration`` attributes, not dict keys). We
        # normalise via ``to_raw_data()`` so the rest of this function
        # — and any test that hands us a list-of-dicts stub — keeps
        # working without conditionals.
        fetched = YouTubeTranscriptApi().fetch(video_id)
        raw = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else fetched
    except Exception as exc:
        # The library raises a small zoo of exceptions
        # (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable…)
        # — all of them are "we can't pull a transcript for this
        # video" from the caller's POV. Collapse to a single 422.
        log.warning("youtube_transcript_failed", video_id=video_id, error=str(exc))
        raise ValidationAppError(
            "No transcript available for this video",
            code="ingest.youtube.no_transcript",
        ) from exc

    out: list[_TranscriptSegment] = []
    for entry in raw:
        # ``raw`` is either a list[dict] (test stubs, or
        # ``.to_raw_data()`` output) or — in case a future library
        # version changes the shape again — a list of objects exposing
        # ``.text`` / ``.start`` attributes. Support both.
        if isinstance(entry, dict):
            text = str(entry.get("text", "")).strip()
            start = float(entry.get("start", 0.0))
        else:
            text = str(getattr(entry, "text", "")).strip()
            start = float(getattr(entry, "start", 0.0))
        out.append(_TranscriptSegment(text=text, start=start))
    return out


def _chunk_transcript(
    segments: list[_TranscriptSegment], *, target_seconds: float = 240.0
) -> list[tuple[float, str]]:
    """Group transcript segments into ~target_seconds chunks.

    Returns a list of ``(chunk_start_seconds, prose)`` tuples.
    Empty input returns an empty list.
    """
    if not segments:
        return []
    chunks: list[tuple[float, str]] = []
    cur_start: float = segments[0].start
    cur_pieces: list[str] = []
    for seg in segments:
        if seg.start - cur_start >= target_seconds and cur_pieces:
            chunks.append((cur_start, " ".join(cur_pieces).strip()))
            cur_start = seg.start
            cur_pieces = []
        if seg.text:
            cur_pieces.append(seg.text)
    if cur_pieces:
        chunks.append((cur_start, " ".join(cur_pieces).strip()))
    return chunks


def _fetch_youtube_title(video_id: str) -> str | None:
    """Best-effort title fetch via oEmbed (no API key needed).

    Returns ``None`` on any failure — the caller falls back to
    "YouTube video {id}" so a flaky network never blocks ingest.
    """
    try:
        r = httpx.get(
            "https://www.youtube.com/oembed",
            params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"},
            timeout=5.0,
        )
        r.raise_for_status()
        title = r.json().get("title")
        return str(title) if title else None
    except Exception:  # pragma: no cover - network dependent
        return None


def extract_youtube(url: str) -> IngestPayload:
    """Turn a YouTube URL into a draft course.

    Strategy:
      * One module per video (the video *is* the course unit).
      * ~4-minute lesson chunks, each anchored to a deep link
        (``?t={seconds}``) so a learner can jump to the right
        timestamp.
      * Each lesson body is the chunked transcript prose.
    """
    video_id = extract_youtube_video_id(url)
    if not video_id:
        raise ValidationAppError(
            "Could not parse a YouTube video id from the URL",
            code="ingest.youtube.bad_url",
        )

    segments = _fetch_youtube_transcript(video_id)
    chunks = _chunk_transcript(segments)
    if not chunks:
        raise ValidationAppError(
            "Transcript was empty",
            code="ingest.youtube.empty_transcript",
        )

    title = _fetch_youtube_title(video_id) or f"YouTube video {video_id}"
    base_watch = f"https://www.youtube.com/watch?v={video_id}"

    lessons: list[LessonDraft] = []
    for i, (start, body) in enumerate(chunks, start=1):
        ts = int(start)
        lesson_title = _summarise_first_words(body, fallback=f"Part {i}", max_words=8)
        lessons.append(
            LessonDraft(
                title=f"{i:02d}. {lesson_title}",
                type="text",
                body=body,
                anchor=f"{base_watch}&t={ts}s",
            )
        )

    return IngestPayload(
        title=title,
        source_url=url,
        source="youtube",
        modules=[ModuleDraft(title=title, lessons=lessons)],
    )


def _summarise_first_words(text: str, *, fallback: str, max_words: int = 8) -> str:
    """Cheap fallback title generator — first N words of the chunk.

    The spec calls for the LLM to suggest titles when an LLM client is
    available; until E1/E2's ``app/services/llm.py`` exists, we use
    this heuristic. It keeps the ingest pipeline deterministic for
    tests and avoids hitting an external service for every chunk.
    """
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return fallback
    words = cleaned.split()
    snippet = " ".join(words[:max_words])
    # Strip trailing punctuation for nicer titles.
    snippet = snippet.rstrip(",.;:!?-")
    return snippet[:160] or fallback


# ---------- Notion ----------


# Notion-style page slugs end in a 32-char hex page id. Capture both
# the bare /<id> shape and the more common /<slug-id> shape.
_NOTION_ID_RE = re.compile(r"([0-9a-f]{32})", re.IGNORECASE)


def extract_notion_page_id(url: str) -> str | None:
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return None
    # The id is always the *last* 32 hex chars of the path's final
    # segment. Notion accepts dashed or undashed ids in URLs.
    path = parsed.path.rstrip("/")
    if not path:
        return None
    last_segment = path.split("/")[-1]
    # Drop dashes, then read only the trailing 32 chars — anchoring
    # to the end avoids matching an earlier accidental hex run in a
    # slug (e.g. "Public-Page-..." starts with the hex chars of
    # "Pageabcdef…" so a leading search picks up too far back).
    candidate = last_segment.replace("-", "")
    if len(candidate) < 32:
        return None
    tail = candidate[-32:]
    return tail.lower() if _NOTION_ID_RE.fullmatch(tail) else None


def _fetch_notion_blocks(page_id: str) -> list[dict]:
    """Walk a public Notion page's block tree.

    Uses the official ``notion-client`` when ``NOTION_TOKEN`` is set,
    otherwise raises a clean error. v1 ships token-based-only; the
    "no-token public scraping fallback" path the spec hints at is
    intentionally deferred — public Notion pages don't ship a stable
    HTML structure, and parsing the ``__NEXT_DATA__`` blob is fragile
    enough that we'd rather degrade explicitly. See ADR-pending.
    """
    try:
        from notion_client import Client as NotionClient  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        raise ValidationAppError(
            "Notion ingest dependency is not installed",
            code="ingest.notion.missing_dep",
        ) from exc

    from app.core.config import get_settings

    secret = getattr(get_settings(), "notion_token", None)
    token = secret.get_secret_value() if secret is not None else ""
    if not token:
        raise ValidationAppError(
            "Notion ingest requires NOTION_TOKEN to be set on the server",
            code="ingest.notion.no_token",
        )

    client = NotionClient(auth=token)
    blocks: list[dict] = []
    cursor: str | None = None
    while True:
        kwargs: dict = {"block_id": page_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = client.blocks.children.list(**kwargs)
        results = resp.get("results", []) if isinstance(resp, dict) else []
        blocks.extend(results)
        if not (isinstance(resp, dict) and resp.get("has_more")):
            break
        cursor = resp.get("next_cursor") if isinstance(resp, dict) else None
        if not cursor:
            break
    return blocks


def _notion_block_text(block: dict) -> str:
    """Flatten a single block's rich-text array into plain text."""
    if not isinstance(block, dict):
        return ""
    btype = block.get("type")
    if not isinstance(btype, str):
        return ""
    payload = block.get(btype)
    if not isinstance(payload, dict):
        return ""
    rich = payload.get("rich_text") or payload.get("title") or []
    if not isinstance(rich, list):
        return ""
    return "".join(
        str(piece.get("plain_text", "")) for piece in rich if isinstance(piece, dict)
    )


def _notion_blocks_to_modules(blocks: Iterable[dict]) -> list[ModuleDraft]:
    """Group blocks into modules at H1, lessons at H2, body otherwise.

    If the page has no H1, the whole page becomes a single module
    titled "Content". H2-less content within a module collapses into
    a single "Introduction" lesson.
    """
    modules: list[ModuleDraft] = []
    cur_module: ModuleDraft | None = None
    cur_lesson_title: str | None = None
    cur_lesson_body: list[str] = []

    def _flush_lesson() -> None:
        nonlocal cur_lesson_title, cur_lesson_body
        if cur_module is None:
            return
        body = "\n\n".join(s.strip() for s in cur_lesson_body if s.strip()).strip()
        title = cur_lesson_title or "Introduction"
        if body or cur_lesson_title:
            cur_module.lessons.append(
                LessonDraft(title=title[:200], type="text", body=body[:200_000])
            )
        cur_lesson_title = None
        cur_lesson_body = []

    def _ensure_module(title: str) -> None:
        nonlocal cur_module
        _flush_lesson()
        cur_module = ModuleDraft(title=title[:200], lessons=[])
        modules.append(cur_module)

    for block in blocks:
        btype = block.get("type") if isinstance(block, dict) else None
        text = _notion_block_text(block) if isinstance(block, dict) else ""
        if btype == "heading_1":
            _ensure_module(text or "Section")
        elif btype == "heading_2":
            if cur_module is None:
                _ensure_module("Content")
            _flush_lesson()
            cur_lesson_title = text or "Lesson"
        else:
            if cur_module is None:
                _ensure_module("Content")
            if text:
                cur_lesson_body.append(text)
    _flush_lesson()

    # Drop empty modules so the preview tree isn't littered with stubs.
    return [m for m in modules if m.lessons]


def extract_notion(url: str) -> IngestPayload:
    page_id = extract_notion_page_id(url)
    if not page_id:
        raise ValidationAppError(
            "Could not parse a Notion page id from the URL",
            code="ingest.notion.bad_url",
        )
    blocks = _fetch_notion_blocks(page_id)
    modules = _notion_blocks_to_modules(blocks)
    if not modules:
        raise ValidationAppError(
            "Notion page contained no extractable content",
            code="ingest.notion.empty",
        )
    # First H1 wins as the course title; otherwise fall back to the
    # first module title.
    title = modules[0].title or "Notion import"
    return IngestPayload(
        title=title[:200],
        source_url=url,
        source="notion",
        modules=modules,
    )


# ---------- Google Docs ----------


def extract_google_docs_id(url: str) -> str | None:
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    # Expected shape: /document/d/{id}/edit (or /view, or no trailing).
    if len(parts) >= 3 and parts[0] == "document" and parts[1] == "d":
        candidate = parts[2]
        # Google Docs ids are alphanumeric + dash + underscore, 20-100ish chars.
        if re.match(r"^[A-Za-z0-9_-]{20,120}$", candidate):
            return candidate
    return None


def _fetch_google_docs_text(doc_id: str) -> str:
    """Fetch the plaintext export of a public Google Doc.

    The export endpoint returns 200 + UTF-8 text for any "anyone with
    the link" doc, no auth required. Private docs return 401/403 (we
    surface that as a 422 with a clean error code).
    """
    export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    try:
        r = httpx.get(export_url, timeout=10.0, follow_redirects=True)
    except Exception as exc:
        log.warning("google_docs_fetch_failed", doc_id=doc_id, error=str(exc))
        raise ValidationAppError(
            "Could not reach Google Docs",
            code="ingest.google_docs.fetch_failed",
        ) from exc
    if r.status_code in (401, 403):
        raise ValidationAppError(
            "Google Doc is private — share with 'anyone with the link'",
            code="ingest.google_docs.private",
        )
    if r.status_code >= 400:
        raise ValidationAppError(
            f"Google Docs returned HTTP {r.status_code}",
            code="ingest.google_docs.http_error",
        )
    # Google Docs export sometimes returns UTF-8 with a BOM.
    return r.text.lstrip("﻿")


_HEADING_LINE_RE = re.compile(r"^\s*([A-Z][^a-z\n]{2,})\s*$")


def _split_google_docs_text(text: str) -> list[ModuleDraft]:
    """Split a plaintext Google Doc into modules + lessons.

    Google's plaintext export doesn't preserve heading levels — it
    just hands us paragraphs separated by blank lines. We use a
    heuristic: a SHORT line of mostly-uppercase text is a section
    header (module title); the surrounding paragraphs become a
    lesson. If no headers are detected the whole doc becomes one
    module of one lesson.
    """
    raw_lines = text.split("\n")
    modules: list[ModuleDraft] = []
    cur_module: ModuleDraft | None = None
    cur_lesson_buf: list[str] = []
    cur_lesson_title: str | None = None

    def _flush_lesson() -> None:
        nonlocal cur_lesson_buf, cur_lesson_title
        if cur_module is None or (not cur_lesson_buf and not cur_lesson_title):
            cur_lesson_buf = []
            cur_lesson_title = None
            return
        body = "\n\n".join(s.strip() for s in cur_lesson_buf if s.strip()).strip()
        title = cur_lesson_title or "Section"
        cur_module.lessons.append(
            LessonDraft(title=title[:200], type="text", body=body[:200_000])
        )
        cur_lesson_buf = []
        cur_lesson_title = None

    def _start_module(title: str) -> None:
        nonlocal cur_module
        _flush_lesson()
        cur_module = ModuleDraft(title=title[:200], lessons=[])
        modules.append(cur_module)

    # First pass: walk paragraphs, splitting on blank-line boundaries.
    paragraphs: list[str] = []
    buf: list[str] = []
    for ln in raw_lines:
        if ln.strip():
            buf.append(ln.rstrip())
        elif buf:
            paragraphs.append("\n".join(buf))
            buf = []
    if buf:
        paragraphs.append("\n".join(buf))

    for para in paragraphs:
        line = para.strip()
        first_line, _, rest = para.partition("\n")
        first_line = first_line.strip()
        # ALL-CAPS short solo paragraph ⇒ module-level heading.
        if (
            len(line) <= 100
            and "\n" not in line
            and _HEADING_LINE_RE.match(line)
        ):
            _start_module(line.title())
            continue
        # A paragraph whose first line is short and ends with a colon
        # is a lesson-level heading. Anything after the colon on
        # subsequent lines becomes the lesson body.
        if len(first_line) <= 80 and first_line.endswith(":"):
            if cur_module is None:
                _start_module("Content")
            _flush_lesson()
            cur_lesson_title = first_line.rstrip(":").strip()
            if rest.strip():
                cur_lesson_buf.append(rest)
            continue
        if cur_module is None:
            _start_module("Content")
        cur_lesson_buf.append(para)
    _flush_lesson()

    return [m for m in modules if m.lessons]


def extract_google_docs(url: str) -> IngestPayload:
    doc_id = extract_google_docs_id(url)
    if not doc_id:
        raise ValidationAppError(
            "Could not parse a Google Docs id from the URL",
            code="ingest.google_docs.bad_url",
        )
    text = _fetch_google_docs_text(doc_id)
    text = text.strip()
    if not text:
        raise ValidationAppError(
            "Google Doc was empty",
            code="ingest.google_docs.empty",
        )
    modules = _split_google_docs_text(text)
    if not modules:
        # No headings detected and the doc isn't empty — drop the
        # whole body into a single lesson.
        modules = [
            ModuleDraft(
                title="Content",
                lessons=[
                    LessonDraft(title="Content", type="text", body=text[:200_000])
                ],
            )
        ]
    # First line is the conventional doc title.
    first_line = text.splitlines()[0].strip() if text else ""
    title = (first_line[:200] if first_line else "Google Docs import") or "Google Docs import"
    return IngestPayload(
        title=title,
        source_url=url,
        source="google_docs",
        modules=modules,
    )


# ---------- Public entry point ----------


def ingest(url: str) -> IngestPayload:
    """Dispatch a URL to the right extractor.

    The caller (the API handler) is responsible for rate-limiting and
    auth — this function is pure-business-logic and can be unit-tested
    without FastAPI.
    """
    kind = detect_source(url)
    if kind == "youtube":
        return extract_youtube(url)
    if kind == "notion":
        return extract_notion(url)
    if kind == "google_docs":
        return extract_google_docs(url)
    raise ValidationAppError(
        "Unsupported source URL — accepted: YouTube, Notion, Google Docs",
        code="ingest.unsupported_source",
        details={"url": url},
    )


# ---------- Commit ----------


async def commit_payload(
    db: AsyncSession,
    *,
    course_id: str,
    owner: User,
    payload: IngestPayload,
) -> dict[str, int]:
    """Materialise a draft payload into real modules + lessons.

    The caller owns auth; we re-check it here so a malicious or buggy
    caller can't escalate by skipping the deps. Modules are appended
    after any existing modules; lesson order starts at 0 within each
    new module.

    Returns a small counts dict so the API can report
    ``{"modules": 3, "lessons": 12}`` without re-fetching the course.
    """
    course = await courses_repo.get_course(db, course_id)
    if course is None:
        raise NotFoundError("Course not found", code="course.not_found")
    if not (owner.is_admin() or course.owner_id == owner.id):
        raise ForbiddenError("Not your course", code="course.forbidden")

    next_module_order = await courses_repo.next_module_order(db, course.id)

    module_count = 0
    lesson_count = 0

    for m_idx, mdraft in enumerate(payload.modules):
        mod = Module(
            course_id=course.id,
            title=mdraft.title.strip()[:200],
            description="",
            order=next_module_order + m_idx,
        )
        db.add(mod)
        await db.flush()
        module_count += 1
        for l_idx, ldraft in enumerate(mdraft.lessons):
            body = ldraft.body or ""
            if ldraft.anchor:
                # Surface the source link at the top of the lesson body
                # so the learner has a one-click jump back to the
                # original (YouTube timestamp, etc.).
                body = f"[Open source]({ldraft.anchor})\n\n{body}".strip()
            lesson = Lesson(
                module_id=mod.id,
                title=ldraft.title.strip()[:200],
                type=LessonType.text,
                order=l_idx,
                duration_seconds=None,
                is_preview=False,
                data={"type": "text", "body_markdown": body or "(empty)"},
            )
            db.add(lesson)
            lesson_count += 1
        await db.flush()

    return {"modules": module_count, "lessons": lesson_count}


# Re-export for `from app.services.content_ingest import detect_source`
__all__ = [
    "IngestPayload",
    "LessonDraft",
    "ModuleDraft",
    "SourceKind",
    "commit_payload",
    "detect_source",
    "extract_google_docs",
    "extract_google_docs_id",
    "extract_notion",
    "extract_notion_page_id",
    "extract_youtube",
    "extract_youtube_video_id",
    "ingest",
]
