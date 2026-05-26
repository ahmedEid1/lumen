# Lumen UI redesign — status log

A one-line-per-loop ledger. Each loop appends; nothing else writes here.

The full retrospective for any loop lives in `loop-{N}-result.md`. This file
exists so a glance from a cold start tells you what has shipped and what's
queued.

| Loop | Surface | Outcome | Commit |
|------|---------|---------|--------|
| 1 | Foundation A — token scale (info / space / z / opacity / motion) + duration-literal sweep | Shipped. 34 vitest files / 160 tests green. No visible diff. | `2049ec8` |
| 2 | Foundation B — Playwright visual-regression baseline (public routes only) | Shipped. 8/8 baselines stable (12.1s re-run). Auth-gated 8 deferred to Loop 3 (login hydration race in dev-mode docker). | _pending_ |

