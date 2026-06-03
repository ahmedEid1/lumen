"""Demo seed bundle for the single-VM demo deploy.

Drops three published courses and one demo student into the database on
top of whatever the base seed (``python -m app.cli seed``) put there:

1. **Intro to Python** — every lesson has a quiz, so the live demo can
   show the quiz UI + cert flow end-to-end.
2. **Data Structures** — hand-curated content imported via the same
   shape that the Phase E3 multi-modal ingest produces (so the demo
   shows the result of "ingest a URL → committed draft" without
   actually hitting YouTube/Notion at seed time, which would be flaky
   on a cold deploy).
3. **Async Web Apps in FastAPI** — designed for the AI-tutor demo:
   chunked, citation-rich lessons that give the RAG tutor real
   substance to cite back.

Plus one demo learner:

    demo@lumen.test / Demo!2026

…enrolled in the Data Structures course with progress already in flight
(first module complete) so the dashboard doesn't look empty on the live
demo URL.

Idempotent: a re-run upserts every row by stable lookup key (slug for
courses, email for users, etc) and skips anything that already exists.
Safe to run after every deploy without polluting the DB.

Invoke via:

    python -m app.cli demo-seed       # in the api container
    make demo-seed                    # local convenience

The :mod:`app.cli` ``seed`` command must have been run first so the
shared Subject / Tag / instructor rows already exist — this bundle only
adds *demo-flavoured* content on top.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from rich.console import Console
from sqlalchemy import select

from app.core.security import hash_password
from app.db.base import get_sessionmaker
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
from app.models.user import Role, User

console = Console()


# --------------------------------------------------------------------- #
# Helpers — mirror the patterns in app.cli so re-runs are idempotent.   #
# --------------------------------------------------------------------- #


async def _get_or_create(db, model, *, lookup: dict, defaults: dict | None = None):
    """Upsert by stable lookup keys. Returns (instance, created)."""
    res = await db.execute(select(model).filter_by(**lookup))
    obj = res.scalar_one_or_none()
    if obj is not None:
        return obj, False
    obj = model(**lookup, **(defaults or {}))
    db.add(obj)
    await db.flush()
    return obj, True


async def _ensure_user(db, *, email: str, full_name: str, password: str, role: Role) -> User:
    res = await db.execute(select(User).where(User.email == email))
    user = res.scalar_one_or_none()
    if user is None:
        user = User(
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            role=role,
            email_verified_at=datetime.now(UTC) - timedelta(days=1),
        )
        db.add(user)
        await db.flush()
    return user


# --------------------------------------------------------------------- #
# Lesson content                                                        #
# --------------------------------------------------------------------- #
#
# Lesson bodies are hand-authored so the live demo has substance on
# first click without needing to call out to YouTube / Notion / Groq at
# seed time. The chunks are short on purpose (~120-200 words) so the
# embeddings pipeline (Phase E0) can index them quickly during the
# post-seed reindex step — the RAG tutor relies on these chunks to
# generate citations that line up with real lesson IDs.


def _quiz(question: str, choices: list[tuple[str, str]], answer_id: str) -> dict[str, Any]:
    """Quick helper to build a single-question quiz block.

    Lesson.data shape is the same one the API exposes; see
    apps/backend/app/schemas/lesson.py for the source of truth.
    """
    return {
        "type": "quiz",
        "pass_score": 60,
        "questions": [
            {
                "id": "q1",
                "prompt": question,
                "kind": "single",
                "choices": [{"id": cid, "text": text} for cid, text in choices],
                "answer_keys": [answer_id],
            }
        ],
    }


def _text(body_markdown: str) -> dict[str, Any]:
    return {"type": "text", "body_markdown": body_markdown}


# ---- Course 1: Intro to Python (quiz on every lesson) ---------------- #

INTRO_PYTHON_MODULES: list[dict[str, Any]] = [
    {
        "title": "Getting started",
        "description": "Install Python, run your first script, understand the REPL.",
        "lessons": [
            {
                "title": "Why Python?",
                "type": LessonType.text,
                "data": _text(
                    "Python is a high-level, dynamically-typed language designed "
                    "to be readable. Its standard library is enormous, its package "
                    "ecosystem (PyPI) covers nearly every domain, and a beginner "
                    "can build something useful in their first week.\n\n"
                    "In this course we'll learn enough Python to read other "
                    "people's code, build small scripts, and graduate to "
                    "frameworks like FastAPI and Django."
                ),
            },
            {
                "title": "Quick check: Why Python?",
                "type": LessonType.quiz,
                "data": _quiz(
                    "Which of these is NOT a reason Python is widely used?",
                    [
                        ("a", "Readable syntax"),
                        ("b", "Large standard library"),
                        ("c", "Always faster than C"),
                        ("d", "Big package ecosystem"),
                    ],
                    "c",
                ),
            },
            {
                "title": "Your first script",
                "type": LessonType.text,
                "data": _text(
                    "Create a file `hello.py` containing:\n\n"
                    '```python\nprint("Hello, Lumen!")\n```\n\n'
                    "Run it with `python hello.py`. The `print` builtin writes "
                    "to standard output; the string is a literal. Notice there's "
                    "no main() boilerplate — top-level statements just run."
                ),
            },
            {
                "title": "Quick check: First script",
                "type": LessonType.quiz,
                "data": _quiz(
                    'What does `print("Hello, Lumen!")` write?',
                    [
                        ("a", "Hello, Lumen! to stdout"),
                        ("b", "Nothing — print is not a builtin"),
                        ("c", "An error — strings need single quotes"),
                    ],
                    "a",
                ),
            },
        ],
    },
    {
        "title": "Values and types",
        "description": "Numbers, strings, booleans, None, and how Python infers types.",
        "lessons": [
            {
                "title": "Variables and assignment",
                "type": LessonType.text,
                "data": _text(
                    "Python variables are *names* bound to *values*. Assignment "
                    "with `=` binds a name to whatever's on the right:\n\n"
                    '```python\nx = 42\nname = "Lumen"\nactive = True\n```\n\n'
                    "Names can be rebound to a different type later — Python is "
                    "dynamically typed."
                ),
            },
            {
                "title": "Quick check: Variables",
                "type": LessonType.quiz,
                "data": _quiz(
                    "After `x = 42; x = 'hello'`, what is the type of `x`?",
                    [
                        ("a", "int — Python pins the type at first assignment"),
                        ("b", "str — the latest assignment wins"),
                        ("c", "TypeError — you can't change type"),
                    ],
                    "b",
                ),
            },
        ],
    },
]


# ---- Course 2: Data Structures (simulated multi-modal ingest) -------- #
#
# This course is shaped like the output of Lumen's content-ingest
# pipeline (Phase E3) — one module per logical chapter, each with a
# short lesson summary. In production an instructor would paste a TED
# talk URL or a Notion page; here we hardcode the chunks so the demo
# works offline.

DATA_STRUCTURES_MODULES: list[dict[str, Any]] = [
    {
        "title": "Arrays and lists",
        "description": "Contiguous-memory sequences and what they're good for.",
        "lessons": [
            {
                "title": "Why arrays are fast",
                "type": LessonType.text,
                "data": _text(
                    "Arrays store elements in contiguous memory. Indexing is "
                    "O(1) — the CPU computes `base + i * sizeof(element)` and "
                    "jumps. The cost: inserting at the front is O(n) because "
                    "every later element has to shift one slot to the right.\n\n"
                    "Python's `list` is a dynamic array (a buffer that grows by "
                    "geometric resize), not a linked list. Appending is amortised "
                    "O(1); inserting at position 0 is O(n)."
                ),
            },
        ],
    },
    {
        "title": "Hash tables",
        "description": "Average O(1) lookups via hashing — how, and when it goes wrong.",
        "lessons": [
            {
                "title": "How a hash table works",
                "type": LessonType.text,
                "data": _text(
                    "A hash table maps keys to values using a *hash function* "
                    "that turns a key into a bucket index. Lookup is average "
                    "O(1) — compute the hash, jump to the bucket, compare keys.\n\n"
                    "Two keys colliding into the same bucket is handled either "
                    "by *chaining* (each bucket is a linked list) or *open "
                    "addressing* (probe forward until you find an empty slot). "
                    "Python's `dict` uses open addressing with a perturbation "
                    "probing sequence."
                ),
            },
            {
                "title": "When hash tables go quadratic",
                "type": LessonType.text,
                "data": _text(
                    "If your hash function clusters keys into a small range, "
                    "every insert collides and the table degenerates to a "
                    "linked list — O(n) lookups. CPython mitigates this via "
                    "hash randomisation (`PYTHONHASHSEED`); attackers who "
                    "control input keys would otherwise pin you into quadratic "
                    "worst case (a classic DoS vector)."
                ),
            },
        ],
    },
    {
        "title": "Trees and graphs",
        "description": "When relationships matter more than positions.",
        "lessons": [
            {
                "title": "Binary search trees",
                "type": LessonType.text,
                "data": _text(
                    "A binary search tree (BST) stores keys such that the left "
                    "subtree is < the node, and the right subtree is > the "
                    "node. Lookup, insert, and delete are all O(log n) — if "
                    "the tree stays balanced.\n\n"
                    "An unbalanced BST (e.g. you inserted keys in sorted "
                    "order) degenerates to a linked list with O(n) ops. "
                    "Self-balancing variants — red-black, AVL — re-balance on "
                    "every mutation to preserve the log n guarantee."
                ),
            },
        ],
    },
]


# ---- Course 3: Async Web Apps in FastAPI (the AI-tutor demo) -------- #

ASYNC_FASTAPI_MODULES: list[dict[str, Any]] = [
    {
        "title": "The async mental model",
        "description": "What `async`/`await` actually changes about how your code runs.",
        "lessons": [
            {
                "title": "Concurrency is not parallelism",
                "type": LessonType.text,
                "data": _text(
                    "Async lets a single thread interleave many in-flight tasks. "
                    "While one task is waiting on the network, the event loop "
                    "runs another. You don't get a second CPU — you get better "
                    "use of the one you have when the bottleneck is I/O.\n\n"
                    "If your bottleneck is compute (numpy, image processing, "
                    "tight Python loops), async won't help. Use a process pool "
                    "instead, or push that work to a Celery worker."
                ),
            },
            {
                "title": "What `await` does",
                "type": LessonType.text,
                "data": _text(
                    "`await` suspends the current coroutine until the awaited "
                    "thing finishes. While suspended, the event loop runs other "
                    "ready coroutines. The key insight: a function annotated "
                    "with `async def` doesn't *do* anything until you `await` "
                    "it (or pass it to `asyncio.create_task`). Calling it just "
                    "returns a coroutine object."
                ),
            },
        ],
    },
    {
        "title": "FastAPI fundamentals",
        "description": "Routing, dependency injection, and Pydantic schemas.",
        "lessons": [
            {
                "title": "Path operations",
                "type": LessonType.text,
                "data": _text(
                    "FastAPI builds a route from a decorator + function:\n\n"
                    "```python\n@router.get('/items/{item_id}')\n"
                    "async def read_item(item_id: int) -> Item:\n"
                    "    return await items_repo.get(item_id)\n```\n\n"
                    "The `int` annotation on `item_id` is the validator: a "
                    "request to `/items/abc` returns 422 automatically. The "
                    "return type `Item` is the response model — FastAPI "
                    "validates the response before sending it, which catches "
                    "drift between the model layer and the contract."
                ),
            },
            {
                "title": "Dependency injection",
                "type": LessonType.text,
                "data": _text(
                    "`Depends(...)` lets you compose request-scoped resources: "
                    "a DB session, an authenticated user, a feature flag. "
                    "FastAPI resolves the dependency graph per request and "
                    "passes the results into your handler as keyword arguments.\n\n"
                    "Lumen uses this for `DBSession` (yields an AsyncSession), "
                    "`CurrentUser` (decodes the JWT), and the role guards "
                    "(`RequireInstructor`, `RequireAdmin`)."
                ),
            },
        ],
    },
    {
        "title": "Persistence with SQLAlchemy 2 async",
        "description": "AsyncSession, query patterns, and the unit-of-work mindset.",
        "lessons": [
            {
                "title": "AsyncSession 101",
                "type": LessonType.text,
                "data": _text(
                    "SQLAlchemy 2's `AsyncSession` is the async cousin of the "
                    "classic `Session`. Every query becomes:\n\n"
                    "```python\nstmt = select(User).where(User.email == email)\n"
                    "result = await db.execute(stmt)\n"
                    "user = result.scalar_one_or_none()\n```\n\n"
                    "The session is a unit of work. Stage changes via "
                    "`db.add(obj)`, `await db.flush()` to push them to the DB "
                    "without committing, and `await db.commit()` to make them "
                    "durable. Forgetting `commit()` is the #1 'why didn't my "
                    "write stick' bug."
                ),
            },
            {
                "title": "Avoiding N+1",
                "type": LessonType.text,
                "data": _text(
                    "Lazy loading + async don't mix: an async handler that "
                    "touches a relationship attribute after the request has "
                    "moved on will deadlock the session. Always eager-load "
                    "what you need via `selectinload()` or `joinedload()`.\n\n"
                    "Concretely: if you return a Course with its modules, "
                    "spell it out — `.options(selectinload(Course.modules))` — "
                    "so SQLAlchemy emits one extra SELECT instead of N."
                ),
            },
        ],
    },
]


# --------------------------------------------------------------------- #
# Course construction                                                   #
# --------------------------------------------------------------------- #


async def _build_course(
    db,
    *,
    owner: User,
    subject: Subject,
    tags: list[Tag],
    slug: str,
    title: str,
    overview: str,
    learning_outcomes: list[str],
    difficulty: Difficulty,
    modules_spec: list[dict[str, Any]],
) -> Course:
    """Upsert a published course + its module/lesson tree."""
    res = await db.execute(select(Course).where(Course.slug == slug))
    course = res.scalar_one_or_none()
    if course is not None:
        return course

    course = Course(
        owner_id=owner.id,
        subject_id=subject.id,
        title=title,
        slug=slug,
        overview=overview,
        learning_outcomes=learning_outcomes,
        difficulty=difficulty,
        status=CourseStatus.published,  # noqa: published-check — seed write
        published_at=datetime.now(UTC),
        is_featured=True,
    )
    course.tags = tags
    db.add(course)
    await db.flush()

    for m_idx, mod_spec in enumerate(modules_spec):
        module = Module(
            course_id=course.id,
            title=mod_spec["title"],
            description=mod_spec.get("description", ""),
            order=m_idx,
        )
        db.add(module)
        await db.flush()
        for l_idx, lesson_spec in enumerate(mod_spec["lessons"]):
            lesson = Lesson(
                module_id=module.id,
                title=lesson_spec["title"],
                type=lesson_spec["type"],
                order=l_idx,
                data=lesson_spec["data"],
                # QA-iter2: surface the free-preview feature in the
                # demo. The first lesson of the first module on every
                # seeded course is_preview=True so /courses/[slug]
                # shows the "Try preview" link, /preview/[lessonId]
                # actually renders, and the backend's auth bypass
                # branch (apps/backend/app/api/v1/courses.py
                # get_lesson — `if lesson.is_preview and published`)
                # gets exercised. Pre-iter2 the whole free-preview
                # surface was reachable in code but no seeded lesson
                # was marked preview, so a recruiter clicking through
                # never saw it work. Explicit boolean (not the per-
                # spec override below) so the seed change is grep-able
                # if/when we want to opt more lessons into preview.
                is_preview=(m_idx == 0 and l_idx == 0) or lesson_spec.get("is_preview", False),
            )
            db.add(lesson)
        await db.flush()

    return course


# --------------------------------------------------------------------- #
# Top-level entry point                                                 #
# --------------------------------------------------------------------- #


async def run() -> None:
    """Apply the demo bundle. Idempotent on re-run."""
    Session = get_sessionmaker()
    async with Session() as db:
        # The base seed (app.cli seed) creates these. If the operator
        # ran demo-seed without seeding first, we re-create the
        # subjects + tags + instructor we need so this command can
        # stand on its own.
        programming, _ = await _get_or_create(
            db,
            Subject,
            lookup={"slug": "programming"},
            defaults={"title": "Programming"},
        )
        data_science, _ = await _get_or_create(
            db,
            Subject,
            lookup={"slug": "data-science"},
            defaults={"title": "Data Science"},
        )

        tag_data: list[tuple[str, str]] = [
            ("Beginner", "beginner"),
            ("Python", "python"),
            ("FastAPI", "fastapi"),
            ("Async", "async"),
            ("Data Structures", "data-structures"),
            ("Algorithms", "algorithms"),
            ("TypeScript", "typescript"),
            ("Demo", "demo"),
        ]
        tags: dict[str, Tag] = {}
        for name, slug in tag_data:
            tag, _ = await _get_or_create(db, Tag, lookup={"slug": slug}, defaults={"name": name})
            tags[slug] = tag

        # Reuse the base-seed instructor if it exists, otherwise create
        # a demo-specific one so the seed is self-contained.
        instructor = await _ensure_user(
            db,
            email="teacher@lumen.test",
            full_name="Tareq Hassan",
            password="Teach!2026",
            role=Role.instructor,
        )

        demo_student = await _ensure_user(
            db,
            email="demo@lumen.test",
            full_name="Demo Learner",
            password="Demo!2026",
            role=Role.student,
        )

        intro_python = await _build_course(
            db,
            owner=instructor,
            subject=programming,
            tags=[tags["beginner"], tags["python"], tags["demo"]],
            slug="intro-to-python",
            title="Intro to Python",
            overview=(
                "Hands-on introduction to Python for absolute beginners. "
                "Each lesson ends with a short quiz that unlocks the next, "
                "so you can see your progress without guessing."
            ),
            learning_outcomes=[
                "Write and run small Python scripts from the command line",
                "Use variables, types, and string formatting fluently",
                "Read and predict what an unfamiliar script will do",
                "Earn a course-completion certificate on a real LMS",
            ],
            difficulty=Difficulty.beginner,
            modules_spec=INTRO_PYTHON_MODULES,
        )

        data_structures = await _build_course(
            db,
            owner=instructor,
            subject=data_science,
            tags=[tags["data-structures"], tags["algorithms"], tags["demo"]],
            slug="data-structures-essentials",
            title="Data Structures Essentials",
            overview=(
                "Arrays, hash tables, trees — the data structures every "
                "working engineer reaches for weekly. Content imported via "
                "Lumen's multi-modal ingest pipeline and reviewed by the "
                "instructor."
            ),
            learning_outcomes=[
                "Pick the right structure for a given access pattern",
                "Reason about big-O cost of common operations",
                "Spot when a hash table or BST will degrade to O(n)",
            ],
            difficulty=Difficulty.intermediate,
            modules_spec=DATA_STRUCTURES_MODULES,
        )

        # L20.5 — TypeScript Generics & Variance course. Designed to be
        # the live demo target for the canonical "Type 'string' is not
        # assignable to type 'T'" question. Authored in its own module
        # so the lesson content stays out of this file's plumbing.
        from app.seeds.ts_variance_demo import apply as apply_ts_variance

        ts_variance = await apply_ts_variance(
            db,
            instructor=instructor,
            programming=programming,
            tags=tags,
        )

        # L20.6 — Building a RAG system from scratch. Self-referential
        # course: the tutor cites these lessons when a learner asks
        # "how does this system work?". Same factoring as the TS
        # variance course — its own module file.
        from app.seeds.rag_from_scratch_demo import apply as apply_rag_from_scratch

        rag_from_scratch = await apply_rag_from_scratch(
            db,
            instructor=instructor,
            programming=programming,
            tags=tags,
        )

        await _build_course(
            db,
            owner=instructor,
            subject=programming,
            tags=[tags["python"], tags["fastapi"], tags["async"], tags["demo"]],
            slug="async-web-apps-fastapi",
            title="Async Web Apps in FastAPI",
            overview=(
                "Build a production-shaped async web service end-to-end. "
                "Designed to pair with Lumen's AI tutor — ask the tutor any "
                "question about async, dependency injection, or SQLAlchemy "
                "and watch it cite back to specific lessons."
            ),
            learning_outcomes=[
                "Reason about async vs threads vs processes",
                "Compose FastAPI dependencies for auth + DB + flags",
                "Avoid the N+1 trap with SQLAlchemy 2 async",
                "Ship a FastAPI app you'd actually want to operate",
            ],
            difficulty=Difficulty.intermediate,
            modules_spec=ASYNC_FASTAPI_MODULES,
        )

        # Enrol the demo learner into the Data Structures course with
        # progress already in flight — finish all lessons in the first
        # module so the dashboard surface isn't empty on the live demo.
        existing_enrol = await db.execute(
            select(Enrollment).where(
                Enrollment.user_id == demo_student.id,
                Enrollment.course_id == data_structures.id,
            )
        )
        enrolment = existing_enrol.scalar_one_or_none()
        if enrolment is None:
            enrolment = Enrollment(user_id=demo_student.id, course_id=data_structures.id)
            db.add(enrolment)
            await db.flush()

            # Mark every lesson in the first module complete so the
            # progress bar shows ~33% on a 3-module course.
            #
            # Explicit selects (instead of lazy-loading via
            # `data_structures.modules`) — SQLAlchemy 2 async sessions
            # raise MissingGreenlet on relationship traversal that
            # wasn't pre-loaded. Two cheap queries beat
            # selectinload-rebuilds of the entire course tree.
            first_module_res = await db.execute(
                select(Module)
                .where(Module.course_id == data_structures.id)
                .order_by(Module.order)
                .limit(1)
            )
            first_module = first_module_res.scalar_one()
            first_lessons_res = await db.execute(
                select(Lesson).where(Lesson.module_id == first_module.id).order_by(Lesson.order)
            )
            for lesson in first_lessons_res.scalars().all():
                db.add(
                    LessonProgress(
                        enrollment_id=enrolment.id,
                        lesson_id=lesson.id,
                        completed_at=datetime.now(UTC) - timedelta(hours=2),
                        score=100 if lesson.type == LessonType.quiz else None,
                    )
                )

        # Also drop a no-progress enrolment on Intro to Python so the
        # dashboard's "in progress" list has variety.
        existing_intro = await db.execute(
            select(Enrollment).where(
                Enrollment.user_id == demo_student.id,
                Enrollment.course_id == intro_python.id,
            )
        )
        if existing_intro.scalar_one_or_none() is None:
            db.add(Enrollment(user_id=demo_student.id, course_id=intro_python.id))

        # Also enrol the demo learner in the TS Generics/Variance course
        # so the /demo deep-link redirect (added in L20.5) lands on a
        # fully-enrolled state and doesn't bounce back to the catalog.
        existing_ts = await db.execute(
            select(Enrollment).where(
                Enrollment.user_id == demo_student.id,
                Enrollment.course_id == ts_variance.id,
            )
        )
        if existing_ts.scalar_one_or_none() is None:
            db.add(Enrollment(user_id=demo_student.id, course_id=ts_variance.id))

        # And in the RAG-from-scratch course (L20.6) so the tutor can
        # ground "how does this RAG work?" answers in the demo learner's
        # own enrollment without bouncing to the course-detail page.
        existing_rag = await db.execute(
            select(Enrollment).where(
                Enrollment.user_id == demo_student.id,
                Enrollment.course_id == rag_from_scratch.id,
            )
        )
        if existing_rag.scalar_one_or_none() is None:
            db.add(Enrollment(user_id=demo_student.id, course_id=rag_from_scratch.id))

        await db.commit()

    console.print("[green]Demo seed applied[/green]")
    console.print("  • intro-to-python                 (3 demo lessons, every lesson has a quiz)")
    console.print("  • data-structures-essentials      (simulated multi-modal ingest)")
    console.print("  • async-web-apps-fastapi          (AI-tutor demo target)")
    console.print(f"  • {ts_variance.slug:32s} (L20.5 demo target — canonical TS error)")
    console.print(
        f"  • {rag_from_scratch.slug:32s} (L20.6 self-referential — 'how does this work?')"
    )
    console.print("  • demo@lumen.test / Demo!2026     (in-flight progress on Data Structures)")


def main() -> None:  # pragma: no cover — thin wrapper, exercised via CLI
    asyncio.run(run())


if __name__ == "__main__":  # pragma: no cover
    main()
