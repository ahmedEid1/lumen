"""Lumen CLI — admin tasks, seed, reindex."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import typer
from rich.console import Console
from sqlalchemy import select

from app.core.config import Environment, get_settings
from app.core.security import hash_password
from app.db.base import get_sessionmaker
from app.models.course import (
    Course,
    CourseStatus,
    Difficulty,
    Enrollment,
    Lesson,
    LessonType,
    ModerationState,
    Module,
    Subject,
    Tag,
    Visibility,
)
from app.models.user import Role, User

cli = typer.Typer(no_args_is_help=True)
console = Console()


def _refuse_prod_seed_or_pass(command: str) -> None:
    """L21-Sec — refuse to run a destructive/credential-exposing seed
    command against production unless the operator explicitly opts in
    with ``LUMEN_ALLOW_PROD_SEED=1``.

    The demo seed in particular drops a fixed-password demo learner
    (``demo@lumen.test`` / ``Demo!2026``) into the database. Running
    that against prod is the kind of operator mistake that turns
    "weekend deploy" into "Hacker News headline." A 2-line guard is
    much cheaper than the incident.

    The override env var is intentional, named, and undocumented in
    the public README — the only people who'd know to set it are
    operators reading this very source code.
    """
    s = get_settings()
    if s.env != Environment.production:
        return
    if os.environ.get("LUMEN_ALLOW_PROD_SEED") == "1":
        console.print(
            f"[yellow]WARNING: {command} is running against PRODUCTION because "
            "LUMEN_ALLOW_PROD_SEED=1 is set. Demo credentials will be inserted.[/yellow]"
        )
        return
    console.print(
        f"[red]{command} refuses to run against production by default.[/red]\n"
        "If you really mean it, re-run with LUMEN_ALLOW_PROD_SEED=1.\n"
        "If you did NOT mean to seed production — congratulations, you just "
        "avoided shipping a fixed-password demo account to prod."
    )
    raise typer.Exit(code=2)


async def _get_or_create(db, model, *, lookup: dict, defaults: dict):
    """Idempotent upsert by single-column lookup. Used by `seed` so a
    re-run reuses existing rows. Defaults are only constructed when a
    new row is needed; pass a precomputed dict for callers that don't
    care about lazy construction."""
    res = await db.execute(select(model).filter_by(**lookup))
    obj = res.scalar_one_or_none()
    if obj is None:
        obj = model(**lookup, **defaults)
        db.add(obj)
        await db.flush()
    return obj


@cli.command()
def bootstrap_admin(
    email: str = "admin@lumen.test", password: str = "Admin!2026", full_name: str = "Admin"
) -> None:
    """Create or upsert an admin user."""
    asyncio.run(_bootstrap_admin(email, password, full_name))


async def _bootstrap_admin(email: str, password: str, full_name: str) -> None:
    Session = get_sessionmaker()
    async with Session() as db:
        res = await db.execute(select(User).where(User.email == email))
        user = res.scalar_one_or_none()
        if user:
            user.role = Role.admin
            user.is_active = True
            user.full_name = full_name
            msg = f"Updated existing user {email} → admin"
        else:
            db.add(
                User(
                    email=email,
                    password_hash=hash_password(password),
                    full_name=full_name,
                    role=Role.admin,
                )
            )
            msg = f"Created admin {email}"
        await db.commit()
        console.print(f"[green]{msg}[/green]")


@cli.command()
def seed() -> None:
    """Load demo subjects, tags, instructor, student, and a course."""
    _refuse_prod_seed_or_pass("seed")
    asyncio.run(_seed())


async def _seed() -> None:
    Session = get_sessionmaker()
    async with Session() as db:
        subjects = {
            slug: await _get_or_create(
                db, Subject, lookup={"slug": slug}, defaults={"title": title}
            )
            for title, slug in [
                ("Programming", "programming"),
                ("Data Science", "data-science"),
                ("Design", "design"),
                ("Business", "business"),
                ("Mathematics", "mathematics"),
            ]
        }
        tags = {
            slug: await _get_or_create(db, Tag, lookup={"slug": slug}, defaults={"name": name})
            for name, slug in [
                ("Beginner", "beginner"),
                ("Python", "python"),
                ("FastAPI", "fastapi"),
                ("React", "react"),
                ("TypeScript", "typescript"),
                ("Machine Learning", "machine-learning"),
                ("Algorithms", "algorithms"),
                ("UX", "ux"),
            ]
        }

        # Users — S1.8: the two demo accounts keep their familiar emails but
        # are seeded as the canonical `user` role (both can author + learn;
        # admin is the only elevated role). The persona shim in the frontend
        # e2e / conftest maps teacher@/student@ → user.
        users = {
            "admin@lumen.test": ("Admin", Role.admin, "Admin!2026"),
            "teacher@lumen.test": ("Tareq Hassan", Role.user, "Teach!2026"),
            "student@lumen.test": ("Lina Park", Role.user, "Learn!2026"),
        }
        created = {}
        for email, (full_name, role, password) in users.items():
            res = await db.execute(select(User).where(User.email == email))
            user = res.scalar_one_or_none()
            if not user:
                user = User(
                    email=email,
                    password_hash=hash_password(password),
                    full_name=full_name,
                    role=role,
                )
                db.add(user)
                await db.flush()
            created[email] = user

        instructor = created["teacher@lumen.test"]
        student = created["student@lumen.test"]

        # Course
        existing = await db.execute(select(Course).where(Course.slug == "fastapi-from-zero"))
        course = existing.scalar_one_or_none()
        if not course:
            course = Course(
                owner_id=instructor.id,
                subject_id=subjects["programming"].id,
                title="FastAPI from Zero",
                slug="fastapi-from-zero",
                overview="Learn to build production-ready APIs with FastAPI, SQLAlchemy 2, and async Python.",
                difficulty=Difficulty.beginner,
                cover_url=None,
                status=CourseStatus.published,  # noqa: published-check — seed write
                # Seed the FULL publicly-listed state (R-C1′ /
                # app.services.visibility.is_publicly_listed): a fresh stack has
                # no S2 backfill migration to upgrade legacy rows, so the seed
                # must mirror what moderation.approve_course writes — visibility
                # public + moderation_state approved — or the course is
                # existence-hidden from the anonymous catalog (404).
                visibility=Visibility.public,
                moderation_state=ModerationState.approved,
                published_at=datetime.now(UTC),
                is_featured=True,
            )
            course.tags = [tags["python"], tags["fastapi"], tags["beginner"]]
            db.add(course)
            await db.flush()

            module1 = Module(
                course_id=course.id,
                title="Getting started",
                description="The why and the how.",
                order=0,
            )
            module2 = Module(
                course_id=course.id,
                title="Routing & schemas",
                description="Pydantic + path & query.",
                order=1,
            )
            module3 = Module(
                course_id=course.id, title="Persistence", description="Async SQLAlchemy.", order=2
            )
            db.add_all([module1, module2, module3])
            await db.flush()

            db.add_all(
                [
                    Lesson(
                        module_id=module1.id,
                        title="Welcome",
                        type=LessonType.text,
                        order=0,
                        data={
                            "type": "text",
                            "body_markdown": "Welcome to *FastAPI from Zero*. Let's build something!",
                        },
                    ),
                    Lesson(
                        module_id=module1.id,
                        title="Project layout",
                        type=LessonType.text,
                        order=1,
                        data={
                            "type": "text",
                            "body_markdown": "We'll structure the project with clear seams between layers.",
                        },
                    ),
                    Lesson(
                        module_id=module2.id,
                        title="Path & query params",
                        type=LessonType.text,
                        order=0,
                        data={
                            "type": "text",
                            "body_markdown": "FastAPI infers OpenAPI from your type hints.",
                        },
                    ),
                    Lesson(
                        module_id=module2.id,
                        title="Quick quiz",
                        type=LessonType.quiz,
                        order=1,
                        data={
                            "type": "quiz",
                            "pass_score": 60,
                            "questions": [
                                {
                                    "id": "q1",
                                    "prompt": "Which library provides FastAPI's data validation?",
                                    "kind": "single",
                                    "choices": [
                                        {"id": "a", "text": "marshmallow"},
                                        {"id": "b", "text": "pydantic"},
                                        {"id": "c", "text": "attrs"},
                                    ],
                                    "answer_keys": ["b"],
                                }
                            ],
                        },
                    ),
                    Lesson(
                        module_id=module3.id,
                        title="Async session",
                        type=LessonType.text,
                        order=0,
                        data={
                            "type": "text",
                            "body_markdown": "Use `AsyncSession` and let SQLAlchemy 2 do the heavy lifting.",
                        },
                    ),
                ]
            )
            await db.flush()

            db.add(Enrollment(user_id=student.id, course_id=course.id))

        # ---- Agentic demo enrichments (A5 activation) ----
        # Layered on top of the base seed: extra published courses,
        # a completed enrollment + certificate, a tutor turn with a
        # populated agent_trace, and a course draft with a
        # self-critique trace. Lives in its own module to keep this
        # file a one-screen read. Idempotent on re-run.
        from app.seeds import agentic_demo

        await agentic_demo.apply(
            db,
            subjects=subjects,
            tags=tags,
            instructor=instructor,
            student=student,
        )

        await db.commit()
        console.print("[green]Seeded demo data[/green]")


@cli.command()
def reindex() -> None:
    """Reindex the search backend."""
    from app.workers.tasks.search import _reindex

    asyncio.run(_reindex())


@cli.command(name="demo-seed")
def demo_seed() -> None:
    """Load the demo bundle (3 courses + demo student).
    L21-Sec — refuses in production unless ``LUMEN_ALLOW_PROD_SEED=1``.

    Sits on top of ``seed``: run ``seed`` first if you want the full
    subject / tag / instructor / student dev fixtures; ``demo-seed`` is
    additive and idempotent on its own. See ``app/seeds/demo.py``.
    """
    _refuse_prod_seed_or_pass("demo-seed")
    from app.seeds.demo import run as _demo_run

    asyncio.run(_demo_run())


@cli.command(name="ingest-embeddings")
def ingest_embeddings(
    only_slug: str = typer.Option(None, "--only-slug", help="Restrict to one course slug."),
) -> None:
    """L41-followup — ingest lesson_chunks (pgvector embeddings) for
    all published courses.

    The demo-seed inserts published courses but does NOT run the
    embedding pipeline — the L21-Sec `_schedule_index` Celery hook
    fires on the publish-via-API path only. Demo-seeded courses
    therefore have no lesson_chunks, which means the tutor
    orchestrator's empty-retrieval refusal fires on every question
    against those courses → bad eval scores. This command
    backfills the gap.

    Idempotent — re-running just rewrites existing rows. Safe to
    invoke against prod (no schema change, no destructive ops; the
    embedding API calls cost money proportional to chunk count).
    """
    asyncio.run(_ingest_embeddings(only_slug))


async def _ingest_embeddings(only_slug: str | None) -> None:
    from app.services.embeddings_ingest import ingest_course
    from app.services.visibility import publicly_listed_sql

    Session = get_sessionmaker()
    async with Session() as db:
        # Enumerate only publicly-listed courses (S2.6 / ADR-0026 §3) through
        # the central authorizer rather than the raw status proxy.
        stmt = select(Course).where(publicly_listed_sql())
        if only_slug:
            stmt = stmt.where(Course.slug == only_slug)
        courses = (await db.execute(stmt)).scalars().all()
        if not courses:
            console.print("[yellow]No published courses to ingest.[/yellow]")
            return
        for course in courses:
            try:
                written = await ingest_course(db, course.id)
                await db.commit()
                console.print(f"[green]ingested[/green] {course.slug:30s} → {written} chunks")
            except Exception as exc:
                await db.rollback()
                console.print(
                    f"[red]FAILED[/red]    {course.slug:30s} → {type(exc).__name__}: {exc}"
                )


@cli.command(name="promote-eval")
def promote_eval(
    suite: str = typer.Option(
        ..., "--suite", help="Eval suite to promote (e.g. tutor, authoring, ingest)."
    ),
    report: str = typer.Option(
        ..., "--report", help="Report id to surface on public /eval (e.g. tutor-20260527-101530)."
    ),
    clear: bool = typer.Option(
        False, "--clear", help="Un-promote the suite instead of setting a new report."
    ),
) -> None:
    """L41 — Promote (or un-promote) an eval report to the public surface.

    Updates ``apps/backend/evals/reports/PROMOTED.json``. The
    public ``GET /api/v1/eval/public`` endpoint reads this file
    and falls back to honest-empty for any suite not in it.

    Examples::

        python -m app.cli promote-eval --suite tutor --report tutor-20260527-101530
        python -m app.cli promote-eval --suite tutor --clear

    Safe to run against production (read+write of one file; no
    LLM cost; no DB write) — does NOT call ``_refuse_prod_seed_or_pass``.
    """
    from app.api.v1.eval_public import clear_promoted, set_promoted

    if clear:
        clear_promoted(suite)
        console.print(
            f"[yellow]Un-promoted suite={suite}; public /eval reverts to honest-empty for it.[/yellow]"
        )
        return
    set_promoted(suite, report)
    console.print(
        f"[green]Promoted report={report} for suite={suite}.[/green] "
        "Public /eval endpoint surfaces the summary on next request."
    )


@cli.command(name="mcp-token")
def mcp_token(
    owner_email: str = typer.Option(
        ...,
        "--owner-email",
        "-o",
        help="Email of the Lumen user the MCP token will act as.",
    ),
    name: str = typer.Option(
        "Local MCP client",
        "--name",
        "-n",
        help="Human-readable label for the registration (shown in /admin/mcp-clients).",
    ),
    scopes: str = typer.Option(
        "*",
        "--scopes",
        "-s",
        help=(
            "Comma-separated list of MCP tool names the token may invoke,"
            " or '*' for unrestricted. Default: '*'."
        ),
    ),
) -> None:
    """Mint a new MCP OAuth client + print its secret once.

    The secret is shown **only** on this CLI run — once you close
    the terminal, you can't recover it (we store only an argon2
    hash). If you lose it, mint a new one and revoke the old via
    ``DELETE /api/v1/admin/mcp-clients/{id}``.

    Example
    -------

    .. code-block:: shell

       $ python -m app.cli mcp-token --owner-email teacher@lumen.test
       client_id=abc123…
       client_secret=def456…   # paste into Claude Desktop's LUMEN_MCP_AUTH_TOKEN
       scopes=*
    """
    asyncio.run(_mcp_token(owner_email=owner_email, name=name, scopes=scopes))


async def _mcp_token(*, owner_email: str, name: str, scopes: str) -> None:
    from app.core.ids import new_id
    from app.core.security import hash_password
    from app.models.mcp_client import WILDCARD_SCOPE, MCPClient

    scope_list = [s.strip() for s in scopes.split(",") if s.strip()]
    if not scope_list:
        scope_list = [WILDCARD_SCOPE]

    Session = get_sessionmaker()
    async with Session() as db:
        res = await db.execute(select(User).where(User.email == owner_email))
        owner = res.scalar_one_or_none()
        if owner is None or not owner.is_active:
            console.print(f"[red]Owner not found or inactive: {owner_email}[/red]")
            raise typer.Exit(code=1)

        plaintext_secret = new_id()
        row = MCPClient(
            client_secret_hash=hash_password(plaintext_secret),
            owner_user_id=owner.id,
            name=name,
            scopes=scope_list,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)

        # Plain ``print`` (not ``console.print``) so the values land
        # on stdout without ANSI escape codes — the typical usage is
        # ``eval $(python -m app.cli mcp-token ...)`` or piping into
        # a secrets manager. ``app/cli.py`` already has the T20
        # (no-print) rule disabled in pyproject.toml's per-file-ignores
        # so no per-line noqa is needed.
        print(f"client_id={row.id}")
        print(f"client_secret={plaintext_secret}")
        print(f"owner_user_id={row.owner_user_id}")
        print(f"name={row.name}")
        print(f"scopes={','.join(row.scopes)}")
        console.print("\n[yellow]Save the client_secret now — it will not be shown again.[/yellow]")


@cli.command(name="rotate-byok-master-key")
def rotate_byok_master_key() -> None:
    """Re-wrap every BYOK credential's DEK under the active KEK version.

    S5.14 / FR-BYOK-12 / R-S2. Envelope rotation: only the wrapped DEK
    (``enc_data_key``) is re-wrapped under the new active KEK; the encrypted
    plaintext (``enc_key``) is preserved byte-for-byte — the plaintext key is
    never touched, logged, or surfaced. Emits ``byok.master_key_rotated``
    (counts only).

    Precondition (R-S2): deploy the NEW KEK version to EVERY API + worker
    process FIRST and bump ``BYOK_MASTER_KEY_VERSION``, keeping the OLD
    version present in ``BYOK_MASTER_KEYS`` until this command finishes — a
    credential resolved under the old version mid-rotation must still decrypt.
    See docs/runbooks/byok-key-rotation.md.
    """
    from app.services.llm_credentials import rotate_master_key

    async def _run() -> None:
        async with get_sessionmaker()() as db:
            rotated, skipped = await rotate_master_key(db)
            console.print(
                f"[green]BYOK master-key rotation complete.[/green] "
                f"rotated={rotated} skipped(already-current)={skipped} "
                f"to_version={get_settings().byok_master_key_version}"
            )

    asyncio.run(_run())


# The exact fixture template Playwright registers in
# apps/frontend/tests/e2e/auth.spec.ts:
#   const email = `e2e-auth-${Date.now()}@lumen.test`;  full_name "E2E Auth User"
# A LIKE on this prefix (anchored to the @lumen.test domain so a real user who
# happens to start their address with "e2e-auth-" on another domain is never
# swept) is the pin. ``%`` matches the epoch-ms stamp. Keep this in lock-step
# with the spec — if the fixture template ever changes, this pattern must too.
_E2E_USER_EMAIL_LIKE = "e2e-auth-%@lumen.test"


@cli.command(name="prune-e2e-users")
def prune_e2e_users(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="List what WOULD be pruned without deleting anything.",
    ),
) -> None:
    """Hard-delete throwaway Playwright auth-fixture users + their owned data.

    The e2e auth golden-path spec registers a fresh
    ``e2e-auth-<epoch>@lumen.test`` user on every run (see
    ``apps/frontend/tests/e2e/auth.spec.ts``). Those accounts accumulate in
    the dev DB and clutter ``/admin/users``. This is a data-hygiene sweep —
    it HARD-deletes the matching users and every row they own, in FK-safe
    order:

    1. Their owned courses are deleted FIRST. ``courses.owner_id`` is an
       ``ondelete="RESTRICT"`` FK (ADR-0030 D1), so a user who owns a course
       can't be removed until the course is gone. Deleting the course lets
       Postgres CASCADE tear down its whole subtree (modules → lessons →
       chunks, enrollments, reviews, discussions, tutor conversations,
       learning-path items, moderation rows, …) and SET NULL the clone-
       provenance self-pointers on any descendant courses.
    2. The users are deleted SECOND. Postgres then CASCADEs the remaining
       user-owned rows (refresh tokens, enrollments in other courses,
       notifications, MCP clients, BYOK credentials, learning briefs/paths,
       tutor jobs, …) and SET NULLs the audit / authored-by columns that are
       deliberately ``ondelete="SET NULL"``.

    L21-Sec — refuses in production unless ``LUMEN_ALLOW_PROD_SEED=1``
    (the same operator opt-in the seed commands use). Prints a count summary
    of users + courses pruned. ``--dry-run`` lists what WOULD go and deletes
    nothing.
    """
    _refuse_prod_seed_or_pass("prune-e2e-users")
    asyncio.run(_prune_e2e_users(dry_run=dry_run))


async def _prune_e2e_users(*, dry_run: bool) -> None:
    Session = get_sessionmaker()
    async with Session() as db:
        users = (
            (await db.execute(select(User).where(User.email.like(_E2E_USER_EMAIL_LIKE))))
            .scalars()
            .all()
        )
        if not users:
            console.print("[yellow]No e2e fixture users found — nothing to prune.[/yellow]")
            return

        user_ids = [u.id for u in users]
        # Include soft-deleted courses too: a hygiene sweep must leave NO trace
        # of the fixture account, and a soft-deleted row still pins owner_id
        # under the RESTRICT FK.
        courses = (
            (await db.execute(select(Course).where(Course.owner_id.in_(user_ids)))).scalars().all()
        )
        course_ids = [c.id for c in courses]

        if dry_run:
            console.print(
                f"[cyan]DRY RUN — would prune {len(users)} user(s) "
                f"and {len(courses)} owned course(s):[/cyan]"
            )
            for u in users:
                console.print(f"  user  {u.email:40s} ({u.id})")
            for c in courses:
                console.print(f"  course {c.slug:39s} ({c.id})")
            return

        # FK-safe order: courses first (owner_id is RESTRICT), then users.
        # Use ORM ``session.delete`` so SQLAlchemy issues per-row DELETEs the
        # DB-level ``ondelete`` rules act on (CASCADE children, SET NULL
        # provenance / audit pointers).
        for c in courses:
            await db.delete(c)
        await db.flush()
        for u in users:
            await db.delete(u)
        await db.commit()

        console.print(
            f"[green]Pruned {len(user_ids)} e2e fixture user(s) "
            f"and {len(course_ids)} owned course(s).[/green]"
        )


@cli.command()
def info() -> None:
    """Print configuration summary."""
    s = get_settings()
    console.print(
        {
            "env": s.env,
            "api": str(s.api_base_url),
            "db": s.database_url,
            "redis": s.redis_url,
            "search": "postgres-tsvector",
            "s3": s.s3_endpoint_url,
            "llm_provider": s.llm_provider,
            "embedding_provider": s.embedding_provider,
        }
    )


if __name__ == "__main__":  # pragma: no cover
    cli()
