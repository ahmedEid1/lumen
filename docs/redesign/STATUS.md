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
| 4 | Foundation D — AuthCard + 7-surface migration + LinkButton disabled fix (Codex rescue #1) | Shipped. 36 files / 194 tests green. Public VR 8/8 byte-stable (AuthCard preserved chrome). Auth-gated VR deferred AGAIN — second race in auth context propagation, fix is Playwright `storageState` (own loop). | `00ea6ab` |
| 5 | First application sweep — token cleanup (ScoreBadge + LLMTracesTab raw hues) + course-card i18n leak fix + studio loading/empty → Skeleton/EmptyState | Shipped. 36 files / 194 tests green. Public VR 8/8 byte-stable (resolved i18n matches pre-migration English). | `c88ad15` |
| 6 | Playwright `storageState` fixtures + 14 of 16 auth-gated VR baselines | Shipped (reordered ahead of light mode). Setup project + per-role storageState files. 8 public + 6 auth-gated stable. 2 light-mode auth-gated (dashboard-light + admin-light) deferred to Loop 7's light-mode redesign re-bless. | `3cae978` |
| 7 | Light mode redesign — token-layer + Codex rescue #2 (Sonner pin-off rolled back) | Shipped token layer (`.light` surface ramp redesign + sonner CSS overrides). Pin-off attempt cascaded into VR flake (sonner-vs-next-themes hydration race) — pin restored, override block ships dormant. Codex #2 caught 2 bad baselines; both addressed. studio-light joins the deferral list (3 light auth-gated deferred). | `0bfa333` |
| 8 | e2e infrastructure — API-based login in auth.setup.ts | Shipped. ~60 LoC. All 16 visual-regression baselines now capture stably (19/19 first try, 45.1s). 3 deferred light auth-gated baselines (dashboard-light, admin-light, studio-light) finally land. Residual verification flake unrelated to auth; CI retries=2 covers. | `094c71f` |
| 9 | `<RadioGroup>` + `<Checkbox>` primitives + quiz radiogroup a11y migration | Shipped. 37 files / 202 tests green (+1 file / +8 tests). Closes AUDIT.md §3 Block-renderer's heaviest a11y finding — quiz options now have role/aria-checked, arrow-key nav, fieldset/legend. | `45f1511` |
| 7-followup | HOTFIX: revert `--spacing-*` aliases (Tailwind 4 `max-w-*` collision) | Shipped. `max-w-3xl` was resolving to 96px instead of 48rem since Loop 1, breaking every page that constrains content with `max-w-xl/2xl/3xl`. Caught by visual review of the prod deploy. 37 files / 202 tests still green. | `f04efc1` |
| 10 | Foundation C slice 1 — Dialog + Sheet primitives + tutor-modal migration | Shipped. 38 files / 216 tests green (+1 file / +14 tests). Tutor modal on `/courses/[slug]` now has Radix focus trap, aria-labelledby, Escape, click-outside, focus restore. Sheet primitive lands with 4-side `data-side` variant ready for Loop 11 mobile menu. | `2b16a53` |
| 11 | Foundation C slice 2 — Popover + DropdownMenu + 3 overlay migrations | Shipped. 40 files / 228 tests green (+2 files / +12 tests). Notifications-bell → Popover; locale-switcher promoted from cycle-button to DropdownMenu with radio-group selection; mobile menu → Sheet (Sheet finally has a consumer). All four hand-rolled overlays inside the shared chrome retired. | `42955c0` |
| 12 | Foundation C slice 3 — Tooltip + 4 modal migrations + Codex rescue #3 | Shipped (via 3-commit chain: `d395cd5` + `230677e` rescue + `c771b43` a11y test fix). 41 files / 232 tests green. Tooltip primitive lands w/ theme-toggle as first consumer. ai-outline-modal, ingest-modal, onboarding-tour, profile-delete-confirm all migrated from hand-rolled `fixed inset-0` to `<Dialog>`. Codex caught 2 P2 regressions (ingest scroll, sheet stay-open on logout) — both fixed in-loop. a11y test broke because Radix Dialog correctly sets `aria-hidden` on siblings; signIn helper now pre-dismisses onboarding tour. **Closes out Foundation C** — every overlay surface in the audit now uses a Radix primitive. | `c771b43` |














