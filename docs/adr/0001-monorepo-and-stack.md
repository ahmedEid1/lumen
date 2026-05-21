# ADR-0001: Monorepo with FastAPI backend and Next.js frontend

- **Status:** Accepted
- **Date:** 2026-05-21
- **Deciders:** @ahmedEid1

## Context

The legacy `E-Learning-Platform` was a monolithic Django app rendering server-side templates. We are rewriting it as a 2026-era app. We need:

- A modern, typed backend with async I/O for WebSockets and uploads.
- A modern frontend with SSR/RSC for SEO of the public catalog and a great authoring UX.
- A single repository so issues, ADRs, and tests stay in one place.
- A path for separate deployment cadences without splitting the repo.

## Decision

- **Backend:** Python 3.13 + FastAPI + async SQLAlchemy 2 + Pydantic v2 + Alembic + Celery.
- **Frontend:** Next.js 15 (App Router, RSC) + React 19 + TypeScript 5 + TailwindCSS 4 + shadcn/ui + TanStack Query.
- **Layout:** Monorepo with `apps/backend` and `apps/frontend`.

## Alternatives considered

- **Stay on Django + DRF + HTMX** — preserves prior code but doesn't give us the typed, RSC-friendly frontend we want; chat code path is also more painful in pure Django.
- **Node-only (NestJS + Next.js)** — uniform language but the original tests, data shapes, and team knowledge are Python-centric, and FastAPI's OpenAPI ergonomics + Pydantic v2 are stronger for the API style we want.
- **Two repos** — adds CI/PR/issue overhead; we lose atomic cross-cutting changes (e.g. evolving the API contract together with the FE consumer).

## Consequences

- Two language toolchains in CI (Python + Node). We mitigate with a single Compose stack and clear `Makefile`.
- One CODEOWNERS file lets us route reviews per-app.
- The generated OpenAPI is consumed by an auto-generated TS client; contracts evolve together.

## References

- [Vercel Monorepos](https://vercel.com/docs/monorepos)
- [FastAPI design rationale](https://fastapi.tiangolo.com/features/)
