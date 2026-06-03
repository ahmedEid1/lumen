/**
 * S1.11 — the command palette shows "Studio" to any authenticated user.
 *
 * Before the collapse, the Studio nav item was gated to instructor/admin.
 * After: it's visible to every authenticated user (authoring is ungated). A
 * companion to command-palette.test.tsx (which covers the anonymous case).
 */
import { render, screen, act, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { CommandPalette } from "@/components/shared/command-palette";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/",
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}));

// A regular `user`-role session.
vi.mock("@/lib/auth/store", () => ({
  useAuth: () => ({
    user: {
      id: "u1",
      full_name: "U",
      avatar_url: null,
      bio: null,
      role: "user",
      email: "u@lumen.test",
      is_active: true,
      email_verified_at: null,
      created_at: "2026-01-01T00:00:00Z",
    },
    ready: true,
    token: "t",
    login: vi.fn(),
    logout: vi.fn(),
    refresh: vi.fn(),
    register: vi.fn(),
  }),
}));

vi.mock("next-themes", () => ({
  useTheme: () => ({ theme: "dark", resolvedTheme: "dark", setTheme: vi.fn() }),
}));

function renderPalette() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CommandPalette />
    </QueryClientProvider>,
  );
}

describe("CommandPalette — Studio visible to any user (S1.11)", () => {
  it("shows the Studio nav item for a regular user", async () => {
    renderPalette();
    act(() => {
      fireEvent.keyDown(document, { key: "k", metaKey: true });
    });
    await screen.findByRole("dialog");
    expect(await screen.findByText("Studio")).toBeInTheDocument();
    // Admin-only item must NOT appear for a non-admin user.
    expect(screen.queryByText("Admin")).not.toBeInTheDocument();
  });
});
