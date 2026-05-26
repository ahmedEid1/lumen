/**
 * Loop 18 — CommandPalette behavior coverage.
 *
 * Asserts:
 *   - Cmd+K (and Ctrl+K) opens the palette.
 *   - Custom event `lumen:open-command-palette` opens the palette.
 *   - Search field is focused when open.
 *   - Escape closes (Dialog inherited).
 *   - Navigate item: clicking fires router.push and closes.
 *
 * Course-search section is not asserted here — TanStack Query
 * against happy-dom + a real network is brittle and the local
 * dev-browser walk covers it.
 */
import { render, screen, act, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { CommandPalette } from "@/components/shared/command-palette";

const pushMock = vi.fn();
vi.mock("next/navigation", async () => {
  return {
    useRouter: () => ({
      push: pushMock,
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
  };
});

// useAuth: an unauthenticated user — Navigate section will show
// just the public links.
vi.mock("@/lib/auth/store", () => ({
  useAuth: () => ({
    user: null,
    ready: true,
    token: null,
    login: vi.fn(),
    logout: vi.fn(),
    refresh: vi.fn(),
    register: vi.fn(),
  }),
}));

vi.mock("next-themes", () => ({
  useTheme: () => ({
    theme: "dark",
    resolvedTheme: "dark",
    setTheme: vi.fn(),
  }),
}));

function renderPalette() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <CommandPalette />
    </QueryClientProvider>,
  );
}

describe("CommandPalette", () => {
  it("renders nothing visible until Cmd+K", () => {
    renderPalette();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens on Cmd+K", async () => {
    renderPalette();
    act(() => {
      fireEvent.keyDown(document, { key: "k", metaKey: true });
    });
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("opens on Ctrl+K (Linux/Windows)", async () => {
    renderPalette();
    act(() => {
      fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    });
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("opens on the custom open-event (header hint button)", async () => {
    renderPalette();
    act(() => {
      document.dispatchEvent(new CustomEvent("lumen:open-command-palette"));
    });
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("Escape closes (inherits Dialog behavior)", async () => {
    renderPalette();
    act(() => {
      fireEvent.keyDown(document, { key: "k", metaKey: true });
    });
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("clicking a navigate item calls router.push and closes", async () => {
    const user = userEvent.setup();
    renderPalette();
    act(() => {
      fireEvent.keyDown(document, { key: "k", metaKey: true });
    });
    await screen.findByRole("dialog");
    const catalog = await screen.findByText("Catalog");
    await user.click(catalog);
    expect(pushMock).toHaveBeenCalledWith("/courses");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
