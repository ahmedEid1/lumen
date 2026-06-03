"""Personalized learning-path agent (Lumen v2 Phase I5).

The cohort-quality differentiator: a learner states a goal in plain
English, and a single LLM-with-structured-output call returns a
sequenced 8-course curriculum that respects the learner's existing
mastery and FSRS load.

**Why a single-shot agent, not a multi-step loop.** The market for
"agents" loves multi-step planner-critic loops; the planner-tutor
(I2) and self-critique authoring (I3) flows already cover that
ground in the project. The learning-path planner is a *different*
shape: the upstream signal — "you have 47 due cards and 12% mastery
in Postgres" — fits in one prompt, the catalog candidates fit in
one prompt, and the output is small enough that a critique-revise
loop would not raise quality enough to pay for the extra round-trip
latency the learner is staring at on the form-submit. We do retry
once on malformed JSON, then surface a clean
``AppError("learning_path.llm_invalid_output")``.

**How the prompt is built.** Four blocks, in order:

1. The learner's goal verbatim.
2. A condensed catalog: the top-20 published courses ranked by
   lesson-chunk similarity to the goal. We retrieve 200 chunks
   across the whole catalog (via ``find_relevant_chunks`` with a
   ``None`` course filter — see ``_condense_catalog``), group by
   course, and take the 20 courses with the most relevant chunks.
   Each course is shown as ``slug | title | difficulty | overview``.
3. The learner's current mastery rollup. Courses with high
   ``mastery_pct`` are listed under "already mastered, do not
   suggest"; courses with low mastery and partial completion are
   listed under "in progress, may continue".
4. The learner's FSRS due-card count. If it's high (>50) the prompt
   instructs the agent to cap milestone 1 to a single new course.

**Tracing.** Every step (catalog retrieval, prompt assembly, LLM
call, validation, persistence) records one ``agent_traces`` row via
``agent_tracer.record_step``, parented to the same ``parent_call_id``
the H1 cost meter writes. The frontend trace surface and the admin
observability page render these end-to-end without extra plumbing.

**Persistence shape.** One ``learning_paths`` row + N
``learning_path_steps`` rows (one per course pick). The agent emits
3-5 milestones with 1-3 courses each; we flatten to a single
ascending ``position`` so the UI doesn't have to reason about the
milestone tree at render time — milestones are visible by grouping
on ``milestone_name`` instead.

**Replan.** ``replan_for_user`` runs the same build with the
current mastery + FSRS load, archives the previous active path
(setting ``status='archived'``), and persists the new one. The
monthly Celery beat job (``app.workers.tasks.learning_path``) calls
this for every user whose ``replanned_at`` is older than 30 days.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.models.agent_trace import TRACE_STATUS_ERROR, TRACE_STATUS_OK
from app.models.course import Course, Lesson, Module
from app.models.learning_path import (
    NEXT_ACTION_KIND_REVIEW_DUE_CARDS,
    NEXT_ACTION_KIND_START_LESSON,
    NEXT_ACTION_KIND_TAKE_QUIZ,
    PATH_STATUS_ACTIVE,
    PATH_STATUS_ARCHIVED,
    STEP_STATUS_COMPLETED,
    STEP_STATUS_PENDING,
    LearningPath,
    LearningPathStep,
)
from app.models.lesson_chunk import LessonChunk
from app.services import agent_tracer
from app.services import fsrs as fsrs_service
from app.services import llm as llm_service
from app.services import mastery as mastery_service
from app.services.embeddings import EmbeddingProvider
from app.services.embeddings import get_provider as get_embedding_provider
from app.services.llm_call_log import call_logged
from app.services.visibility import retrieval_acl_clause

log = get_logger(__name__)


# Feature slug for the H1 cost meter + H7 tracer. Kept stable so
# admin queries can roll up "how much did the learning-path agent
# cost this month" without join gymnastics.
FEATURE = "learning_path.build"

# How many candidate courses we surface to the LLM. A larger window
# would make the prompt longer and the model less decisive; smaller
# would risk excluding a perfectly-relevant course. 20 lands well
# in practice for the 50-100-course catalogs we expect at launch.
DEFAULT_TOP_K_CATALOG = 20

# How many lesson chunks we retrieve before grouping by course.
# More chunks → better course ranking on small catalogs (one course
# might only contribute 2-3 chunks). 200 is enough to cover even
# a 50-course catalog at ~4 chunks per course average.
_CHUNK_RETRIEVAL_TOP_K = 200

# FSRS load threshold above which the prompt tells the agent to
# cap milestone-1 to one new course. Empirically a learner with
# >50 due cards has at least an hour of review per day before any
# new course intake — adding two new courses on top of that is a
# recipe for them quitting the path entirely.
_HEAVY_FSRS_LOAD = 50


# ---------- Structured output schema (validates LLM JSON) ----------


class _PlanMilestone(BaseModel):
    """One milestone in the agent's structured output."""

    name: str = Field(min_length=1, max_length=120)
    # Week-range literal. The agent emits ``"1-4"``, ``"5-12"``,
    # ``"13+"`` and similar; we don't normalise.
    weeks: str = Field(min_length=1, max_length=24)
    course_slugs: list[str] = Field(min_length=1, max_length=3)


