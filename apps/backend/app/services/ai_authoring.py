"""AI-assisted course-authoring service.

Rebuild Phase E2. The instructor pastes a one-paragraph brief (or a
bullet outline) and asks the assistant to scaffold a course. The
service exposes three "generate" surfaces — outline, lesson body,
and quiz — plus a "commit" path that persists the generated outline
into an existing course as drafts. **None of the generate calls
touch the database**: nothing is written until the instructor
reviews the preview and explicitly hits commit.

Why human-in-the-loop. The LLM hallucinates. An instructor who
publishes anything the model spat out unedited would ship factual
errors with their name attached. Every call returns a *draft* —
modules + lessons stay marked draft on the course, and the lesson
bodies / quiz questions surface in an editable preview before the
instructor confirms. Editing inline, deleting items they don't
like, and accepting only the bits worth keeping is the expected
workflow; the API is shaped to support that, not full automation.

Error model. The LLM occasionally emits malformed JSON even with a
strict system prompt — a stray trailing comma, prose mixed in, an
unbalanced quote. We try once, parse strictly, and on failure send
a second turn back with the parse error and ask for a clean retry.
After two failures we surface ``ValidationAppError("ai.bad_output")``
so the UI can show a clear "try again" message rather than leaking
the broken text.

Coordination with E1. The :func:`app.services.llm.get_provider`
contract is shared with Phase E1's RAG tutor. This module imports
the protocol + ``ChatMessage`` only; concrete providers stay behind
the settings selector so swapping providers (Anthropic ↔ OpenAI ↔
noop) at the env layer re-routes both authoring and tutor traffic
in one place.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationAppError
from app.core.logging import get_logger
from app.models.course import Course, Lesson, LessonType, Module
from app.models.llm_call import SYSTEM_USER_ID
from app.models.user import User
from app.repositories import courses as courses_repo
from app.schemas.course import QuizQuestion
from app.services import llm as llm_service
from app.services.courses import _owned_course
from app.services.llm_call_log import call_logged

log = get_logger(__name__)


# ---------- Schemas (LLM output, also surfaced on the wire) ----------


class OutlineLesson(BaseModel):
    """One lesson title + its kind in the generated outline.

    We constrain ``type`` to ``text`` or ``quiz`` only. The LLM can't
    invent a video URL or upload an image, so allowing those types in
    the outline would just create empty stubs the instructor has to
    delete. Adding multi-media lessons stays a deliberate
    instructor-driven action.
    """

    title: str = Field(min_length=1, max_length=200)
    type: str = Field(pattern="^(text|quiz)$")


class OutlineModule(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    lessons: list[OutlineLesson] = Field(min_length=1, max_length=10)


class CourseOutline(BaseModel):
    """Top-level outline the LLM returns and the instructor reviews.

    Returned by ``POST /studio/ai/outline``, fed back to
    ``POST /studio/ai/commit-outline`` after the instructor has
    edited it in the preview pane.
    """

    title: str = Field(min_length=1, max_length=200)
    overview: str = Field(min_length=1, max_length=2_000)
    modules: list[OutlineModule] = Field(min_length=1, max_length=12)

    @field_validator("modules")
    @classmethod
    def _at_least_one_lesson(cls, v: list[OutlineModule]) -> list[OutlineModule]:
        if not any(m.lessons for m in v):
            raise ValueError("outline must contain at least one lesson")
        return v


class TiptapDoc(BaseModel):
    """Subset of Tiptap's JSONContent we accept from the LLM.

    The frontend renderer / editor (Phase E6) accepts the full Tiptap
    spec, but for the AI path we constrain inputs: ``type == 'doc'``
    with an array of block children. Anything else trips a validation
    error and triggers a retry. This is deliberately narrow so a
    confused model can't emit something that looks-like-a-doc but
    won't render in the editor (e.g. ``{ "type": "paragraph" }`` at
    the root).
    """

    type: str = Field(pattern="^doc$")
    content: list[dict[str, Any]] = Field(default_factory=list)


class CommitOutlineRequest(BaseModel):
    course_id: str = Field(min_length=1, max_length=64)
    outline: CourseOutline


# ---------- Prompts ----------

# Note: every prompt is a *system* + *user* pair. The system message
# carries the JSON-schema contract; the user message carries the
# instructor's brief / lesson title. We keep them as module-level
# constants so the format is auditable from one place when we tune
# the prompts later.

_OUTLINE_SYSTEM = """\
You are a course-design assistant. Given a brief description of a course \
an instructor wants to build, propose a clear, well-structured outline \
that a learner could follow from start to finish.

