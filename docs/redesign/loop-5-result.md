# Loop 5 — Result

## What shipped

Four focused changes — a first application sweep that *terminates* (doesn't get partially undone by a later route-level redesign).

| File | Change |
|---|---|
| `apps/frontend/src/components/admin/evals/ScoreBadge.tsx` | +5 / -3 — raw `text-emerald-300 / amber-300 / rose-300` → `text-success / warning / destructive` tokens |
| `apps/frontend/src/components/admin/observability/LLMTracesTab.tsx` | +5 / -1 — `bg-yellow-500/15 text-yellow-700 dark:text-yellow-400` → `bg-warning/15 text-warning` |
| `apps/frontend/src/components/course/course-card.tsx` | +5 / -3 — `useT()` import + `t("catalog.featuredBadge")` + `t("courseCard.modulesCount", { n })` (closes audit §4 #2 i18n leak) |
| `apps/frontend/src/app/studio/page.tsx` | +14 / -10 — `<p>Loading…</p>` → 3 `<Skeleton variant="card" className="h-16" />`; hand-rolled empty-state `<div>` → `<EmptyState icon={GraduationCap} title cta />` |
| `apps/frontend/src/lib/i18n/messages/en.ts` | +1 — new `courseCard.modulesCount: "{n} modules"` |
| `apps/frontend/src/lib/i18n/messages/ar.ts` | +1 — Arabic parity `"{n} وحدة"` (the `i18n-parity.test.ts` gate enforces) |
| `docs/redesign/loop-5-{goal,result}.md` | NEW (~250) |

Total: ~50 LoC code + ~250 LoC docs. Smallest loop yet by design.

## Binary criteria — all met

- [x] `grep -E "text-emerald-300|text-amber-300|text-rose-300|text-yellow-700|text-yellow-400" apps/frontend/src/components` → 0 matches.
- [x] ScoreBadge tone mapping: ≥4 → `text-success`, ≥3 → `text-foreground`, ≥2 → `text-warning`, else `text-destructive`.
- [x] StatusBadge throttled → `bg-warning/15 text-warning`.
- [x] studio loading state replaced with 3 skeleton rows (shape-matches the populated row list).
- [x] studio empty branch consumes `<EmptyState icon={GraduationCap} title cta>`.
- [x] course-card no longer hardcodes `"Featured"` or `"modules"` — both go through `useT()`.
- [x] New i18n key `courseCard.modulesCount` parity'd in en.ts + ar.ts; `i18n-parity.test.ts` still green.
- [x] `make test.web` — 36 files / 194 tests passed in 17.09s (same as Loop 4 — no test files added/removed; existing course-card.test.tsx still passes through the migration).
- [x] Visual regression: **8/8 public baselines pass byte-stable** — proves the resolved i18n strings ("Featured", "X modules") match the pre-migration hardcoded English. The "Featured" key already existed in `messages/en.ts:26` (`catalog.featuredBadge`); the "modules" suffix needed a new formatted key (`courseCard.modulesCount: "{n} modules"`).

## Verification

```
$ make test.web
…
Test Files  36 passed (36)
     Tests  194 passed (194)

$ docker compose --profile e2e run --rm e2e \
    visual-regression.spec.ts --project=chromium --reporter=list
…
8 passed (13.8s)

$ grep -rE "text-emerald-300|text-amber-300|text-rose-300|text-yellow-700|text-yellow-400" apps/frontend/src/components
(no matches)
```

## 3-bullet retro

- **The smallest loop is the most satisfying.** Loops 1–4 built up a primitive vocabulary; Loop 5 used four of them (Skeleton, EmptyState, the `--success`/`--warning`/`--destructive` tokens, the i18n hook) in a 50-LoC diff that closes three different AUDIT.md items (§4 #1 raw-Tailwind-hue leaks, §4 #2 i18n leaks, §4 #4 inconsistent loading conventions). Foundation pays off.
- **The "terminal-scope" rule kept the loop tight.** The audit catalogues many loading + empty-state sites, but most of those routes (dashboard home, mastery, reviews, lesson player) are due for full redesigns in their own loops later. Migrating a half-baked Skeleton into a `<p>Loading…</p>` site that I'd partially rewrite three loops from now is churn. Studio's list page is the only surface in this loop because it's *not* on the later redesign queue — its current shape is fine, just its loading + empty states were lazy.
- **i18n key reuse > new keys.** `catalog.featuredBadge` was already a key (line 26 of en.ts); course-card just hadn't consumed it. Only the modules-count suffix needed a new key, and even that lands on the existing `studio.moduleCount: "{n} modules"` shape (just a different namespace because the catalog card is a different context than the studio list).

## Follow-ups discovered

- **`<Field>` adoption in studio/new + studio/[id] forms** — Loop 5 was scoped to *state* primitives (Skeleton/EmptyState) not *form* primitives (Field/Select/Switch). The latter need their consumer site to ship Field + Select together; deferred to Loop 6 (form-input primitives) or whichever loop touches studio/new first.
- **One more raw-hue site to sweep:** `apps/frontend/src/components/admin/observability/CeleryTab.tsx` may have similar token bypasses. Not surfaced in the audit explicitly but worth a sweep when the admin polish loop (AUDIT.md §7 step 13) lands.

## What to watch in Loop 6

Loop 6 per the AUDIT.md §7 sequence is the **light-mode redesign** (re-pick the surface ramp, re-derive the lime so it reads electric in both themes, give Sonner a real light palette so the `theme="dark"` pin can come off). That's the next big design call. Watch:
1. Public VR baselines re-bless for the light variants (`home-light`, `catalog-light`, `login-light`, `register-light`) — expected and called out in the result doc.
2. Whether the existing surface tokens (`#FFFFFF / #F4F4F2 / #F0F0EB`) need redesigning into a 3-step ramp with real elevation deltas (current values are too close to read).
3. Whether `--primary` light-mode value (`hsl(75 80% 25%)` = `#59730D`, the deeper green that clears AA) can be retuned to a brighter electric-friendly hue without re-failing AA. Codex rescue #2 fires after Loop 6 — and given the design call density, it's likely to be the most useful Codex pass yet.