class _PlanNextAction(BaseModel):
    """The "what to do today" hint the agent returns."""

    course_slug: str = Field(min_length=1, max_length=220)
    kind: str = Field(
        pattern=f"^({NEXT_ACTION_KIND_START_LESSON}|"
        f"{NEXT_ACTION_KIND_REVIEW_DUE_CARDS}|"
        f"{NEXT_ACTION_KIND_TAKE_QUIZ})$"
    )


class _Plan(BaseModel):
    """Top-level plan shape the LLM must return."""

    milestones: list[_PlanMilestone] = Field(min_length=3, max_length=5)
    rationale: str = Field(min_length=1, max_length=4_000)
    next_action: _PlanNextAction | None = None

    @field_validator("milestones")
    @classmethod
    def _has_course_picks(cls, v: list[_PlanMilestone]) -> list[_PlanMilestone]:
        if not any(m.course_slugs for m in v):
            raise ValueError("milestones must include at least one course pick")
        return v


# ---------- System prompt (iterate freely here) ----------


_SYSTEM_PROMPT = """\
You are Lumen's learning-path agent — the planner that turns a learner's
plain-English career or skill goal into a sequenced 8-course curriculum
drawn from Lumen's catalog.

Lumen is an open-source, AI-first learning platform. The learner has
spaced-repetition cards, mastery rollups, and a tutor that cites
lesson chunks. Your job is to pick the right courses, in the right
order, at a pace the learner can actually sustain.

You will be given four blocks of context:

  - GOAL: the learner's stated goal verbatim.
  - CANDIDATE COURSES: the top catalog matches retrieved via
    semantic similarity against the goal. Each entry has
    slug | title | difficulty | overview. **You MUST only pick
    courses from this list — never invent slugs.**
  - LEARNER MASTERY: per-course rollups the learner has already
    earned. Courses with mastery_pct >= 75 are "already mastered"
    and MUST be excluded from the plan. Courses with mastery_pct
    between 25 and 75 are "in progress" and MAY be continued.
  - FSRS LOAD: the learner's current due-card count. If it's high
    (more than 50) you MUST cap milestone 1 to a single new course
    so the learner doesn't drown in review work.

Output ONE JSON object with this exact shape — no prose, no
markdown fences, no commentary:

{
  "milestones": [
    {"name": "Foundations", "weeks": "1-4",
     "course_slugs": ["python-basics", "git-and-the-shell"]},
    {"name": "Core backend", "weeks": "5-12",
     "course_slugs": ["intro-to-fastapi", "postgres-fundamentals"]},
    {"name": "Production", "weeks": "13+",
     "course_slugs": ["deploying-fastapi", "observability-basics"]}
  ],
  "rationale": "One paragraph (200-400 words) explaining the
    sequencing decisions, any prerequisite assumptions, and the
    learner's existing strengths/gaps you accounted for.",
  "next_action": {
    "course_slug": "python-basics",
    "kind": "start_lesson"
  }
}

Hard rules:

  1. EVERY course_slug in your output MUST appear in CANDIDATE
     COURSES. Invented slugs are a hard failure.
  2. EXCLUDE any course where the learner already has
     mastery_pct >= 75.
  3. Produce 3-5 milestones total, each with 1-3 courses. The
     whole plan should be 5-9 courses (target 8).
  4. Order matters — milestone 1 is "do this first", milestone N is
     "do this last". Within a milestone, the course_slugs array is
     also ordered: list prerequisites before dependents.
  5. If FSRS_LOAD > 50, milestone 1 has at most ONE course.
  6. The "next_action.kind" field must be one of:
     "start_lesson" | "review_due_cards" | "take_quiz".
     If FSRS_LOAD > 0, prefer "review_due_cards".
  7. The "next_action.course_slug" must be a slug from your own
     milestones (or any candidate slug if kind is
     "review_due_cards").

Return ONLY the JSON object. No prose before or after.
"""


