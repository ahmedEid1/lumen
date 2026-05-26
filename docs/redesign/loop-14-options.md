# Loop 14 — options

## Option A — Tabs primitive only (~400 LoC)

Just Tabs + 2 migrations. Defer DataTable + Breadcrumb to separate loops.

- **Pros:** smallest diff, easiest review.
- **Cons:** Doesn't match the new "team-day" iteration size the user asked for. Splits a coherent Foundation E tier across 3 loops needlessly.

## Option B — Full Foundation E (CHOSEN)

Tabs + Breadcrumb + DataTable + 5 migrations + token-drift cleanup. ~1500-1800 LoC.

- **Pros:** closes a tier in one push. Matches the requested iteration size. Each new primitive ships with at least one real consumer.
- **Cons:** larger review surface. Mitigated by mechanical similarity of the 3 DataTable migrations (same shape, different columns) and the 2 Tabs migrations (same shape, different content).

## Option C — Foundation E + Codex rescue #4 (~1800-2200 LoC)

Same as B but adds a Codex rescue at the end.

- **Pros:** if the larger surface introduces regressions, catching them in-loop is cheaper.
- **Cons:** Codex cadence anchors at Loop 15. Triggering it a loop early shifts the rhythm; Loop 17 / 20 would also need to shift. Better to keep the cadence and let Loop 15's natural rescue cover Loops 13-15.

## Decision

**Option B.** Closes Foundation E as a coherent tier. Stays under the 2500 LoC hard ceiling.

## DataTable API sketch

```tsx
type Column<T> = {
  id: string;
  header: React.ReactNode;
  cell: (row: T) => React.ReactNode;
  sortable?: boolean;
  className?: string;
};

type DataTableProps<T> = {
  columns: Column<T>[];
  rows: T[];
  loading?: boolean;            // shows Skeleton rows
  emptyState?: React.ReactNode; // shown when !loading && rows.length === 0
  sortBy?: { id: string; dir: "asc" | "desc" };
  onSortChange?: (next: { id: string; dir: "asc" | "desc" } | null) => void;
  rowKey: (row: T) => string;
};

// usage:
<DataTable
  columns={[
    { id: "name", header: "Name", cell: (u) => u.full_name, sortable: true },
    { id: "email", header: "Email", cell: (u) => <span className="font-mono">{u.email}</span> },
    { id: "actions", header: "", cell: (u) => <Actions row={u} />, className: "text-end" },
  ]}
  rows={users}
  rowKey={(u) => u.id}
  loading={usersQ.isLoading}
  emptyState={<EmptyState title="No users" />}
/>
```

Server-side sort is the consumer's responsibility — the table only emits sort intent + renders the indicator chevron.

## Breadcrumb API sketch

```tsx
<Breadcrumb>
  <BreadcrumbList>
    <BreadcrumbItem>
      <BreadcrumbLink href="/studio">Studio</BreadcrumbLink>
    </BreadcrumbItem>
    <BreadcrumbSeparator />
    <BreadcrumbItem>
      <BreadcrumbPage>{course.title}</BreadcrumbPage>
    </BreadcrumbItem>
  </BreadcrumbList>
</Breadcrumb>
```

Tabs follow Radix's standard API; no surprises.