Return a single JSON object with this exact shape (no surrounding prose, \
no markdown code fences):

{
  "title": "Short course title",
  "overview": "1-2 paragraphs the instructor can paste straight into the \
course detail page",
  "modules": [
    {
      "title": "Module title",
      "lessons": [
        { "title": "Lesson title", "type": "text" },
        { "title": "Quiz title",  "type": "quiz" }
      ]
    }
  ]
}

Rules:
- Generate 3-6 modules unless the instructor explicitly asked for a \
different number.
- Each module has 3-5 lessons.
- Most lessons should be "text". Every module should end with one "quiz" \
lesson that checks the module's material.
- Only use "text" or "quiz" as the lesson type. Other lesson types \
(video, image, file) are reserved for instructor-uploaded content.
- Titles must be specific, not generic. "Introduction" alone is not a \
good lesson title; "Introduction to async/await in Python 3.13" is.
"""

_LESSON_BODY_SYSTEM = """\
You are a course-content drafter. Given a single lesson title and the \
broader course context, draft the lesson body as a Tiptap / ProseMirror \
JSON document an instructor can edit before publishing.

Return a single JSON object with this exact shape (no surrounding prose, \
no markdown code fences):

{
  "type": "doc",
  "content": [
    { "type": "heading", "attrs": { "level": 2 }, \
"content": [{ "type": "text", "text": "Section heading" }] },
    { "type": "paragraph", \
"content": [{ "type": "text", "text": "Paragraph text..." }] },
    { "type": "bulletList", "content": [
      { "type": "listItem", "content": [
        { "type": "paragraph", \
"content": [{ "type": "text", "text": "Bullet" }] }
      ] }
    ] }
  ]
}

Rules:
- Use a mix of paragraphs, headings (level 2 or 3), and bullet/ordered \
lists where they help comprehension.
- Aim for 200-500 words of body text. The instructor will expand or \
trim before publishing.
- Don't invent code snippets unless the lesson is clearly about code.
- Stay sober — no marketing voice, no exclamation marks.
"""

_QUIZ_SYSTEM = """\
You are a quiz-question writer. Given a lesson title + the broader \
course context, draft multiple-choice questions that test whether the \
learner has understood the material.

Return a single JSON object with this exact shape (no surrounding prose, \
no markdown code fences):

{
  "questions": [
    {
      "id": "q1",
      "prompt": "Question text",
      "kind": "single",
      "choices": [
        { "id": "a", "text": "Option A" },
        { "id": "b", "text": "Option B" },
        { "id": "c", "text": "Option C" },
        { "id": "d", "text": "Option D" }
      ],
      "answer_keys": ["a"]
    }
  ]
}

Rules:
- Generate exactly the number of questions the user asked for.
- Every question is "kind": "single" (one correct answer).
- Every question has 3-4 choices.
- Question ids run "q1", "q2", "q3", ... in order.
- Choice ids run "a", "b", "c", "d" within each question.
- answer_keys is a list with exactly one entry — the correct choice id.
- Make the distractors plausible, not silly. The point is to test \
understanding, not pattern-matching the obviously-wrong option.
"""


# ---------- Public generate API ----------


async def generate_outline(
    brief: str,
    target_modules: int = 4,
    *,
    session: AsyncSession | None = None,
    user_id: str | None = None,
) -> CourseOutline:
    """Call the LLM and return a parsed :class:`CourseOutline`.

    Pure function — no DB writes, no implicit state. The caller (API
    handler) decides whether to surface the result to the instructor
    for review or feed it straight into :func:`commit_outline`.

    ``session`` + ``user_id`` are optional — when supplied, the
    LLM call is routed through ``call_logged`` so Phase H1's cost
    meter records the round-trip. Existing tests that call this
    helper without the kwargs keep working (they hit the legacy
    no-meter path).
    """
    brief = brief.strip()
    if not brief:
        raise ValidationAppError("Brief must not be empty", code="ai.brief_empty")
    target_modules = max(2, min(int(target_modules), 8))
    user_msg = (
        f"Brief: {brief}\n\nPlease generate an outline with approximately {target_modules} modules."
    )
    return await _chat_with_retry(
        system=_OUTLINE_SYSTEM,
        user=user_msg,
        model=CourseOutline,
        temperature=0.7,
        session=session,
        user_id=user_id,
        feature="authoring.outline",
    )


async def generate_lesson_body(
    lesson_title: str,
    course_context: str,
    *,
    session: AsyncSession | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Return a Tiptap block document as a plain dict.

    We return ``dict`` rather than the :class:`TiptapDoc` model so the
    caller can dump it onto ``lesson.data`` (JSONB column) verbatim.
    The :class:`TiptapDoc` validation has already run inside
    :func:`_chat_with_retry` — we just throw away the typed wrapper.
    """
    lesson_title = lesson_title.strip()
    if not lesson_title:
        raise ValidationAppError("Lesson title must not be empty", code="ai.lesson_title_empty")
    user_msg = (
        f"Course context: {course_context.strip() or '(none provided)'}\n\n"
        f"Lesson title: {lesson_title}"
    )
    doc = await _chat_with_retry(
        system=_LESSON_BODY_SYSTEM,
        user=user_msg,
        model=TiptapDoc,
        temperature=0.7,
        session=session,
        user_id=user_id,
        feature="authoring.lesson",
    )
    return doc.model_dump()


