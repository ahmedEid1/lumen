/**
 * L20.5 — useRuntimeFlags() hook.
 *
 * Asserts the hook returns DEFAULT_FLAGS while the request is in flight
 * and the server-supplied flags once the query resolves. The default
 * matters: a page that branches on `flags.tutor_streaming` must not
 * accidentally unlock the streaming UI between mount and the first
 * /api/v1/runtime-flags response.
 */
import { describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type * as Endpoints from "@/lib/api/endpoints";

vi.mock("@/lib/api/endpoints", async () => {
  const actual = await vi.importActual<typeof Endpoints>("@/lib/api/endpoints");
  return {
    ...actual,
    RuntimeFlagsApi: {
      get: vi.fn().mockResolvedValue({ tutor_streaming: true }),
    },
  };
});

import { useRuntimeFlags } from "@/lib/runtime-flags";

function wrap() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const Provider = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  Provider.displayName = "RuntimeFlagsTestProvider";
  return Provider;
}

describe("useRuntimeFlags", () => {
  it("returns DEFAULT_FLAGS (all-off) before the server response lands", () => {
    const { result } = renderHook(() => useRuntimeFlags(), {
      wrapper: wrap(),
    });
    // First render — query is still pending; we must NOT have lit up
    // streaming based on a missing response.
    expect(result.current.tutor_streaming).toBe(false);
  });

  it("hydrates the server-supplied flag value once the query resolves", async () => {
    const { result } = renderHook(() => useRuntimeFlags(), {
      wrapper: wrap(),
    });
    await waitFor(() => {
      expect(result.current.tutor_streaming).toBe(true);
    });
  });
});
