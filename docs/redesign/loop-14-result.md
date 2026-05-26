# Loop 14 — result

Surface: Foundation E (full tier) — `<Tabs>` + `<Breadcrumb>` + `<DataTable>` primitives + 5 surface migrations + ScoreBadge token-drift fix.

**Foundation E closes here.** Combined with Foundations A (Loop 1), B (Loop 3-5), C (Loops 10-12), and D (Loop 13), the audit's primitive backlog from §2 is now empty.

Loop scope intentionally bigger per user feedback "team-day of work, not single-dev hour" (2026-05-26).

## What shipped

### Primitives
- **`apps/frontend/src/components/ui/tabs.tsx`** (75 LoC). Radix Tabs. Trigger uses the Workbench convention — mono-uppercase text, `border-b-2 border-transparent data-[state=active]:border-primary`.
- **`apps/frontend/src/components/ui/breadcrumb.tsx`** (92 LoC). Custom (no Radix needed). Semantic `<nav>` + `<ol>` + `<li>` with `BreadcrumbPage` carrying `aria-current="page"`. ChevronRight separator with `rtl:-scale-x-100` for natural mirroring.
- **`apps/frontend/src/components/ui/data-table.tsx`** (155 LoC). Custom, no tanstack-table dep. Minimum-viable API; sort is intent-only (consumer applies via server-side). Loading state: 5 Skeleton rows.

### Migrations
- **`apps/frontend/src/app/studio/page.tsx`** — status filter rail (`all/draft/published/archived` + per-status count) → `<Tabs>`.
- **`apps/frontend/src/app/admin/observability/page.tsx`** — Celery / LLM Traces / Retrieval Quality tab rail → `<Tabs>`. Inside-tab components (`CeleryTab`, `LLMTracesTab`, `RetrievalTab`) untouched.
- **`apps/frontend/src/app/admin/users/page.tsx`** — `<table>` → `<DataTable>` with 5 columns. Role Select + Disable/Enable button now live in an `actions` column.
- **`apps/frontend/src/app/admin/courses/page.tsx`** — `<table>` → `<DataTable>` with 5 columns. Per-row feature/unfeature toggle stays in an action column.
- **`apps/frontend/src/app/admin/audit/page.tsx`** — `<table>` → `<DataTable>` with 5 columns. Cursor pagination wraps the table.
- **`apps/frontend/src/app/studio/[id]/page.tsx`** — added `<Breadcrumb>` showing `Studio › <course title>` above the page header.

### Token-drift fixes
- **`apps/frontend/src/components/admin/evals/ScoreBadge.tsx`** — `text-emerald-300 / text-amber-300 / text-rose-300` → `text-success / text-warning / text-destructive`.
- **`apps/frontend/src/app/admin/evals/[suite]/[reportId]/page.tsx`** — StatusBadge borders + text: `border-amber-700/40 / text-amber-300` → `border-warning/40 / text-warning`; rose variants → `destructive`.

### Tests
- **`apps/frontend/tests/tabs.test.tsx`** (5 tests).
- **`apps/frontend/tests/breadcrumb.test.tsx`** (4 tests).
- **`apps/frontend/tests/data-table.test.tsx`** (7 tests).

### Other
- **`apps/frontend/package.json`** — `@radix-ui/react-tabs ^1.1.13`.

## Success criteria

- [x] Tabs primitive ships, Radix-backed.
- [x] Breadcrumb primitive ships, semantic.
- [x] DataTable primitive ships with minimum-viable API.
- [x] 2 Tabs migrations.
- [x] 3 DataTable migrations.
- [x] 1 Breadcrumb application.
- [x] ScoreBadge + eval report no longer reference raw Tailwind hues.
- [x] `make test.web`: 46 files / 260 tests green (+3 files / +16 tests vs Loop 13).
- [ ] CI 5 gates green — pending push.
- [ ] Prod deploy + visual review pass — pending.

## Lessons

- **Big loops still work if migrations are mechanically similar.** 3 DataTable migrations + 2 Tabs migrations + 1 Breadcrumb application + 2 token-drift fixes all landed cleanly because each followed the same diff shape. The risk in big loops isn't size, it's variance.
- **Custom-built primitives can beat Radix when the API is narrow.** Breadcrumb is just `<nav>` + `<ol>` + `<li>`; pulling in Radix for it would add a dependency for ~50 LoC of semantics that vanilla HTML covers. Same for DataTable's minimum-viable API. The bar for "must use Radix" is "we need focus management, keyboard semantics, or portal positioning."
- **Sort intent + server-side application is the right DataTable split.** No client-side state in the primitive means the table doesn't need to know about row identity or sort comparators; the consumer's TanStack Query keys handle it.
- **Empty-state handling unifies nicely.** Each DataTable migration replaced an inline empty-row `<tr><td colSpan={5}>` with an `emptyState` prop. Consistent pattern across 3 surfaces.

## Estimated vs actual diff

| Surface | Estimate (spec) | Actual |
|---|---|---|
| Tabs primitive | ~70 LoC | 75 LoC |
| Breadcrumb primitive | ~50 LoC | 92 LoC |
| DataTable primitive | ~220 LoC | 155 LoC |
| 2 Tabs migrations | ~100 LoC churn | net -40 LoC |
| 3 DataTable migrations | ~400 LoC churn | net -150 LoC (table boilerplate dies) |
| Breadcrumb application | ~30 LoC | 15 LoC |
| Token-drift fixes | ~40 LoC | 18 LoC |
| Tests | ~500 LoC | ~390 LoC |
| Loop docs | ~600 LoC | ~600 LoC |
| STATUS + CHANGELOG | ~50 LoC | ~70 LoC |
| pnpm-lock churn | ~40 LoC | ~25 LoC |

**Total source diff: ~1500 LoC.** Right on the "team-day" target. Under the 2500 hard ceiling.

## Codex rescue

Next Codex rescue lands at the end of Loop 15 per the every-3rd-loop anchor. Loop 14 ships without rescue per the spec.
