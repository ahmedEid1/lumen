# Lumen — post-redesign status log

One-line-per-loop ledger for the v7 post-redesign roadmap. Each loop
appends; nothing else writes here. The UI redesign's own ledger lives
in `docs/redesign/STATUS.md` (closed at loop 20).

Canonical plan: `~/.claude/projects/-home-ubuntu-projects-E-Learning-Platform/planning/post-redesign-2026-05-26/plan-v7.md`.

Roadmap summary (v7-locked): L19.5 → L20.5 → L20.6 → L21-Sec → L21a →
L21b → L22 → L23 → L24 → L25 → L26 → L27 → **L28 (interview-ready)** →
L29 → L30 → L31 → L32-L37 (cuttable polish) → L38-L40 (audit + rename
+ distribution).

| Loop | Surface | Outcome | Commit |
|------|---------|---------|--------|
| 19.5 | Founding story (README opener) + empty `/blog` index | Shipped. README leads with the locked V6-F6 paragraph; `/blog` renders `EmptyState` until L30 case-study posts arrive. 51 files / 286 tests green (+1 file / +2 tests). i18n keys added in `en` + `ar` (728 keys → 733 each, parity test green). Sitemap updated. | `c5b36a8` |
| 20.5 | TS Generics/Variance course + `/demo` deep-link + runtime-flags endpoint + ADRs 17/18/19 | Shipped. 4 modules / 8 lessons + canonical-error lesson seeded; `/demo` redirects to `/learn/typescript-variance?tutor=open&q=…&lesson=canonical-error`; `feature_tutor_streaming` exposed via `GET /api/v1/runtime-flags` (default OFF until L21b); three ADRs draft Celery prefork pool + Redis Streams + atomic phase fence/after-commit enqueue. 52 files / 288 frontend tests green; 4 new backend tests green. | `5c27373` |
| 20.6 | RAG-from-scratch course (8 lessons, self-referential) + 15-question curated demo library + GET /api/v1/demo-questions + streaming observability tile placeholder | Shipped. Library locks canonical_id=ts-variance-canonical with invariant guards; expected_tools validated against known sub-agents; 5 categories (retriever-only, retriever-code-runner, retriever-web-searcher, refusal, multi-hop). Streaming tab on /admin/observability shows 6 placeholder tiles + ADR cross-refs. 53 files / 289 frontend tests; +10 backend tests (RAG seed + demo-questions library). | `a9e41a5` |
| 21-Sec | Security hardening (no streaming yet) — Llama 3.x special-token sanitizer + Sentry tutor-namespace scrubber + Lua cost-cap + concurrency scripts (microcents, zero FP drift) + code-runner subprocess RLIMIT hardening + email-verify grandfather migration + boot-hook backstop + empty tutor_turn_jobs table with reservation columns + seed-in-prod refusal + IDOR contract tests | Shipped. +43 backend tests, all green. Backend suite 697/697. Alembic 0027 grandfathered users + created tutor_turn_jobs table. All primitives additive; L21a wires the callers. **Codex rescue pass next.** | TBD |
