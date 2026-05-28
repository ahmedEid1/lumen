/**
 * Regression: closing the tutor mid-turn must abort the server turn.
 *
 * `useTutorStream`'s cleanup used to only `controller.abort()` the
 * client fetch — the server kept orchestrating (burning LLM cost) and
 * only released the reserved cost on natural termination or the 60s
 * sweep. The `DELETE /api/v1/tutor/turns/{id}` endpoint existed but had
 * no caller (a backend↔UI parity orphan + a reservation leak). The hook
 * now fires that DELETE on unmount when the turn is still non-terminal.
 *
 * The initial snapshot phase is "idle" (non-terminal), so a mount→unmount
 * with the SSE stream stubbed to never resolve exercises the cancel path
 * deterministically.
 */
import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/auth/store", () => ({ useAuth: () => ({ token: "tok" }) }));
// Never resolves → the turn stays in its initial non-terminal "idle"
// phase for the duration of the (immediately unmounted) test.
vi.mock("@/lib/tutor/sse-client", () => ({
  openSseStream: vi.fn(() => new Promise<void>(() => {})),
}));

import { useTutorStream } from "@/lib/tutor/use-tutor-stream";

describe("useTutorStream — abort on close", () => {
  afterEach(() => vi.restoreAllMocks());

  it("DELETEs a non-terminal turn on unmount (releases the cost reservation)", () => {
    const fetchMock = vi.fn(() => Promise.resolve({ ok: true } as Response));
    vi.stubGlobal("fetch", fetchMock);

    const { unmount } = renderHook(() => useTutorStream("turn-abc"));
    unmount();

    const deleteCall = fetchMock.mock.calls.find(
      ([url, init]) =>
        typeof url === "string" &&
        url.includes("/api/v1/tutor/turns/turn-abc") &&
        (init as RequestInit | undefined)?.method === "DELETE",
    );
    expect(
      deleteCall,
      "expected a DELETE to abort the in-flight turn on unmount",
    ).toBeTruthy();
    // keepalive lets the request outlive the unmount / navigation.
    expect((deleteCall?.[1] as RequestInit | undefined)?.keepalive).toBe(true);
  });

  it("does NOT DELETE when there is no active turn (turnId null)", () => {
    const fetchMock = vi.fn(() => Promise.resolve({ ok: true } as Response));
    vi.stubGlobal("fetch", fetchMock);

    const { unmount } = renderHook(() => useTutorStream(null));
    unmount();

    expect(fetchMock).not.toHaveBeenCalled();
  });
});
