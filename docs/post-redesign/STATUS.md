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
| 20.5 | TS Generics/Variance course + `/demo` deep-link + runtime-flags endpoint + ADRs 17/18/19 | Shipped. 4 modules / 8 lessons + canonical-error lesson seeded; `/demo` redirects to `/learn/typescript-variance?tutor=open&q=…&lesson=canonical-error`; `feature_tutor_streaming` exposed via `GET /api/v1/runtime-flags` (default OFF until L21b); three ADRs draft Celery prefork pool + Redis Streams + atomic phase fence/after-commit enqueue. 52 files / 288 frontend tests green; 4 new backend tests green. | TBD |
