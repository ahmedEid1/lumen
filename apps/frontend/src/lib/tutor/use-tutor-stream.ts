"use client";

/**
 * L21b — `useTutorStream(turnId)` hook.
 *
 * Drives a single tutor turn end-to-end:
 *  1. Opens an SSE connection to `/api/v1/tutor/turns/{tid}/stream`.
 *  2. Parses each event into a reducer-driven snapshot.
 *  3. Returns the snapshot via `useSyncExternalStore` so React only
 *     re-renders when something the caller cares about changed.
 *
 * Snapshot shape (caller decides what to render):
 *   {
 *     phase: "planning" | "tool" | "synth" | "complete" | "failed" | "trim",
 *     tools: [{tool, status, latency_ms?, summary?}, ...],
 *     text: string,        // accumulated synth chunks
 *     error: string | null,
 *     turnCompleteData: { ... } | null,
 *   }
 *
 * The hook also re-uses the user's bearer token from `useAuth()`,
 * passing it to the SSE client as the `Authorization` header.
 */

import { useEffect, useRef, useSyncExternalStore } from "react";
import { useAuth } from "@/lib/auth/store";
import { openSseStream } from "./sse-client";
import type { SseEvent } from "./sse-parser";

export type TutorStreamPhase =
  | "idle"
  | "planning"
  | "tool"
  | "synth"
  | "complete"
  | "failed"
  | "trim";

export interface TutorTool {
  tool: string;
  status: "running" | "ok" | "error";
  latency_ms?: number;
  summary?: string;
}

export interface TutorStreamSnapshot {
  phase: TutorStreamPhase;
  tools: TutorTool[];
  text: string;
  error: string | null;
  turnCompleteData: Record<string, unknown> | null;
  lastEventId: string | null;
}

const INITIAL: TutorStreamSnapshot = {
  phase: "idle",
  tools: [],
  text: "",
  error: null,
  turnCompleteData: null,
  lastEventId: null,
};

/** Reducer over one parsed SSE event → next snapshot. */
function reduce(prev: TutorStreamSnapshot, ev: SseEvent): TutorStreamSnapshot {
  let data: Record<string, unknown> = {};
  try {
    data = ev.data ? (JSON.parse(ev.data) as Record<string, unknown>) : {};
  } catch {
    // Backend renders dicts in their repr() shape on the noop path,
    // which isn't valid JSON. The reducer keeps going — we don't
    // need the body for phase tracking, only for the synth chunks.
    data = { _raw: ev.data };
  }
  const next: TutorStreamSnapshot = {
    ...prev,
    lastEventId: ev.id ?? prev.lastEventId,
  };
  switch (ev.event) {
    case "planner_start":
      return { ...next, phase: "planning" };

    case "tool_call_start":
      return {
        ...next,
        phase: "tool",
        tools: [
          ...next.tools,
          { tool: String(data.tool ?? "unknown"), status: "running" },
        ],
      };

    case "tool_call_result": {
      const targetTool = String(data.tool ?? "");
      // Update the most-recent matching `running` tool in place.
      const tools = next.tools.map((t, i, arr) => {
        const isLastRunningMatch =
          t.tool === targetTool &&
          t.status === "running" &&
          arr.slice(i + 1).every((u) => u.status !== "running" || u.tool !== targetTool);
        if (!isLastRunningMatch) return t;
        return {
          tool: t.tool,
          status: (data.status === "ok" ? "ok" : "error") as TutorTool["status"],
          latency_ms: typeof data.latency_ms === "number" ? data.latency_ms : undefined,
          summary: typeof data.summary === "string" ? data.summary : undefined,
        };
      });
      return { ...next, tools };
    }

    case "synth_chunk":
      return {
        ...next,
        phase: "synth",
        text: next.text + (typeof data.delta === "string" ? data.delta : ""),
      };

    case "turn_complete":
      return { ...next, phase: "complete", turnCompleteData: data };

    case "turn_failed":
      return {
        ...next,
        phase: "failed",
        error: typeof data.error_code === "string" ? data.error_code : "tutor.unknown",
      };

    case "trim_detected":
      return { ...next, phase: "trim" };

    default:
      return next;
  }
}

class TutorStreamStore {
  private snapshot: TutorStreamSnapshot = INITIAL;
  private listeners = new Set<() => void>();

  getSnapshot = (): TutorStreamSnapshot => this.snapshot;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  apply(ev: SseEvent): void {
    const next = reduce(this.snapshot, ev);
    if (next === this.snapshot) return;
    this.snapshot = next;
    for (const l of this.listeners) l();
  }

  fail(error: string): void {
    this.snapshot = { ...this.snapshot, phase: "failed", error };
    for (const l of this.listeners) l();
  }

  reset(): void {
    this.snapshot = INITIAL;
    for (const l of this.listeners) l();
  }
}

const TERMINAL_PHASES: TutorStreamPhase[] = ["complete", "failed", "trim"];

/**
 * Subscribe to a tutor turn's SSE stream.
 *
 * Opens the connection on first mount (or when `turnId` changes),
 * tears down on unmount. The returned snapshot is stable across
 * re-renders if nothing changed (`useSyncExternalStore` semantics).
 *
 * For unauthenticated callers `turnId === null` is the safe shape
 * — the hook returns the INITIAL snapshot and doesn't open a
 * connection.
 */
export function useTutorStream(turnId: string | null): TutorStreamSnapshot {
  const storeRef = useRef<TutorStreamStore | null>(null);
  if (storeRef.current === null) {
    storeRef.current = new TutorStreamStore();
  }
  const store = storeRef.current;
  const { token } = useAuth();

  useEffect(() => {
    if (!turnId) {
      store.reset();
      return;
    }
    const controller = new AbortController();
    let cancelled = false;

    void (async () => {
      await openSseStream({
        url: `/api/v1/tutor/turns/${encodeURIComponent(turnId)}/stream`,
        token,
        signal: controller.signal,
        onEvent: (ev) => {
          if (cancelled) return;
          store.apply(ev);
        },
        onError: (err) => {
          if (cancelled) return;
          store.fail(err.message || "tutor.stream_error");
        },
      });
    })();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [turnId, token, store]);

  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
}

export { TERMINAL_PHASES };
