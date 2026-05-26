# Loop 14 — goal

**Foundation E (full tier)**: Tabs + Breadcrumb + DataTable primitives + 5 surface migrations + token-drift cleanup.

User explicitly asked for bigger per-iteration scope on 2026-05-26 ("a team worth of work for a day"). This loop bundles what would have been Loops 14–16 in the original AUDIT.md §7 sequence into one push.

## Why now

- Foundation D closed in Loop 13 (form-input primitives). Foundation E is the largest remaining tier from the audit's primitive backlog — three primitives that together unlock pagination, sort, deep nav, and tabbed surfaces.
- AUDIT.md §3 calls out 6 admin tables that hand-roll `<table className="w-full text-sm">` + ad-hoc row chrome. Migrating to DataTable in batch is the kind of cohesive cleanup that fits one loop better than three.
- ScoreBadge + admin/evals/[suite]/[reportId] token drift (`text-emerald/amber/rose` literals) is small enough to ride along — same files the DataTable migration touches.
- Next Codex rescue cadence anchors at Loop 15. This loop ships without rescue.

## What "done" looks like

1. **`apps/frontend/src/components/ui/tabs.tsx`** — Radix Tabs with `Tabs`, `TabsList`, `TabsTrigger`, `TabsContent`. Workbench border-b-2-on-active visual matches the hand-rolled patterns it replaces.
2. **`apps/frontend/src/components/ui/breadcrumb.tsx`** — semantic nav with `Breadcrumb`, `BreadcrumbList`, `BreadcrumbItem`, `BreadcrumbLink`, `BreadcrumbPage`, `BreadcrumbSeparator`. Custom (no Radix needed) — small enough.
3. **`apps/frontend/src/components/ui/data-table.tsx`** — minimal-API generic table: `columns`, `rows`, optional `pagination`, optional `rowActions`, `emptyState`, `loading` slot. Sort indicator on sortable columns; mono-uppercase column headers.
4. **Tabs migrations:**
   - `/studio` status filter rail (lines 116-130 of studio/page.tsx).
   - `/admin/observability` tab rail (Celery / LLM Traces / RAG audits tabs).
5. **DataTable migrations:**
   - `/admin/users` — preserves role Select + active toggle in row actions.
   - `/admin/courses` — preserves search input + featured Switch + per-row toggle.
   - `/admin/audit` — cursor pagination preserved.
6. **Breadcrumb application:**
   - `/studio/[id]` — `Studio › <Course title>` (back-button-only nav today per AUDIT.md §3).
7. **Token-drift cleanup:**
   - `ScoreBadge.tsx` — `text-emerald-300 / text-amber-300 / text-rose-300` → `text-success / text-warning / text-destructive` semantic tokens.
   - `/admin/evals/[suite]/[reportId]/page.tsx` border literals → semantic borders.
8. **Unit tests** in `apps/frontend/tests/{tabs,breadcrumb,data-table}.test.tsx`.
9. **Existing tests stay green**: studio integration, admin units, lesson editor, profile.
10. **`make test.web` green.**
11. **STATUS.md row + CHANGELOG entry + `loop-14-result.md` retrospective.**

## Out of scope

- DataTable column-resizing / virtualization / column visibility — minimum-viable API only.
- Per-row drag-reorder. Studio modules use dnd-kit already; admin tables don't need it.
- Pagination on admin/users + admin/courses (the audit calls for it, but server-side paging is a backend follow-up). Cursor-based paging on /admin/audit lands here because that backend already supports it.
- Admin observability charts. Token-drift fixes there ride along; the chart loop (Loop 16ish in original sequence) handles visualization.
- Sonner pin-off retry. Codex rescue. RTL sweep.

## Success criteria (binary)

- [ ] Tabs primitive ships, Radix-backed.
- [ ] Breadcrumb primitive ships, semantic nav.
- [ ] DataTable primitive ships with minimum-viable API.
- [ ] 2 Tabs migrations land.
- [ ] 3 DataTable migrations land.
- [ ] 1 Breadcrumb application lands (`/studio/[id]`).
- [ ] ScoreBadge + eval report no longer reference raw Tailwind hues.
- [ ] `make test.web`: green, file count grows by 3.
- [ ] CI 5 gates green.
- [ ] Prod deploy + visual review pass.

## Estimated diff (target band 1500-2200 LoC)

- Tabs primitive: ~70 LoC
- Breadcrumb primitive: ~50 LoC
- DataTable primitive: ~220 LoC
- 2 Tabs migrations: ~100 LoC churn (net likely -30 LoC)
- 3 DataTable migrations: ~400 LoC churn (net likely -150 LoC because hand-rolled `<thead>`/`<tbody>`/`<tr>` markup compresses heavily)
- Breadcrumb application: ~30 LoC
- Token-drift fixes: ~40 LoC
- Tests: ~500 LoC
- Loop docs: ~600 LoC (don't count)
- STATUS + CHANGELOG: ~50 LoC
- pnpm-lock churn: ~40 LoC

**Total source diff: ~1500-1800 LoC.** On target for "team-day of work".