class _QuizPayload(BaseModel):
    """Internal wrapper so we can validate the top-level ``questions``
    array as one Pydantic call. Not exposed on the wire."""

    questions: list[QuizQuestion] = Field(min_length=1, max_length=10)


async def generate_quiz(
    lesson_title: str,
    course_context: str,
    n: int = 4,
    *,
    session: AsyncSession | None = None,
    user_id: str | None = None,
) -> list[QuizQuestion]:
    """Return ``n`` MCQ questions for a quiz lesson."""
    lesson_title = lesson_title.strip()
    if not lesson_title:
        raise ValidationAppError("Lesson title must not be empty", code="ai.lesson_title_empty")
    n = max(1, min(int(n), 10))
    user_msg = (
        f"Course context: {course_context.strip() or '(none provided)'}\n\n"
        f"Lesson title: {lesson_title}\n\n"
        f"Generate exactly {n} multiple-choice questions."
    )
    payload = await _chat_with_retry(
        system=_QUIZ_SYSTEM,
        user=user_msg,
        model=_QuizPayload,
        temperature=0.6,
        session=session,
        user_id=user_id,
        feature="authoring.quiz",
    )
    return list(payload.questions)


# ---------- Persist (commit) ----------


async def commit_outline(
    db: AsyncSession, *, course_id: str, owner: User, outline: CourseOutline
) -> Course:
    """Persist ``outline`` into ``course_id`` as draft modules + lessons.

    The course must already exist (the studio UI creates an empty
    course first, then commits the outline against it). Existing
    modules / lessons are left alone — commit only *adds*. The
    instructor can re-run generate + commit to layer more content on
    top, or delete modules they don't want.

    Lesson bodies and quiz questions inside ``outline`` are NOT
    populated by this call. The outline carries only titles + types;
    individual lesson bodies / quizzes are filled in via the per-
    lesson generate buttons in the editor (see
    :func:`generate_lesson_body` / :func:`generate_quiz`).
    """
    course = await _owned_course(db, course_id, owner)
    # Start at the next available module order so we never collide
    # with whatever was already on the course (idempotent re-commit).
    base_order = await courses_repo.next_module_order(db, course.id)
    for mi, m in enumerate(outline.modules):
        module = Module(
            course_id=course.id,
            title=m.title,
            description="",
            order=base_order + mi,
        )
        db.add(module)
        await db.flush()
        for li, lesson_spec in enumerate(m.lessons):
            data = _default_lesson_data(lesson_spec)
            lesson = Lesson(
                module_id=module.id,
                title=lesson_spec.title,
                order=li,
                type=LessonType(lesson_spec.type),
                duration_seconds=None,
                is_preview=False,
                data=data,
            )
            db.add(lesson)
        await db.flush()
    return course


def _default_lesson_data(spec: OutlineLesson) -> dict[str, Any]:
    """Mint the minimum-valid ``lesson.data`` payload for a draft lesson.

    The schemas in ``app.schemas.course`` enforce non-empty content
    on every lesson type (text body, quiz needs at least one
    question). We satisfy the constraint with placeholder content
    the instructor will overwrite on first edit / on first
    per-lesson AI generate call. Without this, ``POST /lessons``
    would 422 on the bare outline.
    """
    if spec.type == "quiz":
        return {
            "type": "quiz",
            "pass_score": 60,
            "questions": [
                {
                    "id": "q1",
                    "prompt": "Draft question — replace before publishing",
                    "kind": "single",
                    "choices": [
                        {"id": "a", "text": "Option A"},
                        {"id": "b", "text": "Option B"},
                    ],
                    "answer_keys": ["a"],
                }
            ],
        }
    # text — minimum-valid block doc + legacy body_markdown.
    placeholder = "Draft — replace before publishing."
    return {
        "type": "text",
        "body_markdown": placeholder,
        "blocks": {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": placeholder}],
                }
            ],
        },
    }


