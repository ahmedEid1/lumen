"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

/**
 * TraceTree — render an agent-trace flat list as a collapsible tree.
 *
 * The backend returns the rows flat (ordered created_at ASC,
 * step_index ASC) and we build the tree client-side off
 * ``parent_trace_id``. We bias toward CSS for the tree connectors:
 * each child's left padding + a left border draws the vertical
 * line, and a horizontal pseudo-element gives the elbow.
 *
 * Each node is collapsible. Open by default — admins want to see
 * the whole tree on first load; collapsing is only useful for
 * very deep critic loops.
 */

export type TraceStep = {
  trace_id: string;
  parent_trace_id: string | null;
  parent_call_id: string | null;
  step: string;
  step_index: number;
  payload: Record<string, unknown>;
  duration_ms: number;
  status: string;
  created_at: string;
};

type TreeNode = TraceStep & { children: TreeNode[] };

function buildTree(steps: TraceStep[]): TreeNode[] {
  const byId = new Map<string, TreeNode>();
  for (const s of steps) byId.set(s.trace_id, { ...s, children: [] });
  const roots: TreeNode[] = [];
  for (const node of byId.values()) {
    if (node.parent_trace_id && byId.has(node.parent_trace_id)) {
      byId.get(node.parent_trace_id)!.children.push(node);
    } else {
      roots.push(node);
    }
  }
  // Sort siblings by step_index, then created_at (stable).
  const sortChildren = (list: TreeNode[]) => {
    list.sort((a, b) => {
      if (a.step_index !== b.step_index) return a.step_index - b.step_index;
      return a.created_at.localeCompare(b.created_at);
    });
    for (const n of list) sortChildren(n.children);
  };
  sortChildren(roots);
  return roots;
}

export function TraceTree({ steps }: { steps: TraceStep[] }) {
  if (steps.length === 0) {
    return (
      <p className="font-mono text-xs text-muted-foreground">
        No agent steps recorded for this call. The multi-agent
        tutor (I2) and self-critique authoring (I3) write into
        this tree; until they ship, plain single-shot LLM calls
        produce one ``llm_calls`` row with no associated trace.
      </p>
    );
  }
  const tree = buildTree(steps);
  return (
    <ol className="flex flex-col gap-1">
      {tree.map((node) => (
        <TraceNode key={node.trace_id} node={node} depth={0} />
      ))}
    </ol>
  );
}

function TraceNode({ node, depth }: { node: TreeNode; depth: number }) {
  const [open, setOpen] = useState(true);
  const hasChildren = node.children.length > 0;
  const isError = node.status === "error";

  return (
    <li
      className="font-mono text-xs"
      style={{ paddingInlineStart: depth === 0 ? 0 : depth * 16 }}
    >
      <div
        className={
          "group flex items-baseline gap-2 border-l-2 px-2 py-1.5 " +
          (depth === 0 ? "border-transparent" : "border-border")
        }
      >
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          disabled={!hasChildren}
          aria-label={open ? "Collapse step" : "Expand step"}
          className="shrink-0 text-muted-foreground transition-colors duration-[160ms] hover:text-foreground disabled:opacity-30"
        >
          {hasChildren ? (
            open ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )
          ) : (
            <span className="inline-block h-3 w-3" />
          )}
        </button>
        <span
          className={
            "rounded px-1.5 py-0.5 " +
            (isError
              ? "bg-destructive/15 text-destructive"
              : "bg-muted text-foreground")
          }
        >
          {node.step}
        </span>
        <span className="text-muted-foreground">
          #{node.step_index}
          {" · "}
          <span className="tabular-nums text-foreground">
            {node.duration_ms.toLocaleString()}
          </span>{" "}
          ms
        </span>
      </div>
      {open && (
        <>
          <PayloadView payload={node.payload} depth={depth} />
          {hasChildren && (
            <ol className="mt-1 flex flex-col gap-1">
              {node.children.map((child) => (
                <TraceNode
                  key={child.trace_id}
                  node={child}
                  depth={depth + 1}
                />
              ))}
            </ol>
          )}
        </>
      )}
    </li>
  );
}

function PayloadView({
  payload,
  depth,
}: {
  payload: Record<string, unknown>;
  depth: number;
}) {
  const entries = Object.entries(payload);
  if (entries.length === 0) return null;
  return (
    <dl
      className="ms-5 mt-1 flex flex-col gap-0.5 border-l-2 border-border ps-3 font-mono text-[10px]"
      style={{ marginInlineStart: depth === 0 ? 12 : depth * 16 + 12 }}
    >
      {entries.map(([k, v]) => (
        <div key={k} className="flex items-baseline gap-2">
          <dt className="shrink-0 uppercase tracking-wider text-muted-foreground">
            {k}
          </dt>
          <dd className="break-all text-foreground">{formatValue(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") {
    return v.length > 300 ? v.slice(0, 300) + "…" : v;
  }
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    const out = JSON.stringify(v);
    return out.length > 300 ? out.slice(0, 300) + "…" : out;
  } catch {
    return String(v);
  }
}
