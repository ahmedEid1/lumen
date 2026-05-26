# Lumen UI redesign — status log

A one-line-per-loop ledger. Each loop appends; nothing else writes here.

The full retrospective for any loop lives in `loop-{N}-result.md`. This file
exists so a glance from a cold start tells you what has shipped and what's
queued.

| Loop | Surface | Outcome | Commit |
|------|---------|---------|--------|
| 1 | Foundation A — token scale (info / space / z / opacity / motion) + duration-literal sweep | Shipped. 34 vitest files / 160 tests green. No visible diff. | `2049ec8` |
| 2 | Foundation B — Playwright visual-regression baseline (public routes only) | Shipped. 8/8 baselines stable (12.1s re-run). Auth-gated 8 deferred to Loop 3 (login hydration race in dev-mode docker). | `c72bcc7` |
| 3 | Foundation C — Skeleton/EmptyState/Alert/Field/Spinner/LinkButton + useHydrated | Shipped 7 primitives + hook + 247-LoC test spec. 35 files / 185 tests green. VR 8/8 stable, no visible diff. Application deferred to Loop 4. | `ccf7336` |
| 4 | Foundation D — AuthCard + 7-surface migration + LinkButton disabled fix (Codex rescue #1) | Shipped. 36 files / 194 tests green. Public VR 8/8 byte-stable (AuthCard preserved chrome). Auth-gated VR deferred AGAIN — second race in auth context propagation, fix is Playwright `storageState` (own loop). | _pending_ |





