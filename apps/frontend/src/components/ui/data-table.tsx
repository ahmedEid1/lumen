"use client";

import * as React from "react";
import { ChevronDown, ChevronUp, ChevronsUpDown } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * Workbench DataTable.
 *
 * Minimum-viable API per AUDIT.md §2 (DataTable row): columns + rows
 * + optional pagination + optional rowActions + empty/loading slots.
 * No tanstack-table dependency — the API surface this loop ships
 * doesn't justify the runtime cost.
 *
 * Sort is intent-only: the column declares `sortable: true`, the
 * table renders a chevron indicator, and the consumer's
 * `onSortChange` handler decides how to apply the new sort
 * (typically server-side via a query param).
 *
 * Used by /admin/users, /admin/courses, /admin/audit (Loop 14
 * migrations) and earmarked for /admin/observability LLMTracesTab +
 * CeleryTab when those land in the observability charts loop.
 */

export type SortDir = "asc" | "desc";
export type SortState = { id: string; dir: SortDir };

export type Column<T> = {
  /** Stable id used as a key and as the sort identifier. */
  id: string;
  /** Header cell content — Workbench convention is mono-uppercase. */
  header: React.ReactNode;
  /** Cell render — receives the row. */
  cell: (row: T) => React.ReactNode;
  /** When true, the header shows a sort indicator + clicking it
   *  cycles asc → desc → unsorted via `onSortChange`. */
  sortable?: boolean;
  /** Extra classes for the cell (`<td>`) — not the header. */
  className?: string;
  /** Extra classes for the header (`<th>`) cell. */
  headerClassName?: string;
};

export type DataTableProps<T> = {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  loading?: boolean;
  /** Shown when not loading and rows is empty. Required for any
   *  table that can be empty — defaults to a minimal mono row. */
  emptyState?: React.ReactNode;
  /** Current sort, controlled. */
  sort?: SortState | null;
  /** Sort change handler. Null means unsorted. */
  onSortChange?: (next: SortState | null) => void;
  /** Optional caption — visible only to screen readers. */
  ariaLabel?: string;
};

function nextSort(cur: SortState | null | undefined, id: string): SortState | null {
  if (!cur || cur.id !== id) return { id, dir: "asc" };
  if (cur.dir === "asc") return { id, dir: "desc" };
  return null;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading,
  emptyState,
  sort,
  onSortChange,
  ariaLabel,
}: DataTableProps<T>) {
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table
        className="w-full border-collapse text-sm"
        aria-label={ariaLabel}
      >
        <thead className="border-b border-border bg-muted/40">
          <tr>
            {columns.map((c) => {
              const isSorted = sort?.id === c.id;
              return (
                <th
                  key={c.id}
                  scope="col"
                  className={cn(
                    "px-4 py-2.5 text-start font-mono text-[10px] font-medium uppercase tracking-wider text-muted-foreground",
                    c.headerClassName,
                  )}
                >
                  {c.sortable && onSortChange ? (
                    <button
                      type="button"
                      onClick={() => onSortChange(nextSort(sort, c.id))}
                      className={cn(
                        "inline-flex items-center gap-1 transition-colors duration-base hover:text-foreground",
                        isSorted && "text-foreground",
                      )}
                    >
                      <span>{c.header}</span>
                      {!isSorted && (
                        <ChevronsUpDown className="h-3 w-3 opacity-50" aria-hidden />
                      )}
                      {isSorted && sort?.dir === "asc" && (
                        <ChevronUp className="h-3 w-3 text-primary" aria-hidden />
                      )}
                      {isSorted && sort?.dir === "desc" && (
                        <ChevronDown className="h-3 w-3 text-primary" aria-hidden />
                      )}
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {loading && (
            <>
              {Array.from({ length: 5 }).map((_, i) => (
                <tr key={`skel-${i}`} className="border-b border-border/60 last:border-0">
                  {columns.map((c) => (
                    <td key={c.id} className={cn("px-4 py-3", c.className)}>
                      <Skeleton className="h-4 w-full max-w-32" />
                    </td>
                  ))}
                </tr>
              ))}
            </>
          )}
          {!loading &&
            rows.length > 0 &&
            rows.map((row) => (
              <tr
                key={rowKey(row)}
                className="border-b border-border/60 transition-colors duration-base last:border-0 hover:bg-muted/20"
              >
                {columns.map((c) => (
                  <td
                    key={c.id}
                    className={cn("px-4 py-3 align-middle", c.className)}
                  >
                    {c.cell(row)}
                  </td>
                ))}
              </tr>
            ))}
          {!loading && rows.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="px-4 py-12 text-center">
                {emptyState ?? (
                  <span className="font-body text-sm text-muted-foreground">
                    No data
                  </span>
                )}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
