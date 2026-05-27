/**
 * L20.6 — useDemoQuestions() hook.
 *
 * The L22 chip rail consumes this. Asserts the query key cache-keys
 * by course slug + the data shape exposes the canonical id.
 */
import { describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type * as Endpoints from "@/lib/api/endpoints";

vi.mock("@/lib/api/endpoints", async () => {
  const actual = await vi.importActual<typeof Endpoints>("@/lib/api/endpoints");
  // FIXTURE is defined inside the factory because vi.mock is hoisted
  // above any top-level `const` declarations — accessing one from the
  // factory would throw `Cannot access 'X' before initialization`.
  const FIXTURE = {
    version: "2026-05-27.v1",
    canonical_id: "ts-variance-canonical",
    questions: [
      {
        id: "ts-variance-canonical",
        category: "retriever-code-runner" as const,
        prompt: "canonical question text",
        expected_tools: ["retriever", "code_runner"],
        course_slug: "typescript-variance",
        canonical: true,
      },
    ],
  };
  return {
    ...actual,
    DemoQuestionsApi: {
      list: vi.fn().mockResolvedValue(FIXTURE),
    },
  };
});

import { useDemoQuestions } from "@/lib/demo-questions";

function wrap() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const Provider = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  Provider.displayName = "DemoQuestionsTestProvider";
  return Provider;
}

describe("useDemoQuestions", () => {
  it("returns the library + canonical id once resolved", async () => {
    const { result } = renderHook(() => useDemoQuestions("typescript-variance"), {
      wrapper: wrap(),
    });
    await waitFor(() => {
      expect(result.current.data?.canonical_id).toBe("ts-variance-canonical");
      expect(result.current.data?.questions).toHaveLength(1);
    });
  });
});