# ---------- Constraint + digest dataclasses ----------


@dataclass(frozen=True)
class CourseDigest:
    """One candidate course as it appears in the LLM prompt.

    A condensed projection of ``courses`` — slug + title + difficulty
    + overview + the chunk hits that earned this row a spot in the
    top-K. Held by ``_condense_catalog`` and serialised into the
    prompt as one line per course.
    """

    course_id: str
    slug: str
    title: str
    difficulty: str
    overview: str
    chunk_hits: int


@dataclass(frozen=True)
class Constraints:
    """Per-learner filters the LLM consumes.

    ``mastered_slugs`` and ``in_progress_slugs`` are sourced from
    ``mastery.per_course_mastery``. ``due_card_count`` is the FSRS
    queue depth; the prompt uses it to throttle new-course intake.
    """

    mastered_slugs: list[str]
    in_progress_slugs: list[str]
    due_card_count: int


# ---------- Public API ----------


async def build_path(
    db: AsyncSession,
    *,
    user_id: str,
    goal: str,
) -> LearningPath:
    """Run the agent, persist the result. Archives any prior active path.

    Wraps the single LLM call in ``call_logged`` so the H1 cost meter
    records the spend, and records every step
    (``catalog_retrieval``, ``llm_call``, ``validation``,
    ``persistence``) via ``agent_tracer.record_step`` so the
    observability surface can render the agent's reasoning trail.

    On LLM-output failure (after one retry) raises
    ``AppError(code="learning_path.llm_invalid_output")`` which the
    API converts to a 502 — the upstream model produced something
    unusable; the request handler surfaces "the AI returned an
    unexpected response" rather than a generic 500.
    """
    goal = goal.strip()
    if not goal:
        raise AppError(
            "Goal is required to build a learning path.",
            code="learning_path.empty_goal",
        )

    # ---------- 1. Retrieve catalog candidates ----------
    catalog_step = await agent_tracer.record_step(
        db,
        user_id=user_id,
        feature=FEATURE,
        step="catalog_retrieval.start",
        step_index=0,
        payload={"goal_head": goal[:120]},
    )
    catalog = await _condense_catalog(
        db, goal, top_k=DEFAULT_TOP_K_CATALOG, requesting_user_id=user_id
    )
    await agent_tracer.record_step(
        db,
        user_id=user_id,
        feature=FEATURE,
        step="catalog_retrieval.done",
        step_index=1,
        parent_trace_id=catalog_step.id if catalog_step else None,
        payload={"candidate_count": len(catalog)},
    )
    if not catalog:
        # No published courses in the catalog yet. We could still ask
        # the LLM, but it'd have nothing to pick from and the retry
        # loop would burn tokens for a guaranteed failure.
        raise AppError(
            "The catalog is empty — no courses to build a path from.",
            code="learning_path.empty_catalog",
        )

    # ---------- 2. Pull per-learner constraints ----------
    constraints = await _load_constraints(db, user_id)
    await agent_tracer.record_step(
        db,
        user_id=user_id,
        feature=FEATURE,
        step="constraints_loaded",
        step_index=2,
        payload={
            "mastered_count": len(constraints.mastered_slugs),
            "in_progress_count": len(constraints.in_progress_slugs),
            "due_card_count": constraints.due_card_count,
        },
    )

    # ---------- 3. Build the prompt ----------
    user_prompt = _build_user_prompt(goal=goal, catalog=catalog, constraints=constraints)

    # ---------- 4. Call the LLM (metered) with one-shot retry ----------
    plan, llm_raw = await _chat_with_retry(
        db=db,
        user_id=user_id,
        system=_SYSTEM_PROMPT,
        user=user_prompt,
        candidate_slugs={c.slug for c in catalog},
    )
    await agent_tracer.record_step(
        db,
        user_id=user_id,
        feature=FEATURE,
        step="validation.passed",
        step_index=5,
        payload={"raw_head": (llm_raw or "")[:240]},
    )

    # ---------- 5. Resolve slugs → ORM courses ----------
    slug_to_course = await _resolve_slugs(
        db,
        slugs=[s for m in plan.milestones for s in m.course_slugs],
    )
    # Drop any unresolved slugs defensively (the validator already
    # caught invented ones, but a soft-deleted course can slip
    # through the candidate list if the catalog snapshot was taken
    # before the deletion).
    resolved_milestones = [
        (m, [s for s in m.course_slugs if s in slug_to_course]) for m in plan.milestones
    ]
    if not any(slugs for _, slugs in resolved_milestones):
        raise AppError(
            "The AI suggested only courses that no longer exist.",
            code="learning_path.llm_invalid_output",
        )

    # ---------- 6. Archive prior active path, persist new one ----------
    await _archive_active(db, user_id=user_id)

    path = LearningPath(
        user_id=user_id,
        goal=goal,
        rationale=plan.rationale,
        next_action=_next_action_dict(plan.next_action, slug_to_course),
        status=PATH_STATUS_ACTIVE,
    )
    db.add(path)
    await db.flush()

    position = 0
    for milestone, resolved_slugs in resolved_milestones:
        for slug in resolved_slugs:
            course = slug_to_course[slug]
            db.add(
                LearningPathStep(
                    path_id=path.id,
                    position=position,
                    milestone_name=milestone.name,
                    milestone_weeks=milestone.weeks,
                    course_id=course.id,
                    course_slug=course.slug,
                    status=STEP_STATUS_PENDING,
                )
            )
            position += 1
    await db.flush()

    await agent_tracer.record_step(
        db,
        user_id=user_id,
        feature=FEATURE,
        step="persisted",
        step_index=6,
        payload={"path_id": path.id, "step_count": position},
    )
    # Re-load the path with its steps eagerly so callers can hand
    # the row straight to a Pydantic response without lazy-load
    # surprises after the session closes.
    return await _load_path_with_steps(db, path.id)


