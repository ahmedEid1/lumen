# Loop 14 — spec

Selected option: **B** (Full Foundation E tier in one push).

## Files touched

### New
- `apps/frontend/src/components/ui/tabs.tsx`
- `apps/frontend/src/components/ui/breadcrumb.tsx`
- `apps/frontend/src/components/ui/data-table.tsx`
- `apps/frontend/tests/tabs.test.tsx`
- `apps/frontend/tests/breadcrumb.test.tsx`
- `apps/frontend/tests/data-table.test.tsx`
- `docs/redesign/loop-14-{goal,options,spec,result}.md`

### Edited
- `apps/frontend/src/app/studio/page.tsx` — hand-rolled tab rail → `<Tabs>`.
- `apps/frontend/src/app/admin/observability/page.tsx` — hand-rolled tab rail → `<Tabs>`. Inside-tab contents (`CeleryTab`, `LLMTracesTab`, etc.) stay put — only the rail is migrated.
- `apps/frontend/src/app/admin/users/page.tsx` — `<table>` → `<DataTable>`. Role Select + active toggle move into a `rowActions` cell render.
- `apps/frontend/src/app/admin/courses/page.tsx` — `<table>` → `<DataTable>`. Featured Switch on first row was moved to filter row in Loop 13; in-table per-row toggle stays in a column.
- `apps/frontend/src/app/admin/audit/page.tsx` — `<table>` → `<DataTable>`. Cursor pagination wraps the table.
- `apps/frontend/src/app/studio/[id]/page.tsx` — add `<Breadcrumb>` above the course title.
- `apps/frontend/src/components/admin/evals/ScoreBadge.tsx` — `text-emerald-300 / text-amber-300 / text-rose-300` → `text-success / text-warning / text-destructive`.
- `apps/frontend/src/app/admin/evals/[suite]/[reportId]/page.tsx` — `border-amber-700/40 text-amber-300` + `border-rose-700/40 text-rose-300` → semantic borders + text.
- `apps/frontend/src/styles/globals.css` — `data-wb-tabs-trigger` animation rule if needed (Radix Tabs uses static state changes; likely no animation, just border-bottom transitions).
- `apps/frontend/src/lib/i18n/messages/{en,ar}.ts` — new keys for Breadcrumb aria-labels + DataTable shared strings.
- `apps/frontend/package.json` + `pnpm-lock.yaml`.
- `docs/redesign/STATUS.md`, `CHANGELOG.md`.

## Tabs primitive

Radix Tabs. Trigger styled with the existing audit-flagged convention: `border-b-2 border-transparent data-[state=active]:border-primary` for the active marker, font-mono uppercase for the trigger text. Replaces the hand-rolled patterns verbatim.

## Breadcrumb primitive

Custom — no Radix needed. Semantic `<nav aria-label>` + `<ol>` + `<li>` markup. ChevronRight separator (lucide). `BreadcrumbPage` is the current page (non-interactive `<span aria-current="page">`); `BreadcrumbLink` is `<Link asChild>` for Next.js client nav.

## DataTable primitive

- Built on plain `<table>` + Tailwind. No tanstack-table dependency — the minimum API per spec doesn't justify it.
- Columns rendered to `<thead>` with mono-uppercase header cell styling. Sortable columns show a chevron indicator on hover; active sort shows filled indicator.
- Rows render via `rows.map((r) => <tr key={rowKey(r)}>{columns.map(c => <td>{c.cell(r)}</td>)}</tr>)`.
- Loading state: 5 skeleton rows.
- Empty state: consumer-provided `emptyState` React node (defaults to a minimal "No data" if omitted).

## Migration patterns

### Tab rail → Tabs

Before (`/studio` example):
```tsx
<div role="tablist" className="border-b border-border">
  {tabs.map(t => (
    <button
      role="tab"
      aria-selected={tab === t.id}
      onClick={() => setTab(t.id)}
      className={cn("...border-b-2", tab === t.id ? "border-primary" : "border-transparent")}
    >
      {t.label}
    </button>
  ))}
</div>
```

After:
```tsx
<Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
  <TabsList>
    {tabs.map(t => (
      <TabsTrigger key={t.id} value={t.id}>{t.label}</TabsTrigger>
    ))}
  </TabsList>
</Tabs>
```

### Table → DataTable

Before (admin/users excerpt):
```tsx
<table className="w-full text-sm">
  <thead className="border-b border-border bg-muted/40 font-mono text-xs uppercase tracking-wider text-muted-foreground">
    <tr>
      <th>Name</th>...
    </tr>
  </thead>
  <tbody>
    {users.map(u => (
      <tr key={u.id}>
        <td>{u.full_name}</td>...
      </tr>
    ))}
  </tbody>
</table>
```

After:
```tsx
<DataTable
  columns={USERS_COLUMNS}
  rows={users}
  rowKey={(u) => u.id}
  loading={usersQ.isLoading}
  emptyState={<EmptyState title={t("adminUsers.empty")} />}
/>
```

Where `USERS_COLUMNS` is a `Column<AdminUser>[]` defined at file top.

## Tests

- `tabs.test.tsx` (~110 LoC): trigger renders, click switches active state, content visibility tied to value, role="tablist" + role="tab" + role="tabpanel" semantics, keyboard arrow-key delegated to Radix.
- `breadcrumb.test.tsx` (~80 LoC): nav role with aria-label, BreadcrumbPage gets aria-current="page", BreadcrumbLink renders as anchor with href.
- `data-table.test.tsx` (~180 LoC): columns render headers, rows render via cell fn, empty state shown when rows empty + not loading, loading shows skeleton rows, sortable column shows indicator, onSortChange fires.

## Risks

- **DataTable in /admin/courses already has 2 boolean toggles + 1 search.** The filter row + table get reorganized; search + featured-Switch stay above the table, per-row featured-toggle becomes a DataTable column. Mitigation: tests still query by accessible role.
- **Studio tab rail uses Next.js searchParams for tab state.** Existing behavior must be preserved — the Tabs primitive is just a presentational swap; URL sync stays in the consumer.
- **Admin/audit pagination is cursor-based.** DataTable doesn't own pagination state; the page wraps the DataTable with cursor controls outside.
- **i18n keys for new strings** (Breadcrumb aria-label, "No data" empty default): ~3 new keys per language. Parity test will fail if any one is missing.