# ---------- LLM call + retry helper ----------


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


async def _chat_one(
    provider: llm_service.LLMProvider,
    messages: list[llm_service.ChatMessage],
    *,
    temperature: float,
    session: AsyncSession | None,
    user_id: str | None,
    feature: str,
) -> str:
    """Run one provider turn — metered when a session is available.

    Centralised here so both the initial outline / lesson / quiz call
    and the retry path share the same metering decision: if a
    session was threaded down from the API edge, every turn lands
    in ``llm_calls``; otherwise we keep the legacy unmetered call
    so backfill scripts and test fixtures don't need to plumb a DB
    handle through.
    """
    if session is not None:
        response = await call_logged(
            provider,
            messages,
            user_id=user_id or SYSTEM_USER_ID,
            feature=feature,
            session=session,
            temperature=temperature,
        )
        return response.text
    return await provider.chat(messages, temperature=temperature)


def _extract_json(raw: str) -> str:
    """Best-effort: strip markdown code fences from the LLM reply.

    Even with a strict "no fences" system rider, models occasionally
    wrap output in ``` ```json ... ``` ``` blocks. Pull the inner
    JSON if a fence is present; otherwise return as-is and let
    :func:`json.loads` decide.
    """
    fence = _JSON_FENCE_RE.search(raw)
    if fence:
        return fence.group(1).strip()
    return raw.strip()


async def _chat_with_retry[M: BaseModel](
    *,
    system: str,
    user: str,
    model: type[M],
    temperature: float,
    session: AsyncSession | None = None,
    user_id: str | None = None,
    feature: str = "authoring",
) -> M:
    """Send one chat turn, validate as ``model``, retry once on failure.

    Retry policy is deliberately shallow: a single follow-up turn that
    quotes the parse / validation error back at the model. Two
    failures is enough signal that the prompt or the model is wrong;
    looping further would burn tokens with diminishing returns and
    block the request handler.

    When ``session`` is provided, each provider call is routed through
    the Phase H1 cost meter (``app.services.llm_call_log.call_logged``)
    — both turns of a retry pay separately, which is the right shape:
    the second call really is extra spend the operator should see.
    Without ``session``, falls back to the unmetered ``provider.chat``
    path so existing tests keep working.
    """
    provider = llm_service.get_provider()
    messages = [
        llm_service.ChatMessage(role="system", content=system),
        llm_service.ChatMessage(role="user", content=user),
    ]
    raw = await _chat_one(
        provider,
        messages,
        temperature=temperature,
        session=session,
        user_id=user_id,
        feature=feature,
    )
    parsed, err = _try_parse(raw, model)
    if parsed is not None:
        return parsed
    # Retry once with the previous (broken) output + the error so the
    # model can self-correct.
    messages.extend(
        [
            llm_service.ChatMessage(role="assistant", content=raw),
            llm_service.ChatMessage(
                role="user",
                content=(
                    "Your previous response could not be parsed.\n"
                    f"Error: {err}\n\n"
                    "Reply with a corrected JSON object matching the schema. "
                    "No prose, no markdown fences."
                ),
            ),
        ]
    )
    raw2 = await _chat_one(
        provider,
        messages,
        temperature=max(0.2, temperature - 0.3),
        session=session,
        user_id=user_id,
        feature=feature,
    )
    parsed, err = _try_parse(raw2, model)
    if parsed is not None:
        return parsed
    log.warning(
        "ai_authoring_llm_bad_output",
        model=model.__name__,
        first_error=err,
        first_raw_head=raw[:200],
        retry_raw_head=raw2[:200],
    )
    raise ValidationAppError(
        "The AI returned an unexpected response. Try again.",
        code="ai.bad_output",
    )


def _try_parse[M: BaseModel](raw: str, model: type[M]) -> tuple[M | None, str | None]:
    """Parse ``raw`` as JSON + validate against ``model``.

    Returns ``(model_instance, None)`` on success, ``(None, message)``
    on failure. We collapse the two error paths (json + pydantic)
    into one signature so the caller's retry logic doesn't have to
    branch on type.
    """
    body = _extract_json(raw)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return None, f"JSON parse error: {exc.msg} at line {exc.lineno}"
    try:
        return model.model_validate(payload), None
    except ValidationError as exc:
        # Pydantic's full error tree is verbose; we send the model a
        # one-line summary instead so the retry prompt stays small.
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []))
        msg = first.get("msg", "validation error")
        return None, f"validation error at {loc or '<root>'}: {msg}"