async def replan_for_user(db: AsyncSession, *, user_id: str) -> LearningPath | None:
    """Re-run the build for a user's active path, archives the old one.

    Returns ``None`` if the user has no active path (the monthly
    beat job filters by ``replanned_at`` before calling this, but
    the function is robust to being called against any user).
    """
    current = await get_active_path(db, user_id=user_id)
    if current is None:
        return None
    goal = current.goal
    # ``build_path`` archives the old path internally, so we just
    # call it again with the same goal.
    return await build_path(db, user_id=user_id, goal=goal)


async def mark_step_complete(
    db: AsyncSession,
    *,
    step_id: str,
    user_id: str,
) -> LearningPathStep:
    """Flip a step to completed. Requires the step's path to belong to ``user_id``.

    We don't cascade an enrolment progress update from here — the
    step's completion is a path-local signal (the learner is
    walking the path, regardless of whether they finished every
    lesson in the course). Enrolment progress flows the other
    direction in a future enhancement (the lesson-complete handler
    could flip pending → in_progress on any matching step), but
    that path isn't wired in v1.
    """
    step = await db.get(LearningPathStep, step_id)
    if step is None:
        raise NotFoundError("Learning path step not found.", code="not_found")
    path = await db.get(LearningPath, step.path_id)
    if path is None or path.user_id != user_id:
        # Phrasing as "not found" rather than "forbidden" so we
        # don't leak path ids across users.
        raise NotFoundError("Learning path step not found.", code="not_found")
    step.status = STEP_STATUS_COMPLETED
    await db.flush()
    return step


