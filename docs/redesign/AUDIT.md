# Lumen UI redesign — initial audit

Date: 2026-05-26
Branch: `main` @ c3450a8 (CI green, prod healthy at https://lumen.ahmedhobeishy.tech)
Method: 4 parallel sub-agents read every primary route + key components fully; this file synthesizes their reports. Original audit transcripts are in the conversation history.

## TL;DR — what the redesign has to do

The Workbench design system (Linear/Raycast density, dark-first, lime accent, no shadows, 8px grid) is **already strong as a foundation**. Tokens are deliberate, contrast is AA across both themes, motion is documented, and i18n is wired through `useT()` on most surfaces. This redesign is **not a visual re-do**; it's a:

1. **Primitive-fill pass.** ~12 primitives are missing (Dialog, Sheet, Popover, DropdownMenu, DataTable, Tabs, Select, Skeleton variants, EmptyState, Alert, Switch/Checkbox/RadioGroup, Field, Tooltip, Breadcrumb, Command palette). Most surfaces hand-roll their own copy of each, which produces token drift and a11y holes.
2. **Token-scale pass.** Today's tokens are colour + radius + 3 motion durations only — no spacing scale, no z-index ramp, no opacity scale, no semantic `--info`, no typography scale, no motion variants (only durations). Z-30/40/50 magic numbers are scattered; opacity is hard-coded `/40`/`/60`/`/90` everywhere.
3. **State-coverage pass.** Loading, empty, and error states are inconsistent — 5 different "loading" conventions across 5 surfaces; multiple routes return `null` while auth resolves (causes flash-of-nothing).
4. **Interactive-quality pass.** Streaming UX is the largest visible gap — the tutor (the agentic-AI demo centrepiece) is a plain POST + spinner. Quiz options aren't a radiogroup. dnd-kit drag is opacity-only. The block renderer ships no syntax highlighting.
5. **Dataviz pass.** Mastery / path / observability surfaces ship zero SVG/canvas/charts. The mastery dashboard is two same-coloured progress bars per course.
6. **Light-mode design pass.** Light is currently an axe-suite escape hatch, not a designed theme — `globals.css:62-68` admits the lime was bumped to clear AA, Sonner is pinned `theme="dark"` because the light palette failed axe, surface ramp is flat. Light has to become a real theme, not a regression test.
7. **CI safety net.** Zero visual-regression coverage. axe gate skips `/learn/[slug]`, `/reviews`, `/mastery`, `/studio/[id]`, `/studio/draft/[id]`, `/admin/observability`, `/admin/evals`, `/verify-cert`, `/reset-password`, `/verify-email`, 404, error.tsx. Redesign without screenshot diffs = silent regressions.

Every loop ships against one of these seven axes.

## 1. Design foundation — what stays, what flexes

`docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md` is the design constitution; this audit is its 2026-05-26 follow-up.

The Workbench tokens, motion, type stack, and 8px grid are kept verbatim. Loops only edit `globals.css` to add new semantic tokens (info-blue, focus-within ring, z-index ramp, denser spacing scale) — never to mutate existing ones.

What the redesign formally **extends** rather than replaces:
- **`--info` semantic colour** (sibling to `--success`/`--warning`/`--destructive`) — currently info messaging falls into `--muted` or one-off Tailwind hues.
- **z-index ramp** (`--z-sticky`, `--z-overlay`, `--z-modal`, `--z-popover`, `--z-toast`, `--z-tooltip`) — `site-header.tsx:103`, `notifications-bell.tsx:93-94`, `layout.tsx:43` and the rolled-by-hand modals all pick z numbers ad hoc.
- **Spacing scale tokens** (`--space-0` through `--space-12`) — today the "8px grid" claim in CLAUDE.md is convention-only, not enforced; relies entirely on Tailwind's default 4px scale.
- **Opacity scale** (`--opacity-disabled`, `--opacity-hover`, `--opacity-overlay`) — currently `/40`, `/60`, `/90` hard-coded literals.
- **Typography scale** (`--font-size-display`/`-h1`/`-h2`/`-h3`/`-body`/`-caption`/`-mono-small`) — every page invents its own `text-3xl`, `text-4xl` etc.
- **Motion variants** (`--ease-spring-soft`, `--ease-spring-firm`, `--motion-rise-distance`, `--motion-scale-press`) for dialogs/sheets/dropdowns and interactive press states.
- **Light theme designed properly** — re-pick the surface ramp (current `#FFFFFF / #F4F4F2 / #F0F0EB` is three steps too close to read as elevation), re-derive the lime so it reads as electric in both themes, give Sonner a real light palette so the `theme="dark"` pin can come off.

What it **does not** revisit:
- Lime accent. The colour itself, its AA-deeper light-mode sibling (`hsl(75 80% 25%)`), and the rule "one lime per screen" are off-limits.
- Border-elevation principle. No shadows, no glass blur, no gradients.
- Inter + JetBrains Mono pairing.
- Dark-first default.

## 2. Missing primitives — the design-system fill list

Drives the Phase 1 design-system gap analysis. Stars are usage gravity (★ = one surface, ★★★ = ≥4 surfaces).

| Primitive | Gravity | Drives | Notes |
|---|---|---|---|
| **Dialog** | ★★★ | Tutor modal on /courses/[slug]; ai-outline-modal, ingest-modal, onboarding-tour in studio; profile delete-confirm; future destructive-action confirms in admin | Four modals currently hand-roll `fixed inset-0 z-50 backdrop-blur-sm` + their own Escape handler + click-outside; none has focus trap, `aria-modal`, or focus restore. Build on Radix Dialog. |
| **Sheet** | ★★★ | Mobile menu (site-header.tsx:191-254); future studio side-panels; future settings drawer | Mobile drawer is a hand-rolled `border-t` block — no slide-in animation, no swipe-close, no portal. Radix Dialog with `side` variant covers this. |
| **Popover** | ★★ | notifications-bell.tsx:91-148 (built inline, no escape-to-close, no portal, no focus return); future tooltips that need rich content | Radix Popover. |
| **DropdownMenu** | ★★★ | locale-switcher (currently cycles because no dropdown exists — locale-switcher.tsx:13-28), user-menu in header, future `…` per row in admin tables | Radix DropdownMenu. |
| **DataTable** | ★★★ | /admin/users, /admin/courses, /admin/audit, /admin/observability LLMTracesTab, /admin/observability CeleryTab, agent-reasoning-panel.tsx:117 | 6 surfaces re-implement `<table className="w-full text-sm">` + `<thead className="bg-muted/40 font-mono">` + ad-hoc row chrome. Need sort, paginate, row-action menu, empty/loading slots, sticky header. |
| **Tabs** | ★★★ | /studio (status filter rail), /admin/observability (tab rail), future /profile section nav | Both are visually identical hand-rolled `role="tab"` button strips with `border-b-2 border-primary` active marker — no focus-roving. Radix Tabs. |
| **Select / Combobox** | ★★★ | /studio/new, /studio/[id], /admin/users role, /profile notif prefs, lesson-editor quiz kind, all catalog filters | All use native `<select>` with the same 100-char `selectClass` string duplicated. Combobox additionally unlocks subject typeahead on /courses + studio. |
| **Tooltip** | ★★ | locale-switcher `title=` attrs, KBD-shortcut hints (once we add them), reasoning-panel tool cells | Radix Tooltip. |
| **Skeleton** (variants: row / card / text-block / chart / image) | ★★★ | Every loading state — /studio:142, /admin observability tabs, /admin/evals:103, /profile notifs:374, dashboard, mastery, reviews, lesson player | Today every loading is `<p>Loading…</p>` OR a single `h-32 animate-pulse` block — 5 different conventions across 5 surfaces. Promote the existing `.skeleton` utility into a real `<Skeleton variant=… />` component. |
| **EmptyState** | ★★★ | Every "no data" branch | Each surface rolls a one-off `<div className="surface p-8">`. Want an `<EmptyState icon title body cta />` consumed everywhere. |
| **Alert** | ★★ | Error/success banners across studio + auth + profile | Today these are ad-hoc divs with semantic colour mixed in inline. |
| **Switch / Checkbox / RadioGroup** | ★★ | Profile notif prefs (7 toggles), admin/courses "featured only", lesson "free preview", admin/users active, quiz options | Currently raw `<input type="checkbox">` with `accent-[hsl(var(--primary))]` literals. Need Workbench-flavoured small Switch + a real RadioGroup for the quiz radiogroup a11y fix. |
| **Field** (label + hint + error + input slot) | ★★★ | Every form across studio, lesson-editor, profile, auth | `<div className="space-y-1.5"><label className="font-body text-sm font-medium">…</label><Input /></div>` repeated dozens of times. The Field is also the natural home for inline validation — currently nonexistent. |
| **Breadcrumb** | ★★ | /studio/[id] deep nesting, /admin/* deep nesting | Absent today; deep studio + admin nesting reads as "back-button-only nav". |
| **Spinner / Loader** | ★ | Inline pending states across forms + tutor + mark-complete CTA | `Loader2` from lucide spun inline; want a `<Spinner size sm/md/lg />` so we stop hardcoding sizes. |
| **KBD** | ★ | Cmd+K hint, FSRS shortcuts (1/2/3/4), text-editor shortcuts | A Workbench-density product mandates this; today completely absent. |
| **Command palette (cmdk)** | ★★ | Cmd+K global search/nav — Linear/Raycast/Vercel-dashboard density mandates this | New surface; uses Dialog + Popover + DropdownMenu. |
| **Toast wrapper** | ★ | `notify.success(MessageKey)` typed indirection over Sonner | Without it, every callsite passes raw English strings that bypass `useT()`. |
| **`LinkButton`** / `Button asChild` audit | ★ | reset-password:92, verify-email:113, verify/[id]:105, course-detail-view:370 | All currently nest `<Button>` inside `<Link>` — produces nested-interactive a11y warnings. Either consume `Button asChild` or build a thin `<LinkButton>` wrapper. |
| **`useHydrated()` hook + `<AuthCard>`** | ★ | login:57, register:34, forgot:30, reset:44 + 6 byte-identical auth chromes | Hydration-gate paragraph copy-pasted 4×; auth chrome copy-pasted 6×. |

Total: 17 primitives + 2 patterns. (Five low-gravity items — Tooltip, Spinner, KBD, Toast wrapper, LinkButton — ship as a single "small parts" loop.)

## 3. Per-surface findings

### Home (`/`)
Polished. Workbench-true, hero left-aligned, single primary CTA, cartouches in mono. Featured-courses grid lands flat. No reveal animations. The `home-view.tsx` composition is clean.

**Minor:** featured grid empty-state copy lands on `home.emptyBody`, fine, but there's no "browse all courses" CTA on the empty branch — dead end.

### Catalog list (`/courses`)
- Polished overall — sticky filter rail, mono eyebrow, subject tabs, skeleton matches grid shape.
- **Gap (design intent unmet):** original spec §2.2 says "Catalog defaults to a table; grid is a toggle." Today the catalog ships **grid only** — no table view, no toggle. Decision needed: ship the table view in a loop, or formally relax the spec.
- **Gap:** no URL sync — typing in the search box or toggling filters never updates the URL; back-button doesn't restore, shareable links broken. State lives in `useState`, params only read once via `useEffect`.
- **Gap:** subject tabs use `<button aria-pressed>` but no `role="tablist"`/`tab` semantics.
- **Gap:** difficulty group `aria-label` reuses `catalogPage.diff.beginner` as the group name (copy bug).
- **Gap:** no `courses.error` branch — API failure falls into the empty state, masking real outages.
- **Gap:** sticky filter rail hard-codes `top-16` (header height assumption that breaks if header grows).

### Course detail (`/courses/[slug]`)
- Verdict: functional but bland.
- Loading state is centred "Loading…" string — no skeleton.
- Error state is one line of text, no recovery action.
- Unauthenticated enroll path uses `window.location.href` — full page nav, drops scroll/state.
- Tutor modal `fixed inset-0` has **no focus trap, no `role="dialog"`, no `Escape`, no `aria-modal`** — click-outside only.
- PDF cert link is bare `<a href>` to `/api/v1/...pdf` — no auth-error fallback; if logged out the user sees raw API error JSON.
- Three sibling sections (outcomes, syllabus, reviews) live in one big inline JSX blob — should be `<CourseOutcomes>`, `<CourseSyllabus>`, `<CourseReviews>` locals.

### Lesson player (`/learn/[slug]`)
- Solid Workbench frame; outline + player + tutor 3-col grid on `lg` is intentional.
- **`md` viewports (640–1023px) break:** the 3-col grid collapses to a stack and the tutor lands *below* the outline AND the player; outline itself sits below the player because `order-2`. The agentic demo is invisible on tablet/laptop-portrait.
- Returns `null` while auth resolves → half-second flash of nothing; no skeleton matching the two-column shell.
- "Mark complete" CTA has no `disabled` during in-flight mutation → double-click sends two POSTs.
- Outline `max-h-[70vh]` plus inner `overflow-y-auto` produces a nested-scroll trap on iOS.

### Block renderer (`block-renderer.tsx` consumed by lesson player)
- Tolerates unknown nodes, strips `window.opener`, three callout variants. Good defensive shape.
- **Big stub tell:** code blocks render in **plain text — no syntax highlighting in the learner bundle**. For an e-learning product targeting engineers this is the single most visible "feels unfinished" hit.
- Lesson media: raw `<img>`, no skeleton/aspect-ratio reservation → CLS on every image lesson.
- Lesson video: no poster, no buffering UI, no error fallback if the MinIO URL 403s.
- Quiz `short`-answer uses unstyled inline `<input>` — drifts from token system; should consume the `Input` primitive.
- **Quiz options are not a radiogroup** — bare `<button>` rows, no `role="radio"`/`role="checkbox"`, no arrow-key nav, no `aria-checked`, no fieldset/legend. Keyboard users tab through every option; screen readers don't know it's a question.
- Past-attempt pills use a literal `"✓"` glyph — should match the lucide set.

### Tutor (`/tutor` embedded in lesson + course detail)
- **The streaming gap is the most visible regression.** `Tutor.postMessage` (endpoints.ts:670) is a plain POST — no SSE, no `ReadableStream`. Users see a spinner for the full 10–15s LLM call. For a portfolio whose differentiator is "watch the agent think" this kills the demo.
- No `aria-live="polite"` on the assistant turns — screen readers miss them.
- Optimistic user message has no failure rollback or retry affordance — `onError` only toasts.
- `useEffect` deps disable hook-lint and re-fire on `courseId` change with no teardown → switching courses leaks the prior `conversationId`.
- Textarea has no auto-grow; long drafts scroll inside a 64px box.
- Reasoning panel `conversationId`/`messageId` props are optional but **TutorPanel never passes them** — the "See the full trace" deep-link is dead code in the live surface.
- No focus management when the tutor opens from `/learn/[slug]` — focus stays on the Sparkles button; expected: textarea autofocus.

**Strengths to preserve:** agent-reasoning-panel.tsx is a real table with per-tool detail renderers (`RetrieverDetails`, `CodeRunnerDetails`) — those are tailored, not JSON dumps. Keep.

### Dashboard (`/dashboard`)
- Polished, on-brand, light on data.
- Returns `null` until `ready` → flash-of-nothing.
- No skeleton for `enrollmentsQ` loading state (silently renders 0/0 counts before data lands).
- No error path if `enrollmentsQ` fails — page just shows empty state.
- Feels like a v1 landing: no streaks, no recent activity, no "due now" surfacing.

### Mastery (`/dashboard/mastery`)
- **NOT real data viz** — two thin Progress bars per course + a list of pills. The page header promises "mastery" and ships zero spatial encoding (no time axis, no per-lesson grid, no heatmap, no per-topic radar).
- Completion bar and mastery bar use the **same lime fill** — colour-indistinguishable when stacked.
- Skeleton is a single `h-32 animate-pulse` block — no shape parity with the populated layout.
- Weak-spot signal severity uses Badge colour only — `signalLabel` is a numeric injection, no icon → colour-only meaning for `quiz_failed` vs `card_overdue`.

### Reviews / FSRS (`/dashboard/reviews`)
- Best-realised surface in the audit — clear stats grid, inline review without modal, four-button grading respects equal-status self-report.
- `null`-until-ready flash.
- Stats query has no error fallback.
- Grade buttons are 2×2 on mobile but tap targets are tight (no `h-11` minimum).
- **Missing the Anki convention 1/2/3/4 keyboard shortcuts** for Again/Hard/Good/Easy.
- "All done" message is fragile — won't appear if user grades the last card (renders only when list non-empty AND no active).

### Path (`/dashboard/path`)
- Most visibly "stub" surface in the app.
- **Inline English string (`path/page.tsx:40` self-flags i18n bypass).**
- **Literal `TODO(orchestrator)` in shipping code (path/page.tsx:42-45).**
- `MilestoneTable.tsx:185` renders `course_slug` (URL string) as the display title → user sees `cool-stuff-101` instead of "Cool Stuff 101".
- Truncated course id `slice(0,12)` displayed in the row (debug affordance leaked to product).
- No visual timeline — milestones are stacked headings, no horizontal weeks Gantt that would justify the "8-course curriculum" framing.
- "You're caught up" branch renders only a mono line, no surface card → page has a header but no body in this state.

### Studio (`/studio` + `/studio/new` + `/studio/[id]`)
- `/studio` list is the cleanest of the three — border-b-2 tab filters, hairline rows, mono meta. Solid.
- No pagination, no search input → instructor with 100+ courses gets one giant scroll.
- `/studio/new` is a flat single-page form, not a wizard. No client-side validation, no field hints, native `<select>`, no subject loading state, no unsaved-changes guard.
- `/studio/[id]` is long-stacked form with no nav rail, no jumplinks, no sticky save bar. Block editor (Tiptap) integrates cleanly.
- **dnd-kit drag visual is opacity 0.5 only — no DragOverlay, no drop indicator line, no insertion gap.**
- "Dirty" / "Save" is per-section local state. No global unsaved-changes guard, no autosave.
- **Block editor uses `window.prompt()` for link + image URL** (explicit "v1 crude" admission in source).
- Lesson editor still wraps in `<Card>` while everything else moved to flat sections — token drift.
- Quiz editor: native `<select>` for question kind, no validation that `answer_keys` is non-empty.
- LearningOutcomesEditor + quiz choices have no drag reorder — only top-level modules use dnd-kit.

### Admin
- `/admin` is a clean counter wall — no charts, no time-series. Stats query has no loading/error skeleton.
- `/admin/users`, `/admin/courses`, `/admin/subjects`, `/admin/tags`: real `<table>` elements but hand-rolled. **No sort, no pagination, no row selection, no bulk action, no confirm dialogs on destructive actions.** admin/courses search is uncontrolled-debounce-less → refetch every keystroke.
- `/admin/observability`: real (queue depths, trace tree, retrieval audits with score tinting). **Zero charts — Celery queue depth is a 2-col table not a graph.** Tab nav rolled inline.
- `/admin/audit`: bare cursor table. No filter-by-action/actor, no date range. `JSON.stringify(e.data)` is the data column.
- `/admin/evals`: ScoreBadge uses **raw Tailwind hues (`text-emerald-300`/`amber-300`/`rose-300`) that bypass tokens** and break the light theme. LLMTracesTab StatusBadge has the same bypass.

### Profile (`/profile`)
- Longest stacked form in the app. Border-t sections + helper `Section` component.
- 7 native `<select>` toggles for notif prefs where Switch primitives would communicate intent in half the space.
- Delete-confirm is inline expand, **no Dialog primitive for an irreversible action.**
- No tab/anchor nav for the 5 sections — long mobile scroll.
- Email/password forms: no client-side strength meter, no inline match errors.

### Auth surfaces (login, register, forgot, reset, verify-email, verify/[id], confirm-email-change)
- The 6 surfaces (excl. register) are **template-consistent and polished** — identical card chrome, mono eyebrow, hydration gate, `aria-live` regions, lucide status icons in semantic colours.
- /login: no show/hide password toggle, no "remember me" affordance even though refresh tokens are 14d, Suspense fallback is an `h-80` skeleton that doesn't match the card shape it replaces → layout flash.
- /register: password hint is static text — no live strength meter, no min-length feedback. No password confirm field. No T&C / privacy checkbox.
- /reset-password missing-token branch and /verify-email and /verify/[id] all wrap `<Button>` inside `<Link>` (nested interactives).
- /verify-email + /confirm-email-change auto-fire on mount with **no idempotency guard** — React 19 strict-mode double-invoke OR a refresh will burn the token.
- Hydration-gate paragraph copy-pasted 4×; auth chrome copy-pasted 6×. → `useHydrated()` + `<AuthCard>`.

## 4. Cross-cutting patterns (the meta-list)

1. **Token discipline is excellent at the page level, partial in deep components.** Pages use `bg-card`/`text-muted-foreground`/`border-border` consistently. Two leaks worth fixing: admin/evals/ScoreBadge raw emerald/amber/rose, observability/LLMTracesTab StatusBadge raw yellow. course-card.tsx hardcodes `"Featured"` and `"modules"` (i18n leak).
2. **Motion tokens exist but aren't always referenced.** `button.tsx:21` and `input.tsx:20` hard-code `duration-[160ms]`; `progress.tsx:36-37` hard-codes `240ms cubic-bezier(0.16, 1, 0.3, 1)`. The variables are correct; the callsites should reference them, not duplicate literals. A `.reveal` utility exists in globals.css:213-224 (scroll-driven animation with `@supports` fallback) that's used by nobody — promote or delete.
3. **i18n coverage is ~63% of .tsx files (47/75).** 697 keys in `en.ts`, parity gate on. Known hardcoded leaks: `layout.tsx:45` "Skip to content" (skip link itself — `onboarding.skip` exists at en.ts:667 but isn't reused); `site-footer.tsx:22` "GitHub" (brand — debatable); `header-search.tsx:39` Suspense fallback placeholder "Search courses…" (acknowledged compromise in source); `layout.tsx:13-20` metadata title/description (Next 15 metadata API doesn't auto-localise — needs per-route `generateMetadata`); course-card.tsx "Featured" + "modules"; path/page.tsx + PathBuilderForm.tsx inline English fixtures.
4. **State coverage is inconsistent.** 5 different loading conventions across 5 surfaces (centred-text-line, single grey rectangle, `<p>Loading…</p>`, return `null`, container-shaped skeleton). Empty states are one-off each. Error branches mostly fall back to empty states or single-line text. → drives Skeleton + EmptyState + ApiErrorPanel.
5. **Mobile + tablet are second-class.** Lesson player and tutor only have side-by-side affordance at `lg+`. 640–1023px is the agentic demo's blind spot. Reviews grade buttons cramped on mobile. Profile has no section nav so mobile is one long scroll. Header is OK, footer is OK.
6. **Streaming UX is absent.** The tutor + agent reasoning is the portfolio centrepiece, but the wire path is single-shot POST. No SSE plumbing exists in `lib/api/`. Adding it ripples to: `endpoints.ts`, tutor-panel.tsx render loop, agent-reasoning-panel.tsx step accumulation, and the `aria-live` story.
7. **Dataviz is absent.** Mastery, path, observability, dashboard home all warrant charts. No SVG/canvas/recharts/anything in the bundle. For an LMS targeting "learn what you actually use", learning analytics being stub-shaped is a credibility tax.
8. **Two "fixture-in-production" tells:** /dashboard/path renders course slugs as titles and exposes truncated DB IDs to learners; PathBuilderForm has hardcoded English placeholder. Source self-flags both.
9. **Accessibility ground state is decent; high-value paths are weak.** Focus rings via tokens, `aria-current` on nav, skip-link in layout, axe-core CI gate via Playwright on 9 routes. But: quiz options aren't a radiogroup, tutor stream has no live region, mastery signals are colour-only, four modals lack focus trap + `aria-modal`. Axe gate blind spots: `/learn/[slug]`, `/dashboard/reviews`, `/dashboard/mastery`, `/dashboard/path`, `/studio/[id]`, `/studio/draft/[id]`, `/admin/observability`, `/admin/evals`, `/admin/audit`, `/verify-cert`, `/reset-password`, `/verify-email`, 404, error.tsx.
10. **RTL discipline is mostly good but has four leaks.** Shared chrome (site-header, header-search, notifications-bell, sessions-card, image-upload) uses logical properties (`ms-/me-`, `ps-/pe-`, `start-/end-`) consistently. Leaks: `trace/TraceTimeline.tsx:146,152` raw `left-X`, `studio/.../draft-trace-timeline.tsx:83,86` raw `left-X`, `trace/TraceStepCard.tsx:107` `text-left`, `tutor/agent-reasoning-panel.tsx:117` `text-left`. These will visually break under `dir="rtl"`.

## 5. Test infrastructure findings

- **Unit (vitest):** 36 spec files in `apps/frontend/tests/` — heavy component coverage (block-editor, lesson-editor, tutor-panel, agent-reasoning-panel, studio-draft-trace, trace-timeline, mastery-page, header-search, image-upload, etc.) plus infra tests (compose-cors, ci-workflow-shape, i18n-parity, env-api-base, makefile-pnpm-invocation, next-api-rewrite, playwright-timeouts). Setup stubs `next/navigation` and the i18n provider so every test gets real English strings.
- **E2E (Playwright):** 10 specs (~1,376 LOC). Runs against `chromium` + `webkit` projects — **no firefox, no mobile viewport project**. Covers: home + catalog smoke, auth (register→verify→forgot→reset), learner journey (enrol→lesson→cert), instructor flow (create→AI outline→publish), tutor citations (`[L:…]` token assertion), multi-modal ingest (YouTube), README screenshots, axe gate.
- **A11y (axe-core):** full WCAG 2.2 AA gate on 9 routes (accessibility.spec.ts) — `/`, `/courses`, `/login`, `/register`, `/forgot-password`, first seeded course detail, `/dashboard`, `/profile`, `/studio`, `/admin`. **Blind spots that the redesign must fill before it lands:** `/learn/[slug]`, `/dashboard/reviews`, `/dashboard/mastery`, `/dashboard/path`, `/studio/[id]`, `/studio/draft/[id]`, `/admin/observability`, `/admin/evals`, `/admin/audit`, `/verify-cert`, `/reset-password`, `/verify-email`, the 404 surface, `error.tsx`.
- **Visual regression: NONE.** `screenshots.spec.ts` captures PNGs for the README but does not diff. No Percy/Chromatic/Playwright `toHaveScreenshot` baselines anywhere. There are **zero `*.snap` / `*.png` baselines in tests/**.

**Implication:** the foundation loop has to land Playwright visual regression with a baseline set of screenshots — otherwise every subsequent surface loop is shipping blind. Without it the redesign can silently regress trace timelines, studio replay, observability tabs, and the verify-cert flow with no CI signal.

## 6. Out-of-scope for this redesign (deferred)

- New backend endpoints. UI loops may need *new shapes* from existing endpoints (e.g. a series-returning `/mastery/timeline` for the heatmap), and those go in as small backend follow-ups under `apps/backend/app/api/v1/`. But no greenfield product features.
- Replacing Tiptap. Block editor stays; it just gets dressed up.
- Replacing sonner. Toasts stay.
- Replacing the search box behaviour beyond URL-sync.
- Mobile-native shell (no Capacitor/Expo wrap). Responsive web only.

## 7. What ships in which loop (provisional sequence)

The exact loop list will firm up in Phase 1 (gap analysis / SUMMARY draft). Provisional sequence — every loop can re-prioritise based on what shipped and what's still broken:

1. **Foundation A — Token scale + visual-regression baseline.** Add `--info`, `--space-*`, `--z-*`, `--opacity-*`, `--font-size-*`, motion variants. Promote duration literals in button/input/progress to vars. Land Playwright `toHaveScreenshot` for `/`, `/courses`, `/login`, `/register`, `/dashboard`, `/profile`, `/studio`, `/admin` (8 baselines, both themes = 16 PNGs). 0 net new pages.
2. **Foundation B — State + form primitives.** `<Skeleton variant=… />`, `<EmptyState>`, `<Alert>`, `<Field>`, `<Spinner>`, `<LinkButton>`, `useHydrated()`, `<AuthCard>`. Apply to auth surfaces (kills the 6-copy auth chrome) + replace the 5 different loading conventions across studio/mastery/reviews/dashboard/admin.
3. **Foundation C — Overlay primitives (Dialog/Sheet/Popover/DropdownMenu/Tooltip).** Radix-backed. Convert ai-outline-modal, ingest-modal, onboarding-tour, /courses/[slug] tutor modal, /profile delete-confirm, site-header mobile menu, notifications-bell popover, locale-switcher dropdown. Land the focus-trap + restore + `aria-modal` story.
4. **Foundation D — Form-input primitives (Select/Switch/Checkbox/RadioGroup).** Convert /studio/new, /studio/[id], /admin/users, /profile notif prefs, lesson-editor quiz kind. Kill the duplicated `selectClass` string. Quiz `RadioGroup` lands here (fixes the quiz-options a11y gap before the block-renderer loop touches them).
5. **Foundation E — Table + Tabs + Breadcrumb.** `<DataTable>` with sort/paginate/row-actions/empty/loading slots. Migrate /admin/users + /admin/courses + /admin/audit + observability LLMTracesTab + CeleryTab. Land Tabs (convert /studio + /admin/observability). Land Breadcrumb (light footprint, used in deep studio + admin).
6. **Light mode redesign.** Re-pick the surface ramp (3 distinct steps), re-derive the lime so it reads as electric in both themes, give Sonner a real light palette so `theme="dark"` pin comes off. Visual regression baselines for light theme update here.
7. **Streaming tutor.** Wire SSE end-to-end (`endpoints.ts` → SSE handler + client `ReadableStream`). Live token render in TutorPanel. `aria-live="polite"` region. Wire through `conversationId`/`messageId` so the trace deep-link works. Failure rollback + retry on optimistic user message. Auto-grow textarea. Cmd+Enter to send. **Highest-signal loop for the agentic-AI positioning.** Behind `NEXT_PUBLIC_TUTOR_STREAMING=1` during transition.
8. **Block renderer polish + lesson media.** Syntax highlighting (Shiki — already have lowlight installed, but Shiki gives the Workbench-flavoured palette latitude). Video poster + buffering + 403 fallback. Image aspect-ratio reservation + skeleton + `<NextImage>` migration. Past-attempt pills use lucide icon not `"✓"`.
9. **Mastery + path viz.** Mastery: real per-skill encoding (heatmap by lesson × week OR radar by topic), two-colour bars so completion ≠ mastery, lucide icons for signal severity. Path: horizontal week timeline (custom SVG, no recharts), fix slug-as-title, drop the TODO, fix the `slice(0,12)` debug leak.
10. **Catalog v2.** Table view + grid toggle (default = table per spec §2.2). URL sync (search + filters → params). Tablist semantics on subject tabs. Error branch with recovery action. Fix the difficulty group `aria-label` copy bug. Fix sticky `top-16` magic number.
11. **Course detail polish.** Decompose into `<CourseOutcomes>` + `<CourseSyllabus>` + `<CourseReviews>` locals. Skeleton matching the populated layout. Error-with-recovery. Fix unauthenticated enroll to use `router.push`. PDF cert link gets auth-error fallback.
12. **Studio polish.** dnd-kit DragOverlay + drop indicator line + insertion gap. Replace `window.prompt()` for link/image with Dialog. Global dirty guard + autosave indicator. Sticky save bar / section anchor-nav. LearningOutcomesEditor + quiz choices gain dnd-kit reorder.
13. **Admin polish + observability charts.** Pagination on users/courses. Debounce admin/courses search. Confirm Dialog on every destructive action (delete, role change, force-disable). Charts on observability (sparkline for Celery queue depth, timeseries for LLM cost). Replace raw Tailwind hues in ScoreBadge + StatusBadge with token references.
14. **Dashboard re-imagining.** Streaks, recent activity, "due now" surfacing. Skeleton + EmptyState + DataTable consumed. Show streak count with `--success` tinting. FSRS shortcuts (1/2/3/4) on `/dashboard/reviews`.
15. **Auth polish.** Show/hide password, password strength meter, register confirm + T&C checkbox, idempotency guard on `/verify-email` + `/confirm-email-change` (don't burn the token on double-mount). Fix the nested `Link>Button` cases via `Button asChild`.
16. **Lesson player + tutor mobile/tablet pass.** Fix the 640–1023px collapse — tutor should land in a Sheet on `md`, not inline-below. Outline scroll trap fix. "Mark complete" disabled-during-mutation. Add axe coverage to `/learn/[slug]`, `/dashboard/reviews`, `/dashboard/mastery`, `/dashboard/path` here (gate growth).
17. **RTL sweep.** Re-walk every loop's surface under `dir="rtl"`. Fix the 4 known leaks in trace/timeline/reasoning components (raw `left-X` + `text-left`). Add Playwright RTL screenshots to the visual-regression baseline.
18. **Cmd+K command palette + KBD primitive.** New surface; uses the overlay primitives from loop 3 + the typography/spacing tokens from loop 1. Linear/Raycast density mandates it. Routes nav + course search + role-aware actions.
19. **Lighthouse + screenshot regeneration.** README screenshots refreshed; Lighthouse ≥95 on home + top-2 routes. Update OG images.
20. **FINAL-REPORT.** Comprehensive Codex pass on the full diff vs main. Address legitimate findings. Done.

Soft cap ~2000 lines per loop. Cohesive changes that hit 2500 are OK if noted. The 3rd-loop Codex rescue cadence applies as the spec describes — Codex passes after loop 3 (foundation tier), loop 6 (light + streaming kickoff), loop 9 (data viz), loop 12 (studio), loop 15 (auth/polish wave), loop 18 (cmd+k).

## 8. Anti-goals

- Don't redesign the lime accent system. Don't add gradients. Don't add shadows. Don't add 3D tilt.
- Don't introduce a new icon library. Lucide stays.
- Don't churn the i18n key namespaces beyond fixing the inline-English leaks.
- Don't replace TanStack Query, next-themes, sonner, dnd-kit, Tiptap.
- Don't introduce a CSS-in-JS runtime. Tailwind 4 + globals.css + Workbench utilities is the styling boundary.

## 9. Risks

- **Streaming tutor** touches backend (`endpoints.ts` → SSE handlers + new client) + frontend (TutorPanel → token accumulator + ARIA story). Highest-blast-radius loop. Plan to ship behind a feature flag `NEXT_PUBLIC_TUTOR_STREAMING=1` and dual-path during transition.
- **DataTable** has to be flexible enough for 5 different table shapes without becoming a 1000-line config monster. Risk: over-abstraction. Mitigation: ship the smallest possible API surface (`columns`, `rows`, optional `pagination`, optional `rowActions`) and grow from real usage.
- **Mastery viz** depends on a backend shape that doesn't exist yet (per-skill time series). If the backend can't ship the series in the same loop, the loop ships a "what the chart will look like with real data" sketch + a backend follow-up issue.
- **Token-drift snipes** (admin/evals raw Tailwind hues etc.) are tempting "while I'm here" edits — keep them scoped to their loop, not the foundation loop, so each loop's diff is reviewable.
