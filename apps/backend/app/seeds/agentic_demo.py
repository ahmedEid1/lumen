"""Agentic demo seed (Lumen v2 — A5 activation).

Layered on top of :func:`app.cli._seed` so a `make seed` after a fresh
`docker compose up` produces a *live-looking* demo dataset:

* 5 extra **published** courses (combined with the existing FastAPI
  course = 6 in total) covering data-engineering, frontend, MLOps,
  AI engineering, and product design — each carries a cover-image URL
  (``picsum.photos`` placeholder) so the catalog renders illustrated.
* The FastAPI course gets ``learning_outcomes`` + ``cover_url``
  back-filled (the original ``_seed`` left them empty / null).
* The seed student is given a **second** enrollment on FastAPI with
  every lesson marked complete + a minted ``certificate_id`` +
  best-effort OB3 ``badge_credential`` — so the learner dashboard
  shows a "completed courses" row with the certificate / Open Badge
  links visible.
* A separate enrollment on the new "Data Engineering Foundations"
  course is left in-flight at ~50% progress, so the dashboard's
  in-progress list has variety.
* One **tutor conversation** with a `user` + `assistant` turn, plus
  matching `agent_traces`, `llm_calls`, `retrieval_audits` rows
  timestamped just-before the assistant turn so the I4 learner-trace
  drill-down at ``/dashboard/tutor/{cid}/turn/{mid}`` populates
  (the service reconstructs the link temporally, see
  ``app.services.learner_traces``).
* One **course draft trace** (researcher → outliner → critic →
  reviser → outliner → critic → lesson_drafter × 2 → final_critic)
  attached to a freshly-seeded draft course owned by the seed
  instructor — so the I4 studio replay at
  ``/studio/draft/{course_id}/replay`` has content.

Everything is **idempotent** — re-running `make seed` finds existing
rows by stable lookup keys (course slug, conversation+user pair,
draft_id) and skips rather than duplicates. The agentic surfaces
(tutor conversation, course draft) are skipped entirely if the
seed has already populated their parent rows.

Invoked from :func:`app.cli._seed` after the base subject / tag /
user / FastAPI-course bootstrap completes. Kept in its own module so
the base seed stays a one-screen read.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from rich.console import Console
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.models.agent_trace import (
    TRACE_STATUS_OK,
    AgentTrace,
)
from app.models.course import (
    Course,
    CourseStatus,
    Difficulty,
    Enrollment,
    Lesson,
    LessonProgress,
    LessonType,
    Module,
    Subject,
    Tag,
)
from app.models.course_draft_trace import (
    DRAFT_STATUS_OK,
    DRAFT_STEP_CRITIC,
    DRAFT_STEP_FINAL_CRITIC,
    DRAFT_STEP_LESSON_DRAFTER,
    DRAFT_STEP_OUTLINER,
    DRAFT_STEP_RESEARCHER,
    DRAFT_STEP_REVISER,
    CourseDraftTrace,
)
from app.models.llm_call import LLMCall
from app.models.retrieval_audit import RetrievalAudit
from app.models.tutor_conversation import (
    TutorConversation,
    TutorMessage,
    TutorMessageRole,
)
from app.models.user import User
from app.services import badges as badges_service

console = Console()


# --------------------------------------------------------------------- #
# Additional published courses                                          #
# --------------------------------------------------------------------- #
#
# Picsum seeds give us stable, illustrated covers per course
# without a real CDN dependency. The numeric seed in the URL
# (``picsum.photos/seed/<slug>/1200/750``) keeps the same image
# across re-renders so the catalog screenshots look consistent.


def _cover(slug: str) -> str:
    return f"https://picsum.photos/seed/{slug}/1200/750"


_NEW_COURSES: list[dict[str, Any]] = [
    {
        "slug": "data-engineering-foundations",
        "title": "Data Engineering Foundations",
        "subject_slug": "data-science",
        "tag_slugs": ["python", "beginner"],
        "overview": (
            "Move from CSVs and ad-hoc scripts to durable data "
            "pipelines. Postgres as the warehouse, dbt for transforms, "
            "Airflow for scheduling, and a working mental model for "
            "data quality."
        ),
        "outcomes": [
            "Model a star schema from a raw operational source",
            "Write idempotent dbt models with tests + freshness checks",
            "Schedule a daily extract-load-transform with Airflow",
            "Spot and fix the three classic pipeline failure modes",
        ],
        "difficulty": Difficulty.intermediate,
        "modules": [
            ("The warehouse mindset", ["Sources vs models", "Star vs snowflake"]),
            ("Transforms with dbt", ["Your first model", "Tests and freshness"]),
            ("Scheduling with Airflow", ["DAGs and operators", "Retries + alerting"]),
        ],
    },
    {
        "slug": "react-18-server-components",
        "title": "React 18 + Server Components",
        "subject_slug": "programming",
        "tag_slugs": ["react", "typescript"],
        "overview": (
            "What the App Router actually changed. Build a small "
            "Next.js 15 app from scratch — server components, "
            "streaming, suspense, and the new caching model — without "
            "the cargo-culting."
        ),
        "outcomes": [
            "Decide server-vs-client for every component you write",
            "Stream UI with Suspense without breaking the back button",
            "Use the App Router cache without surprise stale reads",
            "Ship a small dashboard that hits an API end-to-end",
        ],
        "difficulty": Difficulty.intermediate,
        "modules": [
            ("Server vs client components", ["Why split?", "The seam"]),
            ("Streaming and Suspense", ["Loading UI", "Selective hydration"]),
            ("Caching the App Router way", ["fetch + revalidate", "When to opt out"]),
        ],
    },
    {
        "slug": "mlops-from-notebook-to-prod",
        "title": "MLOps: From Notebook to Production",
        "subject_slug": "data-science",
        "tag_slugs": ["machine-learning", "python"],
        "overview": (
            "The gap between a notebook that works on your laptop and "
            "a model that pays its keep in production. Tracking, "
            "packaging, serving, monitoring — the four pillars and the "
            "tools that fill them."
        ),
        "outcomes": [
            "Track every experiment with MLflow without ceremony",
            "Package a model as a versioned, reproducible artifact",
            "Serve a model behind FastAPI with sane batching",
            "Catch drift before it makes it into a postmortem",
        ],
        "difficulty": Difficulty.advanced,
        "modules": [
            ("Experiments + tracking", ["Why MLflow", "Logging that matters"]),
            ("Packaging models", ["Containers vs ONNX", "Version pinning"]),
            ("Serving + monitoring", ["FastAPI inference", "Drift detection"]),
        ],
    },
    {
        "slug": "agentic-ai-engineering",
        "title": "Agentic AI Engineering",
        "subject_slug": "programming",
        "tag_slugs": ["machine-learning", "python"],
        "overview": (
            "Build LLM-backed agents that plan, call tools, critique "
            "themselves, and stay observable. Pattern walkthroughs: "
            "planner-orchestrator, self-critique loops, MCP tool "
            "exposure, eval harnesses with LLM-as-judge."
        ),
        "outcomes": [
            "Pick between single-prompt, ReAct, and planner patterns",
            "Wire a multi-agent system with bounded tool-call budgets",
            "Expose your app as MCP tools so other agents can use it",
            "Score every agent run with an LLM-as-judge harness",
        ],
        "difficulty": Difficulty.advanced,
        "modules": [
            ("Patterns of agent design", ["When NOT to use an agent", "Bounded autonomy"]),
            ("Self-critique loops", ["Critic + reviser", "Knowing when to stop"]),
            ("Eval harnesses", ["Golden datasets", "Judge axes"]),
        ],
    },
    {
        "slug": "product-design-fundamentals",
        "title": "Product Design Fundamentals",
        "subject_slug": "design",
        "tag_slugs": ["ux", "beginner"],
        "overview": (
            "The shape of a product, not just the look of it. "
            "Discovery, framing, prototyping, and the handful of UX "
            "heuristics that catch 80% of the avoidable mistakes."
        ),
        "outcomes": [
            "Run a problem-discovery interview without leading the answer",
            "Frame a product brief that fits on one page",
            "Prototype a flow that's testable on five users in an hour",
            "Apply the Nielsen heuristics like a surgical checklist",
        ],
        "difficulty": Difficulty.beginner,
        "modules": [
            ("Discovery", ["What to ask", "What not to ask"]),
            ("Framing", ["The one-page brief", "Tight scope wins"]),
            ("Prototyping", ["Lo-fi to hi-fi", "Testing with five users"]),
        ],
    },
]


def _text_lesson(title: str, body: str) -> dict[str, Any]:
    return {
        "title": title,
        "type": LessonType.text,
        "data": {"type": "text", "body_markdown": body},
    }


async def _ensure_course(
    db: AsyncSession,
    *,
    spec: dict[str, Any],
    subjects: dict[str, Subject],
    tags: dict[str, Tag],
    instructor: User,
) -> Course:
    res = await db.execute(select(Course).where(Course.slug == spec["slug"]))
    course = res.scalar_one_or_none()
    if course is not None:
        # Back-fill cover_url + learning_outcomes for an already-seeded
        # row from a prior run that pre-dated this enrichment (the
        # ``seed`` command is now idempotent + additive — we never
        # clobber instructor edits, but a still-default value is fair
        # game).
        if not course.cover_url:
            course.cover_url = _cover(spec["slug"])
        if not course.learning_outcomes:
            course.learning_outcomes = spec["outcomes"]
        return course

    subject = subjects[spec["subject_slug"]]
    course = Course(
        owner_id=instructor.id,
        subject_id=subject.id,
        title=spec["title"],
        slug=spec["slug"],
        overview=spec["overview"],
        learning_outcomes=spec["outcomes"],
        difficulty=spec["difficulty"],
        cover_url=_cover(spec["slug"]),
        status=CourseStatus.published,
        published_at=datetime.now(UTC),
        is_featured=False,
    )
    course.tags = [tags[s] for s in spec["tag_slugs"] if s in tags]
    db.add(course)
    await db.flush()

    for m_idx, (mod_title, lesson_titles) in enumerate(spec["modules"]):
        module = Module(
            course_id=course.id,
            title=mod_title,
            description=f"Module {m_idx + 1} of {spec['title']}.",
            order=m_idx,
        )
        db.add(module)
        await db.flush()
        for l_idx, lesson_title in enumerate(lesson_titles):
            lesson = Lesson(
                module_id=module.id,
                title=lesson_title,
                type=LessonType.text,
                order=l_idx,
                data={
                    "type": "text",
                    "body_markdown": (
                        f"## {lesson_title}\n\n"
                        f"_Seeded lesson — replace with real content "
                        f"in production. Part of the **{spec['title']}** "
                        f"demo bundle._"
                    ),
                },
            )
            db.add(lesson)
        await db.flush()
    return course


# --------------------------------------------------------------------- #
# Enrollment with progress + certificate                                #
# --------------------------------------------------------------------- #


async def _ensure_completed_enrollment(
    db: AsyncSession, *, student: User, course: Course
) -> Enrollment:
    """Enrol student on ``course``, mark every lesson complete, mint cert.

    Idempotent: if the student is already enrolled with
    ``completed_at`` set, return the existing row untouched. Otherwise
    we top up missing lesson-progress rows + flip ``completed_at`` +
    mint a ``certificate_id``. The OB3 badge is issued best-effort;
    failures are logged but don't block the seed.
    """
    res = await db.execute(
        select(Enrollment).where(
            Enrollment.user_id == student.id,
            Enrollment.course_id == course.id,
        )
    )
    enrolment = res.scalar_one_or_none()
    if enrolment is None:
        enrolment = Enrollment(user_id=student.id, course_id=course.id)
        db.add(enrolment)
        await db.flush()

    if enrolment.completed_at is not None and enrolment.certificate_id:
        return enrolment

    # Mark every lesson complete (idempotent — only add missing rows).
    lessons_res = await db.execute(
        select(Lesson)
        .join(Module, Module.id == Lesson.module_id)
        .where(Module.course_id == course.id)
        .order_by(Module.order, Lesson.order)
    )
    lessons = lessons_res.scalars().all()
    if not lessons:
        return enrolment

    existing_progress_res = await db.execute(
        select(LessonProgress.lesson_id).where(
            LessonProgress.enrollment_id == enrolment.id
        )
    )
    completed_ids = set(existing_progress_res.scalars().all())
    for lesson in lessons:
        if lesson.id in completed_ids:
            continue
        db.add(
            LessonProgress(
                enrollment_id=enrolment.id,
                lesson_id=lesson.id,
                completed_at=datetime.now(UTC) - timedelta(hours=1),
                score=100 if lesson.type == LessonType.quiz else None,
            )
        )
    await db.flush()

    enrolment.completed_at = datetime.now(UTC) - timedelta(minutes=30)
    if not enrolment.certificate_id:
        enrolment.certificate_id = f"cert_{new_id()}"
    # Best-effort OB3 — same posture as the live enrollment service.
    try:
        enrolment.badge_credential = badges_service.issue_for_enrollment(
            enrollment=enrolment, user=student, course=course,
        )
    except Exception:  # pragma: no cover — defensive
        enrolment.badge_credential = None
    return enrolment


async def _ensure_in_flight_enrollment(
    db: AsyncSession, *, student: User, course: Course, progress_fraction: float
) -> Enrollment:
    """Enrol + mark the *first* ``progress_fraction`` of lessons done.

    No certificate / completion. Idempotent on re-run — only adds the
    missing :class:`LessonProgress` rows.
    """
    res = await db.execute(
        select(Enrollment).where(
            Enrollment.user_id == student.id,
            Enrollment.course_id == course.id,
        )
    )
    enrolment = res.scalar_one_or_none()
    if enrolment is None:
        enrolment = Enrollment(user_id=student.id, course_id=course.id)
        db.add(enrolment)
        await db.flush()

    lessons_res = await db.execute(
        select(Lesson)
        .join(Module, Module.id == Lesson.module_id)
        .where(Module.course_id == course.id)
        .order_by(Module.order, Lesson.order)
    )
    lessons = lessons_res.scalars().all()
    if not lessons:
        return enrolment
    cutoff = max(1, int(len(lessons) * progress_fraction))

    existing_res = await db.execute(
        select(LessonProgress.lesson_id).where(
            LessonProgress.enrollment_id == enrolment.id
        )
    )
    completed_ids = set(existing_res.scalars().all())
    for lesson in lessons[:cutoff]:
        if lesson.id in completed_ids:
            continue
        db.add(
            LessonProgress(
                enrollment_id=enrolment.id,
                lesson_id=lesson.id,
                completed_at=datetime.now(UTC) - timedelta(days=1),
                score=None,
            )
        )
    return enrolment


# --------------------------------------------------------------------- #
# Tutor turn — one assistant message with a real agent trace            #
# --------------------------------------------------------------------- #


# Stable marker so a re-run can find "the seed conversation" by user
# + course + a known content prefix on the user message, without us
# needing a new column. Conversations have no business uniqueness
# constraint so we'd otherwise dupe on every seed run.
_SEED_USER_PROMPT = (
    "[demo-seed] How does FastAPI's dependency injection work, and how "
    "does it interact with async session lifetimes?"
)


async def _ensure_tutor_turn(
    db: AsyncSession, *, student: User, course: Course
) -> tuple[TutorConversation, TutorMessage] | None:
    """Persist one tutor user/assistant turn for the screenshot demo.

    Also writes the linked ``llm_calls`` + ``agent_traces`` +
    ``retrieval_audits`` rows the I4 surface joins on. The join is
    *temporal* — the seeded LLM-call / trace / audit rows all sit
    inside the 120-second look-back window the service uses, so the
    drill-down at ``/dashboard/tutor/{cid}/turn/{mid}`` populates
    without any further wiring.

    Returns ``(conversation, assistant_message)`` for callers that
    want to deep-link. Returns ``None`` if a prior seed already wrote
    this conversation (signalled by finding a user message starting
    with :data:`_SEED_USER_PROMPT`).
    """
    # Idempotency: look for the marker user-message on any
    # conversation for this (user, course).
    existing_res = await db.execute(
        select(TutorMessage)
        .join(
            TutorConversation,
            TutorConversation.id == TutorMessage.conversation_id,
        )
        .where(
            TutorConversation.user_id == student.id,
            TutorConversation.course_id == course.id,
            TutorMessage.role == TutorMessageRole.user,
            TutorMessage.content.like(f"{_SEED_USER_PROMPT[:32]}%"),
        )
        .limit(1)
    )
    if existing_res.scalar_one_or_none() is not None:
        return None

    # Anchor the turn ~5 minutes ago — the trace look-back window is
    # 120s, so we keep every linked row inside [anchor - 60s, anchor].
    anchor = datetime.now(UTC) - timedelta(minutes=5)
    user_ts = anchor - timedelta(seconds=90)
    plan_ts = anchor - timedelta(seconds=55)
    retriever_ts = anchor - timedelta(seconds=42)
    web_ts = anchor - timedelta(seconds=30)
    synth_ts = anchor - timedelta(seconds=12)
    assistant_ts = anchor

    conv = TutorConversation(
        user_id=student.id,
        course_id=course.id,
        created_at=user_ts,
        last_message_at=assistant_ts,
    )
    db.add(conv)
    await db.flush()

    user_msg = TutorMessage(
        conversation_id=conv.id,
        role=TutorMessageRole.user,
        content=_SEED_USER_PROMPT,
        citations=[],
        created_at=user_ts,
    )
    db.add(user_msg)
    await db.flush()

    # Look up a couple of real lesson ids on this course so the
    # citations + retrieval audit + retriever-step payload all point
    # somewhere real. Fall back to a stub if the course has no
    # lessons yet (defensive — the base seed always seeds five).
    lessons_res = await db.execute(
        select(Lesson)
        .join(Module, Module.id == Lesson.module_id)
        .where(Module.course_id == course.id)
        .order_by(Module.order, Lesson.order)
        .limit(3)
    )
    cited_lessons = lessons_res.scalars().all()
    citations = [
        {
            "lesson_id": lesson.id,
            "lesson_title": lesson.title,
            "chunk_excerpt": (
                f"{lesson.title} — illustrates how FastAPI's `Depends` "
                "composes per-request resources like the AsyncSession."
            ),
        }
        for lesson in cited_lessons[:2]
    ]
    assistant_text = (
        "FastAPI's `Depends(...)` lets you compose per-request "
        "resources — a DB session, the authenticated user, a feature "
        "flag — into a graph that the framework resolves per request "
        "and passes into your handler as keyword arguments.\n\n"
        "For async session lifetimes specifically, Lumen wires a "
        "`DBSession` dependency that yields an `AsyncSession`. The "
        "session lives for the duration of one request: it's opened in "
        "the dependency, awaited by your handler, committed (or rolled "
        "back) at the boundary, and disposed once the response is "
        "queued. Crucially, lazy-loading a relationship on a model "
        "*after* the dependency returns will deadlock the session — "
        "always eager-load what you need via `selectinload()`."
    )
    assistant_msg = TutorMessage(
        conversation_id=conv.id,
        role=TutorMessageRole.assistant,
        content=assistant_text,
        citations=citations,
        created_at=assistant_ts,
    )
    db.add(assistant_msg)
    await db.flush()

    # ---------- Linked LLM calls + agent_traces + retrieval audits ----------
    #
    # The I4 service reconstructs the turn ↔ trace link temporally
    # because no FK exists today (documented in
    # ``app.services.learner_traces``). We mint LLM-call rows for
    # plan + synth + retriever feature slugs and matching agent_trace
    # rows for plan, sub_agent.retriever, sub_agent.web_searcher, synth.

    plan_call = LLMCall(
        user_id=student.id,
        feature="tutor.multi_agent.plan",
        provider="noop",
        model="lumen-noop-1",
        prompt_tokens=512,
        completion_tokens=84,
        cost_usd=Decimal("0.000234"),
        latency_ms=820,
        status="ok",
        created_at=plan_ts,
    )
    db.add(plan_call)
    synth_call = LLMCall(
        user_id=student.id,
        feature="tutor.multi_agent.synth",
        provider="noop",
        model="lumen-noop-1",
        prompt_tokens=1340,
        completion_tokens=246,
        cost_usd=Decimal("0.000591"),
        latency_ms=1740,
        status="ok",
        created_at=synth_ts,
    )
    db.add(synth_call)
    await db.flush()

    # Retrieval audit — what the retriever sub-agent actually pulled.
    audit_chunks = [
        {
            "chunk_id": f"chunk_{i}",
            "lesson_id": lesson.id,
            "score": round(0.18 + i * 0.05, 3),
            "snippet": (
                f"{lesson.title}: FastAPI dependencies compose into a "
                "per-request graph that resolves once and is reused..."
            )[:120],
        }
        for i, lesson in enumerate(cited_lessons[:3])
    ] if cited_lessons else []
    audit = RetrievalAudit(
        user_id=student.id,
        feature="tutor.multi_agent.retriever",
        query="dependency injection async session lifetime",
        course_id=course.id,
        chunks=audit_chunks,
        top_score=audit_chunks[0]["score"] if audit_chunks else None,
        created_at=retriever_ts,
    )
    db.add(audit)
    await db.flush()

    # Agent traces — plan, retriever, web_searcher, synth.
    plan_trace = AgentTrace(
        user_id=student.id,
        feature="tutor.multi_agent",
        step="plan",
        step_index=0,
        parent_trace_id=None,
        parent_call_id=plan_call.id,
        payload={
            "prompt_summary": _SEED_USER_PROMPT[:240],
            "response_summary": (
                "Plan: retrieve top course chunks on Depends + session "
                "lifetime, supplement with a web check on async "
                "deadlocks, then synthesize."
            ),
            "tools_chosen": ["retriever", "web_searcher"],
            "confidence_after_plan": 4,
            "tool_calls": [
                {
                    "tool_name": "retriever",
                    "args": {
                        "query": "dependency injection async session lifetime",
                        "top_k": 3,
                    },
                    "rationale": (
                        "Course-scoped RAG over FastAPI lessons should "
                        "carry the bulk of the answer."
                    ),
                    "result_summary": (
                        f"Retrieved {len(audit_chunks)} relevant lesson "
                        "chunk(s); top score 0.18."
                    ),
                    "result_details": {"chunks": audit_chunks},
                },
                {
                    "tool_name": "web_searcher",
                    "args": {"q": "fastapi sqlalchemy async session deadlock"},
                    "rationale": (
                        "Cross-check the 'lazy-load after dependency "
                        "returns' deadlock pattern against current docs."
                    ),
                    "result_summary": "1 corroborating snippet on async lazy-load.",
                    "result_details": {
                        "snippets": [
                            {
                                "title": (
                                    "SQLAlchemy 2 async session — "
                                    "MissingGreenlet on lazy attribute"
                                ),
                                "url": (
                                    "https://docs.sqlalchemy.org/en/20/"
                                    "errors.html#error-xd2s"
                                ),
                                "content_first_240": (
                                    "Attribute access on a relationship "
                                    "that was not loaded inside the "
                                    "AsyncSession will raise MissingGreenlet."
                                ),
                            }
                        ]
                    },
                },
            ],
        },
        duration_ms=820,
        status=TRACE_STATUS_OK,
        created_at=plan_ts,
    )
    db.add(plan_trace)
    await db.flush()

    retriever_trace = AgentTrace(
        user_id=student.id,
        feature="tutor.multi_agent.retriever",
        step="sub_agent.retriever",
        step_index=1,
        parent_trace_id=plan_trace.id,
        parent_call_id=None,
        payload={
            "tool_name": "retriever",
            "tool_args": {
                "query": "dependency injection async session lifetime",
                "top_k": 3,
            },
            "tool_result": {
                "chunk_count": len(audit_chunks),
                "audit_id": audit.id,
            },
            "chunks": audit_chunks,
        },
        duration_ms=240,
        status=TRACE_STATUS_OK,
        created_at=retriever_ts,
    )
    db.add(retriever_trace)

    web_trace = AgentTrace(
        user_id=student.id,
        feature="tutor.multi_agent.web_searcher",
        step="sub_agent.web_searcher",
        step_index=2,
        parent_trace_id=plan_trace.id,
        parent_call_id=None,
        payload={
            "tool_name": "web_searcher",
            "tool_args": {"q": "fastapi sqlalchemy async session deadlock"},
            "tool_result": {"snippet_count": 1},
        },
        duration_ms=380,
        status=TRACE_STATUS_OK,
        created_at=web_ts,
    )
    db.add(web_trace)

    synth_trace = AgentTrace(
        user_id=student.id,
        feature="tutor.multi_agent.synth",
        step="synth",
        step_index=3,
        parent_trace_id=None,
        parent_call_id=synth_call.id,
        payload={
            "prompt_summary": "Synthesize from retriever + web chunks.",
            "response_summary": assistant_text[:240],
            "confidence_final": 4,
        },
        duration_ms=1740,
        status=TRACE_STATUS_OK,
        created_at=synth_ts,
    )
    db.add(synth_trace)
    await db.flush()

    return conv, assistant_msg


# --------------------------------------------------------------------- #
# Course draft with a self-critique trace                               #
# --------------------------------------------------------------------- #


# Stable slug so a re-run finds the draft and skips re-seeding the trace.
_DRAFT_COURSE_SLUG = "ai-tutor-design-patterns"


async def _ensure_draft_trace(
    db: AsyncSession,
    *,
    instructor: User,
    subjects: dict[str, Subject],
    tags: dict[str, Tag],
) -> Course | None:
    """Seed a draft course + a full self-critique trace.

    The draft course is created in ``CourseStatus.draft`` (the studio
    replay surface needs an instructor-owned draft course to anchor
    the trace rows). Idempotent: if the course exists *and* already
    has draft-trace rows, we no-op.
    """
    res = await db.execute(select(Course).where(Course.slug == _DRAFT_COURSE_SLUG))
    course = res.scalar_one_or_none()
    if course is None:
        course = Course(
            owner_id=instructor.id,
            subject_id=subjects["programming"].id,
            title="AI Tutor Design Patterns",
            slug=_DRAFT_COURSE_SLUG,
            overview=(
                "Drafted by the Lumen self-critique authoring agent — "
                "researcher → outliner → critic → reviser → drafter → "
                "final-critic. Open the replay to watch the chain unfold."
            ),
            learning_outcomes=[
                "Identify the four patterns of agent-backed tutoring",
                "Pick a retrieval shape (BM25 / dense / hybrid) per case",
                "Wire a critic-revise loop with a hard revision budget",
            ],
            cover_url=_cover(_DRAFT_COURSE_SLUG),
            difficulty=Difficulty.advanced,
            status=CourseStatus.draft,
            is_featured=False,
        )
        course.tags = [tags["python"], tags["machine-learning"]]
        db.add(course)
        await db.flush()
        # Minimal module / lesson tree so the studio surface has
        # something to render. The trace's lesson_drafter rows
        # reference these lessons by id.
        module = Module(
            course_id=course.id,
            title="Patterns of agent-backed tutoring",
            description="The four shapes most AI tutors fall into.",
            order=0,
        )
        db.add(module)
        await db.flush()
        for l_idx, l_title in enumerate(
            ["Single-prompt tutor", "Retrieval-augmented tutor"]
        ):
            db.add(
                Lesson(
                    module_id=module.id,
                    title=l_title,
                    type=LessonType.text,
                    order=l_idx,
                    data={
                        "type": "text",
                        "body_markdown": (
                            f"# {l_title}\n\n_Drafted by the authoring "
                            "agent — instructor review pending._"
                        ),
                    },
                )
            )
        await db.flush()

    # Already have trace rows? Skip.
    existing = await db.execute(
        select(CourseDraftTrace).where(CourseDraftTrace.course_id == course.id).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        return course

    draft_id = new_id()
    base = datetime.now(UTC) - timedelta(hours=2)

    # Pull the seeded lessons so the lesson_drafter steps reference
    # real ids (matches the orchestrator's payload shape).
    lessons_res = await db.execute(
        select(Lesson)
        .join(Module, Module.id == Lesson.module_id)
        .where(Module.course_id == course.id)
        .order_by(Module.order, Lesson.order)
    )
    lessons = lessons_res.scalars().all()

    rows: list[CourseDraftTrace] = []

    rows.append(
        CourseDraftTrace(
            draft_id=draft_id,
            course_id=course.id,
            user_id=instructor.id,
            step=DRAFT_STEP_RESEARCHER,
            step_index=0,
            payload={
                "prompt_summary": (
                    "Brief: a short advanced course on AI-tutor design "
                    "patterns, citation-aware retrieval, and the "
                    "self-critique loop."
                ),
                "response_summary": (
                    "3 web snippet(s); 2 catalog neighbour(s); "
                    "note='enough coverage to outline'."
                ),
                "web_snippets": [
                    {
                        "title": "Anthropic — Building effective agents",
                        "url": "https://www.anthropic.com/research/building-effective-agents",
                        "content_first_240": (
                            "Effective agents start with the simplest "
                            "design that solves the task; complexity "
                            "is earned, not assumed."
                        ),
                    }
                ],
                "catalog_neighbours": [
                    {"slug": "agentic-ai-engineering", "title": "Agentic AI Engineering"},
                    {"slug": "fastapi-from-zero", "title": "FastAPI from Zero"},
                ],
            },
            duration_ms=420,
            status=DRAFT_STATUS_OK,
            created_at=base,
        )
    )

    rows.append(
        CourseDraftTrace(
            draft_id=draft_id,
            course_id=course.id,
            user_id=instructor.id,
            step=DRAFT_STEP_OUTLINER,
            step_index=1,
            payload={
                "prompt_summary": (
                    "Brief: AI-tutor design patterns + self-critique."
                ),
                "response_summary": (
                    "Outline v1: 3 modules, 6 lessons total (Patterns, "
                    "Retrieval shapes, Critic-revise loops)."
                ),
                "outline": {
                    "title": "AI Tutor Design Patterns",
                    "modules": [
                        {"title": "Patterns of agent-backed tutoring", "lessons": 2},
                        {"title": "Retrieval shapes", "lessons": 2},
                        {"title": "Critic-revise loops", "lessons": 2},
                    ],
                },
            },
            duration_ms=1620,
            status=DRAFT_STATUS_OK,
            created_at=base + timedelta(seconds=2),
        )
    )

    rows.append(
        CourseDraftTrace(
            draft_id=draft_id,
            course_id=course.id,
            user_id=instructor.id,
            step=DRAFT_STEP_CRITIC,
            step_index=2,
            payload={
                "prompt_summary": "Outline v1 — 3 modules, 6 lessons.",
                "response_summary": (
                    "Coverage 3, depth 2, sequencing 3, originality 3 "
                    "(mean 2.75) — below acceptance (3.5). Critic asks "
                    "for a sharper depth treatment in the retrieval "
                    "module and an explicit revision-budget lesson."
                ),
                "critic_scores": {
                    "coverage": 3,
                    "depth": 2,
                    "sequencing": 3,
                    "originality": 3,
                    "mean": 2.75,
                },
                "weak_spots": [
                    "Retrieval module is one-sentence-deep — needs hybrid examples",
                    "No lesson on bounding the critic-revise loop",
                ],
                "revision_number": 0,
            },
            duration_ms=1180,
            status=DRAFT_STATUS_OK,
            created_at=base + timedelta(seconds=4),
        )
    )

    rows.append(
        CourseDraftTrace(
            draft_id=draft_id,
            course_id=course.id,
            user_id=instructor.id,
            step=DRAFT_STEP_REVISER,
            step_index=3,
            payload={
                "prompt_summary": (
                    "Retrieval module is one-sentence-deep — needs "
                    "hybrid examples; No lesson on bounding the loop"
                ),
                "response_summary": (
                    "Outline v2: 3 modules, 7 lessons. Retrieval module "
                    "expanded with BM25 vs dense vs hybrid; added "
                    "'Knowing when to stop' lesson to module 3."
                ),
                "outline": {
                    "title": "AI Tutor Design Patterns",
                    "modules": [
                        {"title": "Patterns of agent-backed tutoring", "lessons": 2},
                        {"title": "Retrieval shapes (BM25 / dense / hybrid)", "lessons": 3},
                        {"title": "Critic-revise loops", "lessons": 2},
                    ],
                },
                "revision_number": 1,
            },
            duration_ms=1980,
            status=DRAFT_STATUS_OK,
            created_at=base + timedelta(seconds=7),
        )
    )

    rows.append(
        CourseDraftTrace(
            draft_id=draft_id,
            course_id=course.id,
            user_id=instructor.id,
            step=DRAFT_STEP_CRITIC,
            step_index=4,
            payload={
                "prompt_summary": "Outline v2 — 3 modules, 7 lessons.",
                "response_summary": (
                    "Coverage 4, depth 4, sequencing 4, originality 3 "
                    "(mean 3.75) — accepted. Strong depth gain on "
                    "retrieval; sequencing now matches reader's mental "
                    "model."
                ),
                "critic_scores": {
                    "coverage": 4,
                    "depth": 4,
                    "sequencing": 4,
                    "originality": 3,
                    "mean": 3.75,
                },
                "weak_spots": [
                    "Originality still weak — examples lean on stock RAG patterns",
                ],
                "revision_number": 1,
            },
            duration_ms=1050,
            status=DRAFT_STATUS_OK,
            created_at=base + timedelta(seconds=9),
        )
    )

    # Two lesson_drafter rows — one per seeded lesson.
    for idx, lesson in enumerate(lessons):
        rows.append(
            CourseDraftTrace(
                draft_id=draft_id,
                course_id=course.id,
                user_id=instructor.id,
                step=DRAFT_STEP_LESSON_DRAFTER,
                step_index=5 + idx,
                payload={
                    "prompt_summary": lesson.title[:240],
                    "response_summary": "text lesson drafted",
                    "lesson_id": lesson.id,
                    "lesson_type": str(lesson.type),
                },
                duration_ms=2240 + idx * 120,
                status=DRAFT_STATUS_OK,
                created_at=base + timedelta(seconds=11 + idx * 3),
            )
        )

    final_step_index = 5 + max(len(lessons), 1)
    rows.append(
        CourseDraftTrace(
            draft_id=draft_id,
            course_id=course.id,
            user_id=instructor.id,
            step=DRAFT_STEP_FINAL_CRITIC,
            step_index=final_step_index,
            payload={
                "prompt_summary": "Final outline + drafted lessons.",
                "response_summary": (
                    "Coverage 4, depth 4, sequencing 4, originality 3 "
                    "(mean 3.75) — ready for instructor review. Suggest "
                    "an editorial pass on the originality axis before "
                    "publishing."
                ),
                "critic_scores": {
                    "coverage": 4,
                    "depth": 4,
                    "sequencing": 4,
                    "originality": 3,
                    "mean": 3.75,
                },
                "weak_spots": [
                    "Originality could climb with one case-study lesson",
                ],
            },
            duration_ms=1340,
            status=DRAFT_STATUS_OK,
            created_at=base + timedelta(seconds=11 + len(lessons) * 3 + 2),
        )
    )

    for row in rows:
        db.add(row)
    await db.flush()
    return course


# --------------------------------------------------------------------- #
# Backfill FastAPI cover + outcomes                                     #
# --------------------------------------------------------------------- #


async def _enrich_fastapi_course(db: AsyncSession) -> Course | None:
    """Back-fill the base-seeded FastAPI course's cover + outcomes.

    The original ``_seed`` created the course with ``cover_url=None``
    and no learning outcomes. We add both for the catalog screenshot
    without touching instructor edits — if either is already set, we
    leave it alone.
    """
    res = await db.execute(select(Course).where(Course.slug == "fastapi-from-zero"))
    course = res.scalar_one_or_none()
    if course is None:
        return None
    if not course.cover_url:
        course.cover_url = _cover("fastapi-from-zero")
    if not course.learning_outcomes:
        course.learning_outcomes = [
            "Bootstrap a FastAPI service with sane defaults",
            "Use Pydantic schemas for request + response validation",
            "Wire AsyncSession through Depends without leaking sessions",
            "Ship a first endpoint with OpenAPI documented for free",
        ]
    return course


# --------------------------------------------------------------------- #
# Top-level entry point — invoked from ``app.cli._seed``                #
# --------------------------------------------------------------------- #


async def apply(
    db: AsyncSession,
    *,
    subjects: dict[str, Subject],
    tags: dict[str, Tag],
    instructor: User,
    student: User,
) -> None:
    """Apply every agentic-demo enrichment. Idempotent on re-run."""
    fastapi_course = await _enrich_fastapi_course(db)

    # Make sure the new tags exist (instructor lookups below use them).
    extra_tag_data: list[tuple[str, str]] = [
        ("Beginner", "beginner"),
        ("Python", "python"),
        ("React", "react"),
        ("TypeScript", "typescript"),
        ("Machine Learning", "machine-learning"),
        ("UX", "ux"),
    ]
    for name, slug in extra_tag_data:
        if slug in tags:
            continue
        existing_tag = (
            await db.execute(select(Tag).where(Tag.slug == slug))
        ).scalar_one_or_none()
        if existing_tag is None:
            existing_tag = Tag(name=name, slug=slug)
            db.add(existing_tag)
            await db.flush()
        tags[slug] = existing_tag

    # Make sure subjects we reference are present (the base seed
    # populates these — defensive guard for fresh databases that
    # bypassed the base seed somehow).
    for slug, title in [
        ("programming", "Programming"),
        ("data-science", "Data Science"),
        ("design", "Design"),
    ]:
        if slug in subjects:
            continue
        existing_subject = (
            await db.execute(select(Subject).where(Subject.slug == slug))
        ).scalar_one_or_none()
        if existing_subject is None:
            existing_subject = Subject(title=title, slug=slug)
            db.add(existing_subject)
            await db.flush()
        subjects[slug] = existing_subject

    # ---- New published courses ----
    new_courses: list[Course] = []
    for spec in _NEW_COURSES:
        course = await _ensure_course(
            db, spec=spec, subjects=subjects, tags=tags, instructor=instructor
        )
        new_courses.append(course)

    # ---- Enrollments ----
    if fastapi_course is not None:
        await _ensure_completed_enrollment(
            db, student=student, course=fastapi_course
        )
    # Pick the data-engineering course for an in-flight enrollment.
    data_eng = next(
        (c for c in new_courses if c.slug == "data-engineering-foundations"),
        None,
    )
    if data_eng is not None:
        await _ensure_in_flight_enrollment(
            db,
            student=student,
            course=data_eng,
            progress_fraction=0.5,
        )

    # ---- Tutor turn (agent trace) ----
    if fastapi_course is not None:
        try:
            await _ensure_tutor_turn(
                db, student=student, course=fastapi_course
            )
        except Exception as exc:  # pragma: no cover — defensive
            console.print(f"[yellow]tutor-turn seed skipped: {exc}[/yellow]")

    # ---- Draft trace (self-critique) ----
    try:
        await _ensure_draft_trace(
            db, instructor=instructor, subjects=subjects, tags=tags
        )
    except Exception as exc:  # pragma: no cover — defensive
        console.print(f"[yellow]draft-trace seed skipped: {exc}[/yellow]")


__all__ = ["apply"]