async def get_active_path(db: AsyncSession, *, user_id: str) -> LearningPath | None:
    """Return the user's single active path (or ``None``)."""
    stmt = (
        select(LearningPath)
        .where(
            LearningPath.user_id == user_id,
            LearningPath.status == PATH_STATUS_ACTIVE,
        )
        .options(selectinload(LearningPath.steps))
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_today_action(db: AsyncSession, *, user_id: str) -> dict[str, Any] | None:
    """Bundle the agent's next-action hint with current FSRS load.

    Shape returned: ``{course_slug, kind, lesson_id_if_applicable,
    due_review_count}`` or ``None`` if no active path. The lesson id
    is best-effort — we pick the first incomplete lesson in the
    suggested course; if there isn't a clear pick, we leave it
    null and let the UI deep-link to the course page instead.
    """
    path = await get_active_path(db, user_id=user_id)
    if path is None:
        return None
    fsrs_stats = await fsrs_service.stats(db, user_id=user_id)
    due = fsrs_stats.get("due", 0)
    action = path.next_action or {}
    course_slug = action.get("course_slug")
    kind = action.get("kind") or NEXT_ACTION_KIND_START_LESSON
    lesson_id: str | None = None
    if course_slug and kind == NEXT_ACTION_KIND_START_LESSON:
        lesson_id = await _first_lesson_for_slug(db, slug=course_slug, requesting_user_id=user_id)
    return {
        "course_slug": course_slug,
        "kind": kind,
        "lesson_id_if_applicable": lesson_id,
        "due_review_count": int(due),
    }


# ---------- Catalog condensation ----------


async def _condense_catalog(
    db: AsyncSession,
    goal: str,
    *,
    top_k: int = DEFAULT_TOP_K_CATALOG,
    embedding_provider: EmbeddingProvider | None = None,
    requesting_user_id: str | None = None,
) -> list[CourseDigest]:
    """Top-K courses ranked by chunk similarity to the goal.

    The standard ``find_relevant_chunks`` helper scopes to a single
    course; we want cross-catalog retrieval here. We replicate the
    SELECT (with the cosine distance order-by) but drop the
    course-id filter, then group the chunk hits by their parent
    course and rank courses by hit count.

    Persists one ``retrieval_audits`` row capturing the query +
    chunk ids + similarity scores so the observability surface
    shows the retrieval that drove the planner's candidate list.
    """
    if not goal.strip():
        return []
    prov = embedding_provider or get_embedding_provider()
    [query_vec] = prov.embed([goal])

    distance_col = LessonChunk.embedding.cosine_distance(query_vec).label("distance")
    stmt = (
        select(
            LessonChunk.id.label("chunk_id"),
            distance_col,
            Course.id.label("course_id"),
            Course.slug,
            Course.title,
            Course.difficulty,
            Course.overview,
        )
        .join(Lesson, Lesson.id == LessonChunk.lesson_id)
        .join(Module, Module.id == Lesson.module_id)
        .join(Course, Course.id == Module.course_id)
        .where(
            # Cross-course retrieval ACL (S2.7 / ADR-0029 §D2, R-S12): publicly
            # listed OR the requesting user's own live, non-failed courses.
            # Never leaks another user's private course.
            retrieval_acl_clause(requesting_user_id),
            Lesson.deleted_at.is_(None),
        )
        .order_by(distance_col)
        .limit(_CHUNK_RETRIEVAL_TOP_K)
    )
    rows = (await db.execute(stmt)).all()

    # Group by course id, preserve first-seen ordering (which already
    # reflects best-chunk-first ranking thanks to the ORDER BY).
    by_course: dict[str, CourseDigest] = {}
    hit_counts: dict[str, int] = {}
    for row in rows:
        cid = row.course_id
        hit_counts[cid] = hit_counts.get(cid, 0) + 1
        if cid not in by_course:
            by_course[cid] = CourseDigest(
                course_id=cid,
                slug=row.slug,
                title=row.title,
                difficulty=str(row.difficulty),
                overview=(row.overview or "")[:280],
                chunk_hits=0,
            )

    # If chunk-based retrieval came up empty (a catalog whose
    # lessons haven't been embedded yet — possible in dev), fall
    # back to the most-recently-published live courses so the
    # agent has *something* to pick from.
    if not by_course:
        return await _fallback_recent_published(db, top_k, requesting_user_id=requesting_user_id)

    # Re-rank by hit count + add the count for the prompt.
    digests = sorted(
        (
            CourseDigest(
                course_id=d.course_id,
                slug=d.slug,
                title=d.title,
                difficulty=d.difficulty,
                overview=d.overview,
                chunk_hits=hit_counts[d.course_id],
            )
            for d in by_course.values()
        ),
        key=lambda d: (-d.chunk_hits, d.title),
    )
    return digests[:top_k]


async def _fallback_recent_published(
    db: AsyncSession, top_k: int, *, requesting_user_id: str | None = None
) -> list[CourseDigest]:
    """Last-resort candidate list when no chunks have been embedded.

    Dev environments where ``embeddings_ingest`` hasn't run on the
    seeded courses, and brand-new catalogs in the first hour after
    deploy, both hit this path. We return the most-recent live courses
    the requester may see (publicly listed OR their own — S2.7) so the
    agent isn't reaching for nothing.
    """
    stmt = (
        select(Course)
        .where(retrieval_acl_clause(requesting_user_id))
        .order_by(Course.published_at.desc().nullslast(), Course.created_at.desc())
        .limit(top_k)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        CourseDigest(
            course_id=c.id,
            slug=c.slug,
            title=c.title,
            difficulty=str(c.difficulty),
            overview=(c.overview or "")[:280],
            chunk_hits=0,
        )
        for c in rows
    ]


# ---------- Constraints ----------


async def _load_constraints(db: AsyncSession, user_id: str) -> Constraints:
    """Mastery rollup + FSRS due count for the LLM prompt."""
    mastery_rows = await mastery_service.per_course_mastery(db, user_id)
    mastered: list[str] = []
    in_progress: list[str] = []
    for row in mastery_rows:
        # Tracks the rule in the system prompt.
        if row.mastery_pct >= 75.0:
            mastered.append(row.slug)
        elif row.completion_pct > 0 and row.mastery_pct >= 25.0:
            in_progress.append(row.slug)
    fsrs_stats = await fsrs_service.stats(db, user_id=user_id)
    return Constraints(
        mastered_slugs=mastered,
        in_progress_slugs=in_progress,
        due_card_count=int(fsrs_stats.get("due", 0)),
    )


# ---------- Prompt assembly ----------


def _build_user_prompt(
    *,
    goal: str,
    catalog: list[CourseDigest],
    constraints: Constraints,
) -> str:
    """Stitch goal + candidates + constraints into one user-turn prompt."""
    candidate_lines = "\n".join(
        f"- {c.slug} | {c.title} | {c.difficulty} | {c.overview}" for c in catalog
    )
    mastered_block = ", ".join(constraints.mastered_slugs) or "(none)"
    progress_block = ", ".join(constraints.in_progress_slugs) or "(none)"
    return (
        f"GOAL:\n{goal}\n\n"
        f"CANDIDATE COURSES (slug | title | difficulty | overview):\n"
        f"{candidate_lines}\n\n"
        f"LEARNER MASTERY:\n"
        f"- already mastered (exclude): {mastered_block}\n"
        f"- in progress (may continue): {progress_block}\n\n"
        f"FSRS_LOAD: {constraints.due_card_count} due cards"
        + (
            " — HIGH: cap milestone 1 to one new course."
            if constraints.due_card_count > _HEAVY_FSRS_LOAD
            else ""
        )
    )


# ---------- LLM call + validation ----------


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json(raw: str) -> str:
    """Best-effort: strip markdown fences off the model's reply."""
    fence = _JSON_FENCE_RE.search(raw)
    if fence:
        return fence.group(1).strip()
    return raw.strip()


def _try_parse(raw: str, *, candidate_slugs: set[str]) -> tuple[_Plan | None, str | None]:
    """Validate raw LLM output. Returns ``(plan, None)`` or ``(None, error)``.

    The slug-membership check happens *here* (not in the Pydantic
    model) because the candidate list is dynamic per-request — a
    Pydantic ``field_validator`` would have to close over it via a
    class-level state hack. Doing it imperatively keeps the model
    simple and the error message specific.
    """
    body = _extract_json(raw)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return None, f"JSON parse error: {exc.msg} at line {exc.lineno}"
    try:
        plan = _Plan.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []))
        msg = first.get("msg", "validation error")
        return None, f"validation error at {loc or '<root>'}: {msg}"

    # Slug membership: every emitted slug must be in the candidate
    # list. Inventing slugs is the #1 LLM failure mode for this
    # task; we surface it back to the model on retry.
    invented: list[str] = []
    for m in plan.milestones:
        for slug in m.course_slugs:
            if slug not in candidate_slugs:
                invented.append(slug)
    if invented:
        sample = ", ".join(invented[:5])
        return None, (
            f"course_slugs not in candidate list: {sample}. "
            "Every slug must appear verbatim in CANDIDATE COURSES."
        )
    if plan.next_action and plan.next_action.course_slug not in candidate_slugs:
        return None, (
            f"next_action.course_slug not in candidate list: {plan.next_action.course_slug}"
        )
    return plan, None


