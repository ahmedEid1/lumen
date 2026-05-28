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

    /**
     * L39 — connection lifecycle.
     *
     * Three failure modes the consumer needs to survive:
     *
     * 1. **Transient network error during streaming** — connection
     *    dropped mid-turn. We retry ONCE with the latest
     *    `Last-Event-ID` so the server replays only events the
     *    client missed. A second consecutive failure surfaces as
     *    a hard error (the orchestrator's probably dead at that
     *    point; further retries just burn CI).
     *
     * 2. **Trim detected (events TTL'd)** — the SSE endpoint
     *    emits `trim_detected` and closes. The reducer flips
     *    phase → "trim"; we then poll `/status` until terminal
     *    and synthesise a `turn_complete` / `turn_failed` event
     *    so the consumer reducer settles on a normal terminal
     *    phase.
     *
     * 3. **Hard error (auth / 404 / 503)** — `openSseStream`'s
     *    `onError` fires with a non-retryable message; we mark
     *    the snapshot failed without retry.
     */
    void runWithRecovery(turnId, token, controller.signal, store, () => cancelled);

    return () => {
      cancelled = true;
      controller.abort();
      // Aborting the fetch only closes the *client* connection — the
      // server keeps orchestrating the turn (burning LLM cost) and only
      // releases the reserved cost on natural termination or the 60s
      // sweep. If we leave while the turn is still in flight, tell the
      // server to abort it via DELETE so the reservation is released
      // now. `keepalive` lets the request outlive this unmount /
      // navigation (like a beacon); fire-and-forget — we're gone.
      const { phase } = store.getSnapshot();
      if (!TERMINAL_PHASES.includes(phase)) {
        void fetch(`/api/v1/tutor/turns/${encodeURIComponent(turnId)}`, {
          method: "DELETE",
          credentials: "include",
          keepalive: true,
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        }).catch(() => {
          /* best-effort: the sweep beat is the backstop if this fails */
        });
      }
    };
  }, [turnId, token, store]);

  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
}

export { TERMINAL_PHASES };


/**
 * L39 — stream-with-recovery driver. Lifted out of the hook body so
 * the retry + poll-fallback logic is unit-testable without React.
 *
 * Public for the tests under `tests/use-tutor-stream*.test.tsx`; not
 * part of the hook's external surface.
 */
async function runWithRecovery(
  turnId: string,
  token: string | null,
  signal: AbortSignal,
  store: TutorStreamStore,
  isCancelled: () => boolean,
): Promise<void> {
  const url = `/api/v1/tutor/turns/${encodeURIComponent(turnId)}/stream`;
  const statusUrl = `/api/v1/tutor/turns/${encodeURIComponent(turnId)}/status`;
  let attempts = 0;
  const MAX_ATTEMPTS = 2;

  while (attempts < MAX_ATTEMPTS) {
    attempts += 1;
    const lastEventId = store.getSnapshot().lastEventId;
    let hadError = false;

    await openSseStream({
      url,
      token,
      signal,
      lastEventId: lastEventId ?? undefined,
      onEvent: (ev) => {
        if (isCancelled()) return;
        store.apply(ev);
      },
      onError: (err) => {
        if (isCancelled()) return;
        hadError = true;
        // Auth / 404 / 503 errors don't get a retry — they're
        // permanent for this turn. The SSE client's `onError`
        // shape doesn't carry a status code today, so we sniff
        // the message text for the common non-retryable cases.
        const msg = err.message || "";
        if (/401|403|404|503|disabled/i.test(msg)) {
          store.fail(msg || "tutor.stream_error");
          attempts = MAX_ATTEMPTS;
        }
      },
    });

    if (isCancelled()) return;

    // If the snapshot is terminal (turn_complete / turn_failed /
    // turn_aborted lands), we're done — no retry needed.
    const phase = store.getSnapshot().phase;
    if (phase === "complete" || phase === "failed") return;

    // Trim detected → switch to polling /status until terminal.
    if (phase === "trim") {
      await pollUntilTerminal(statusUrl, token, signal, store, isCancelled);
      return;
    }

    // Stream closed without a terminal event AND without a hard
    // error code — most likely a transient network blip. Retry
    // once via the next iteration of this loop. `Last-Event-ID`
    // (from `store.snapshot.lastEventId`) makes the server replay
    // only what we missed.
    if (!hadError && attempts < MAX_ATTEMPTS) {
      // brief backoff so we don't slam a flapping server
      await new Promise((r) => setTimeout(r, 250 * attempts));
      continue;
    }

    if (hadError && attempts >= MAX_ATTEMPTS) {
      store.fail("tutor.stream_error");
      return;
    }
  }

  // L40 rescue (Codex P2): if both retries closed cleanly without
  // ever yielding a terminal event (proxy idle timeout, server
  // closed mid-synth), the snapshot was left in planning/tool/synth
  // forever. Mark it failed so the consumer's terminal-phase
  // listeners settle.
  if (!isCancelled()) {
    const phase = store.getSnapshot().phase;
    if (phase !== "complete" && phase !== "failed" && phase !== "trim") {
      store.fail("tutor.stream_eof");
    }
  }
}


async function pollUntilTerminal(
  statusUrl: string,
  token: string | null,
  signal: AbortSignal,
  store: TutorStreamStore,
  isCancelled: () => boolean,
): Promise<void> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  // 60s budget at 1s intervals — orchestrator typically completes
  // in under 30s, but cold-start retries can push past that.
  for (let i = 0; i < 60; i += 1) {
    if (isCancelled() || signal.aborted) return;
    // L40 rescue (Codex P2): per-request timeout. The outer abort
    // signal only fires on hook teardown, but a stuck fetch (slow
    // server, dropped TCP) could block one tick of the 60s budget
    // indefinitely → loop never advances, UI freezes in
    // "trim/polling" forever. Race the fetch against a 3s timeout
    // via a chained AbortController.
    const perRequestController = new AbortController();
    const composite = composeAbort(signal, perRequestController.signal);
    const timeoutHandle = setTimeout(() => perRequestController.abort(), 3000);
    try {
      const r = await fetch(statusUrl, { headers, signal: composite });
      if (r.ok) {
        const body: { status?: string; error_code?: string | null } = await r.json();
        if (body.status === "complete") {
          store.apply({ id: "poll", event: "turn_complete", data: "{}" });
          return;
        }
        if (body.status === "failed" || body.status === "aborted") {
          store.fail(body.error_code || `tutor.${body.status}`);
          return;
        }
      }
    } catch {
      // network blip / timeout — try again next tick
    } finally {
      clearTimeout(timeoutHandle);
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  // Budget exhausted; mark stale.
  store.fail("tutor.poll_timeout");
}


/**
 * L40 rescue helper — return an AbortSignal that fires when EITHER
 * input signal fires. The standard `AbortSignal.any([...])` exists
 * but isn't supported on older Safari versions Lumen still
 * targets; this polyfill is a few lines and avoids the dependency.
 */
function composeAbort(...signals: AbortSignal[]): AbortSignal {
  const controller = new AbortController();
  const trip = (s: AbortSignal) => {
    if (s.aborted) controller.abort(s.reason);
    s.addEventListener("abort", () => controller.abort(s.reason));
  };
  for (const s of signals) trip(s);
  return controller.signal;
}
