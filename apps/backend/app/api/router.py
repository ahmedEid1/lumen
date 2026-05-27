"""Versioned root router."""

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    admin_evals,
    admin_llm_calls,
    admin_mcp_clients,
    admin_observability,
    admin_rate_limit_stats,
    ai_authoring,
    auth,
    badges,
    catalog,
    certificates,
    content_ingest,
    courses,
    demo_questions,
    discussions,
    enrollments,
    eval_public,
    health,
    learner_traces,
    learning_path,
    mastery,
    notifications,
    reviews,
    reviews_queue,
    runtime_flags,
    search,
    tutor,
    tutor_streaming,
    uploads,
    users,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(catalog.router, tags=["catalog"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(courses.router, prefix="/courses", tags=["courses"])
api_router.include_router(enrollments.router, prefix="/me", tags=["enrollments"])
api_router.include_router(reviews.router, prefix="/courses", tags=["reviews"])
api_router.include_router(uploads.router, prefix="/uploads", tags=["uploads"])
api_router.include_router(notifications.router, prefix="/me/notifications", tags=["notifications"])
api_router.include_router(reviews_queue.router, prefix="/me/reviews", tags=["reviews-queue"])
# Mastery (Phase E7) — per-learner weak-spot + per-course rollup
# bundle, mounted directly under /me so the path is /me/mastery.
api_router.include_router(mastery.router, prefix="/me", tags=["mastery"])
api_router.include_router(certificates.router, prefix="/certificates", tags=["certificates"])
api_router.include_router(badges.router, prefix="/credentials", tags=["badges"])
api_router.include_router(discussions.router, tags=["discussions"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
# Phase H1 — LLM cost meter: paginated calls + 14-day rollup
# under /api/v1/admin/llm-calls{,/summary}.
api_router.include_router(admin_llm_calls.router, prefix="/admin", tags=["admin-llm-calls"])
# Phase H2 — Eval harness: suites + reports + run-trigger
# under /api/v1/admin/evals/*.
api_router.include_router(admin_evals.router, prefix="/admin", tags=["admin-evals"])
api_router.include_router(eval_public.router, tags=["public-eval"])
# Phase H6 — Rate-limit metrics (read-only) under
# /api/v1/admin/rate-limit-stats, sourced from the in-memory
# 429 ring buffer in app.core.rate_limit_metrics.
api_router.include_router(admin_rate_limit_stats.router, prefix="/admin", tags=["admin-rate-limit"])
# Phase H7 — AI-trace observability under /api/v1/admin/observability/*.
# Three surfaces: per-call agent-trace + retrieval audit drill-down,
# recent retrieval-quality list, and Celery queue/health snapshot.
api_router.include_router(admin_observability.router, prefix="/admin", tags=["admin-observability"])
# Phase I1 — MCP client CRUD (admin-only): create + list + revoke
# the OAuth client-credential rows that the Lumen MCP server checks
# tokens against. Mounted under /api/v1/admin/mcp-clients.
api_router.include_router(admin_mcp_clients.router, prefix="/admin", tags=["admin-mcp-clients"])
# Phase I5 — Personalized learning-path agent. Endpoints live under
# /api/v1/me/learning-path{,/today,/steps/{id}/complete,/replan}.
api_router.include_router(learning_path.router, prefix="/me", tags=["learning-path"])
# Phase I4 — Learner-facing agent-trace surface. Two read-only
# routes the learner / instructor uses to drill into a tutor turn
# or replay a course draft. Paths in the module already carry
# /me/, so no extra prefix here.
api_router.include_router(learner_traces.router, tags=["learner-traces"])
# Content ingest (Phase E3) — paste a URL, get a draft course.
api_router.include_router(content_ingest.router, prefix="/studio/ingest", tags=["studio-ingest"])
# Tutor (Phase E1) — mounts both course-scoped routes
# (``/courses/{id}/tutor/conversations``) and conversation-scoped
# routes (``/tutor/conversations/{id}``) so we let the router root
# inherit the ``/api/v1`` prefix and the module file declares its
# own paths.
api_router.include_router(tutor.router, tags=["tutor"])
# L21a — streaming tutor endpoints (POST /tutor/turns, status, stream,
# cancel). All four gated on settings.feature_tutor_streaming; return
# 503 tutor.streaming_disabled until L21b's flag-flip.
api_router.include_router(tutor_streaming.router, tags=["tutor-streaming"])
# AI-assisted authoring (Phase E2) — outline + lesson body + quiz
# generation. All four endpoints share the ``/studio/ai`` prefix and
# the per-user 5/minute rate limit declared inside the module.
api_router.include_router(ai_authoring.router, prefix="/studio", tags=["studio-ai"])
# L20.5 — Public runtime-flags read endpoint. Anon-readable so the
# frontend can probe before sign-in. Currently reads from Settings;
# L21-Sec adds a Redis-backed override layer for live flag-flips.
api_router.include_router(runtime_flags.router, tags=["runtime-flags"])
# L20.6 — Curated demo-question library. Anon-readable; consumed by
# the L22 chip rail above the tutor composer + the L25 eval suite.
api_router.include_router(demo_questions.router, tags=["demo-questions"])