async def _chat_with_retry(
    *,
    db: AsyncSession,
    user_id: str,
    system: str,
    user: str,
    candidate_slugs: set[str],
) -> tuple[_Plan, str]:
    """One LLM call, validate, retry once on failure.

    Each turn lands a metered ``llm_calls`` row via ``call_logged``
    and one ``agent_traces`` row via ``record_step``. Two failures
    raise the clean ``learning_path.llm_invalid_output`` error.
    """
    provider = llm_service.get_provider()
    messages = [
        llm_service.ChatMessage(role="system", content=system),
        llm_service.ChatMessage(role="user", content=user),
    ]

    # ---- Turn 1 ----
    await agent_tracer.record_step(
        db,
        user_id=user_id,
        feature=FEATURE,
        step="llm_call.start",
        step_index=3,
        payload={"turn": 1, "provider": getattr(provider, "name", "?")},
    )
    response = await call_logged(
        provider,
        messages,
        user_id=user_id,
        feature=FEATURE,
        session=db,
        temperature=0.2,
    )
    raw = response.text
    plan, err = _try_parse(raw, candidate_slugs=candidate_slugs)
    if plan is not None:
        return plan, raw
    await agent_tracer.record_step(
        db,
        user_id=user_id,
        feature=FEATURE,
        step="llm_call.invalid_output",
        step_index=4,
        status=TRACE_STATUS_ERROR,
        payload={"turn": 1, "error": err, "raw_head": raw[:240]},
    )

    # ---- Turn 2 (retry) ----
    messages.extend(
        [
            llm_service.ChatMessage(role="assistant", content=raw),
            llm_service.ChatMessage(
                role="user",
                content=(
                    "Your previous response was invalid. "
                    f"Reason: {err}\n\n"
                    "Reply again with a corrected JSON object that "
                    "matches the schema exactly. No prose, no markdown "
                    "fences, no commentary."
                ),
            ),
        ]
    )
    response2 = await call_logged(
        provider,
        messages,
        user_id=user_id,
        feature=FEATURE,
        session=db,
        temperature=0.2,
    )
    raw2 = response2.text
    plan, err2 = _try_parse(raw2, candidate_slugs=candidate_slugs)
    if plan is not None:
        await agent_tracer.record_step(
            db,
            user_id=user_id,
            feature=FEATURE,
            step="llm_call.recovered_on_retry",
            step_index=4,
            status=TRACE_STATUS_OK,
            payload={"turn": 2},
        )
        return plan, raw2

    log.warning(
        "learning_path_llm_bad_output",
        user_id=user_id,
        first_error=err,
        retry_error=err2,
        first_head=raw[:200],
        retry_head=raw2[:200],
    )
    await agent_tracer.record_step(
        db,
        user_id=user_id,
        feature=FEATURE,
        step="llm_call.invalid_output",
        step_index=5,
        status=TRACE_STATUS_ERROR,
        payload={"turn": 2, "error": err2, "raw_head": raw2[:240]},
    )
    raise AppError(
        "The AI returned an invalid learning-path response. Try again later.",
        code="learning_path.llm_invalid_output",
    )


