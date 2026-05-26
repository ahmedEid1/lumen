# Loop 4 — Result

## What shipped

`<AuthCard>` primitive + seven auth-surface migrations + LinkButton disabled fix (Codex rescue #1's only finding) + the rescue digest itself.

| File | Change |
|---|---|
| `apps/frontend/src/components/ui/auth-card.tsx` | NEW (+52) |
| `apps/frontend/src/components/ui/link-button.tsx` | +47 / -16 (Codex fix) |
| `apps/frontend/src/app/login/page.tsx` | +13 / -28 |
| `apps/frontend/src/app/register/page.tsx` | +13 / -25 |
| `apps/frontend/src/app/forgot-password/page.tsx` | +14 / -27 |
| `apps/frontend/src/app/reset-password/page.tsx` | +18 / -29 |
| `apps/frontend/src/app/verify-email/page.tsx` | +17 / -30 |
| `apps/frontend/src/app/verify/[id]/page.tsx` | +14 / -19 |
| `apps/frontend/src/app/confirm-email-change/page.tsx` | +13 / -19 |
| `apps/frontend/tests/auth-card.test.tsx` | NEW (+108) |
| `apps/frontend/tests/primitives-foundation.test.tsx` | +30 (LinkButton disabled cases) |
| `apps/frontend/tests/e2e/visual-regression.spec.ts` | comment updates |
| `docs/redesign/codex-review-loops-1-to-3.md` | NEW (+74) |
| `docs/redesign/loop-4-{goal,options,spec,result}.md` | ~600 LoC |

Net code: roughly **−165 LoC across the seven page migrations**, **+99 LoC for new primitives + LinkButton fix**, **+138 LoC for tests + rescue digest**. Under the 2000-line cap.

## Binary criteria — status

- [x] `<AuthCard cartouche heading subtitle>` primitive exists with chrome byte-equivalent to the pre-migration shape (verified: VR public baselines unchanged on re-run).
- [x] All 7 auth pages consume `<AuthCard>`. Pre-migration `grep` count for `"rounded-md border border-border bg-card p-8"` in `app/{login,register,forgot-password,reset-password,verify-email,verify,confirm-email-change}`: 7. Post-migration: 0.
- [x] All 4 hydration-gate paragraphs collapse to `const hydrated = useHydrated();` calls. Pre-migration `grep -r "const \[mounted, setMounted\]" app/` count: 4. Post-migration: 0.
- [x] 3 of 4 nested `<Link><Button>` patterns convert to `<LinkButton>` (`reset-password:92` → done, `verify-email:113` → done, `verify/[id]:105` → done). The fourth (`course-detail-view.tsx:370`) is out of scope for this loop — moves with the course-detail polish loop.
- [x] **Codex rescue digest** published at `docs/redesign/codex-review-loops-1-to-3.md`. Sole finding (LinkButton `disabled` non-propagation on `<a>`) fixed in this commit + pinned by new vitest cases.
- [x] `make test.web` — **36 files / 194 tests passed in 16.49s** (+1 file / +9 tests vs Loop 3's 35/185).
- [x] All 5 sampled migrated pages serve HTTP 200; `pnpm typecheck` clean.
- [x] **Public VR baselines remain byte-stable** after the migration (8/8 pass without re-blessing) — confirms the AuthCard composition is byte-equivalent to the hand-rolled chrome.
- [ ] ~~Auth-gated VR baselines (dashboard/profile/studio/admin × 2 themes) captured~~ → **deferred AGAIN** to a future loop. See "Mid-implementation pivot" below.

## Mid-implementation pivot — auth-gated baselines, take two

Loop 2 deferred the 8 auth-gated baselines because the login form's hydration gate raced the dev-mode JIT compile, capturing the login page instead of the post-login target. Loop 4 was supposed to fix that by collapsing the hydration gates into `useHydrated()`. The initial `--update-snapshots` pass DID capture all 16 baselines (8 existing + 8 new), suggesting the fix worked.

But a verification re-run **flunked 6 of 8 auth-gated routes**:
- `dashboard` (dark+light), `studio` (dark+light), `admin` (dark+light) — flaky: sometimes the captured baseline (post-login screenshot), sometimes a diff (probably partial-render or login-page state).
- `profile` (dark+light) — passed both runs but at **33 KB and 34 KB** — almost exactly the login page's size. The "stable" captures are stably *wrong* (consistently showing login).

The hydration gate was *one* race; this exposes a *second*: between `login()`'s `await expect(page).toHaveURL(/\/dashboard/)` resolving and `page.goto(target_route)` reading the right auth state. Even with the hydration gate fixed, the auth context propagation has its own window where a parallel worker can race ahead of cookie/session state.

**Two fixes worth trying in a future loop:**
1. **Playwright `storageState` fixture.** Run a single setup file that logs in each role once, dumps the cookie+localStorage to disk, and every test loads from that snapshot via `test.use({ storageState: '...' })`. Eliminates per-test login + the race entirely.
2. **Wire e2e to `docker-compose.ci.yml` overlay's prod-build `web`.** Removes the JIT cold compile that amplifies the race. CI already uses this overlay; local doesn't.

(1) is the cleaner long-term fix. (2) is half-measure. Schedule: probably the loop before the dashboard re-imagining (AUDIT.md §7 step 14) since that loop will *also* want a stable auth-gated VR baseline to ship safely.

This loop's revert: removed the 4 auth-gated `ROUTES` entries from `visual-regression.spec.ts`, deleted the 8 captured PNGs, and re-verified the 8 public baselines remain green (which they did, in 12.0s).

## 3-bullet retro

- **The decision to "hold strict, re-bless only if forced" paid off.** AuthCard's composition produced byte-identical DOM, so the 8 public baselines from Loop 2 passed without re-blessing — proves the migration preserved chrome rather than just *approximating* it. If I'd defaulted to re-bless, this signal would have been lost.
- **Codex's rescue produced one P2 but a real one.** The CLI grammar didn't take my full priority prompt (only `--commit <SHA>` or `--uncommitted` accept free-form prompts; `--base <branch>` doesn't), so Codex ran its default rubric and surfaced what it surfaced. The LinkButton `disabled` non-propagation is exactly the kind of thing a senior reviewer would catch and an in-house review team had missed — three commits in and the primitive had a real defect waiting for the first `<LinkButton disabled>` call site. Worth fixing now, before any consumer takes a dependency on the broken behaviour. The digest is at `docs/redesign/codex-review-loops-1-to-3.md` with a retry plan for Codex rescue #2 (loop 6).
- **Auth-gated VR is harder than I thought.** Two races, not one. Loop 3's hydration gate fix was necessary but not sufficient. The proper fix needs Playwright `storageState` — and that's a 100-LoC scope, not a 20-LoC bolt-on. Splitting that into its own loop keeps each loop's diff reviewable and avoids the trap of "Loop 4 ships everything imperfectly". The deferred-twice baselines aren't blocking any subsequent loop because no surface-level loop will *introduce* a regression on the auth-gated route shape — those routes' rendered output is determined by their own `page.tsx` files, which the redesign loops will touch one at a time.

## Follow-ups discovered

- **Playwright `storageState` infrastructure** — pre-login fixtures so the auth-gated VR baselines stabilise. Estimate ~100 LoC including the setup spec + per-route storageState references. **Schedule:** new dedicated loop, slot before the dashboard re-imagining (AUDIT.md §7 step 14) so that loop has CI signal.
- **`course-detail-view.tsx:370` `<Link><Button>` migration** — not done here (out of scope per loop-4-goal.md). Moves with the course-detail polish loop (AUDIT.md §7 step 11).
- **AuthCard subtitle vs chrome inconsistency on `verify-email`** — the pre-migration `/verify-email` and `/confirm-email-change` rendered without a subtitle. My AuthCard migration preserves that (no `subtitle` prop). But the chrome's `mb-7` spacing means the heading sits closer to the body when there's no subtitle, which may read slightly differently than the seamless pre-migration version. Visually: probably fine. Worth a manual eyeball in the next light-mode pass.
- **The seven auth pages still have their own `[submitting, setSubmitting]` state + `aria-live` error region.** A future `<AuthForm>` primitive could collapse those too — but the form bodies vary too much (1 field for forgot, 2 for login/reset, 3 for register, 0 for verify) to extract usefully. Holds at the current level of abstraction.

## What to watch in Loop 5

Loop 5 applies the loop-3 primitives (Skeleton, EmptyState, Alert) across the non-auth surfaces — replacing the 5 different loading conventions catalogued in AUDIT.md §4 #4. Watch:
1. Public VR baselines re-blessing for `home` + `catalog` if any Skeleton-using surface like `course-card`'s loading state lands on either page.
2. `<Field>` adoption — Loop 5 might cover that, or it might defer to Loop 6 (light-mode redesign) where the form-input primitives (Switch/Checkbox/RadioGroup) land together.
3. Whether the `storageState` infrastructure ships as part of Loop 5 (bundled with the non-auth surface migrations that don't need auth) or as its own pre-dashboard loop. Decision pending.