# ---------- Persistence helpers ----------


async def _archive_active(db: AsyncSession, *, user_id: str) -> None:
    """Mark any existing active path as archived. Idempotent."""
    stmt = select(LearningPath).where(
        LearningPath.user_id == user_id,
        LearningPath.status == PATH_STATUS_ACTIVE,
    )
    for row in (await db.execute(stmt)).scalars().all():
        row.status = PATH_STATUS_ARCHIVED
    await db.flush()


async def _resolve_slugs(db: AsyncSession, *, slugs: list[str]) -> dict[str, Course]:
    """Look up live, published courses by slug. Drops missing entries."""
    if not slugs:
        return {}
    # Dedupe while preserving order; the LLM might mention the same
    # slug across milestones (we let the validator catch egregious
    # cases but a stray repeat shouldn't break persistence).
    seen: dict[str, None] = {}
    for s in slugs:
        seen[s] = None
    unique = list(seen.keys())
    rows = await db.execute(
        select(Course).where(
            Course.slug.in_(unique),
            Course.deleted_at.is_(None),
        )
    )
    return {c.slug: c for c in rows.scalars().all()}


def _next_action_dict(
    action: _PlanNextAction | None,
    slug_to_course: dict[str, Course],
) -> dict[str, Any] | None:
    """Normalise the agent's ``next_action`` for JSONB storage."""
    if action is None:
        return None
    # If the slug doesn't resolve (e.g. the only mastered course
    # somehow leaked into the suggestion), drop the action rather
    # than persisting a hint to a non-existent course.
    if action.kind == NEXT_ACTION_KIND_REVIEW_DUE_CARDS:
        # ``review_due_cards`` is a global action; the slug is just
        # a hint at which course to review first.
        return {"course_slug": action.course_slug, "kind": action.kind}
    if action.course_slug not in slug_to_course:
        return None
    return {"course_slug": action.course_slug, "kind": action.kind}


async def _load_path_with_steps(db: AsyncSession, path_id: str) -> LearningPath:
    """Re-load a path with its steps eagerly attached."""
    stmt = (
        select(LearningPath)
        .where(LearningPath.id == path_id)
        .options(selectinload(LearningPath.steps))
    )
    return (await db.execute(stmt)).scalar_one()


async def _first_lesson_for_slug(
    db: AsyncSession, *, slug: str, requesting_user_id: str | None = None
) -> str | None:
    """Return the first live lesson id in the course (or ``None``).

    Used by ``get_today_action`` to deep-link "start lesson" into a
    specific lesson rather than dumping the learner on the course
    detail page. Picks the lowest-order lesson in the lowest-order
    module; that's the natural "begin here" pick. The course must be
    visible to the requester (publicly listed OR their own — S2.7).
    """
    stmt = (
        select(Lesson.id)
        .join(Module, Module.id == Lesson.module_id)
        .join(Course, Course.id == Module.course_id)
        .where(
            Course.slug == slug,
            retrieval_acl_clause(requesting_user_id),
            Lesson.deleted_at.is_(None),
        )
        .order_by(Module.order.asc(), Lesson.order.asc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


# ---------- Authorisation helper (used by the API layer) ----------


def ensure_owner_or_admin(*, path_user_id: str, requesting_user_id: str, is_admin: bool) -> None:
    """Raise ForbiddenError unless the caller owns the path or is admin.

    Surfaced here (not just in the API module) so the Celery beat
    job and any future MCP tool that calls into this service can
    share the same gate.
    """
    if is_admin:
        return
    if path_user_id != requesting_user_id:
        raise ForbiddenError(
            "Not allowed to operate on another learner's path.",
            code="auth.forbidden",
        )


__all__ = [
    "FEATURE",
    "Constraints",
    "CourseDigest",
    "build_path",
    "ensure_owner_or_admin",
    "get_active_path",
    "get_today_action",
    "mark_step_complete",
    "replan_for_user",
]


# Keep a sentinel for the workers package so its lazy "now" reference
# (used by the beat-job staleness filter) lives in one place.
def _now_utc() -> datetime:
    return datetime.now(UTC)
