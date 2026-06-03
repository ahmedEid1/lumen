/**
 * F6 — /profile/model BYOK settings page gating coverage.
 *
 * The page (src/app/profile/model/page.tsx) gained two gate fixes:
 *  - it requires auth: when `ready && !user` it redirects to
 *    /login?next=/profile/model and renders nothing;
 *  - it gates the whole form on the server's `byok_enabled` flag (from
 *    GET /api/v1/llm-providers). With the flag off the registry reads
 *    {providers: [], byok_enabled: false} and the page shows an
 *    "unavailable" notice instead of a form whose submit can only 403.
 *
 * These specs render the real page against a real QueryClient with the
 * endpoints mocked, so the page's own isSuccess / enabled / byok_enabled
 * branching is exercised end-to-end.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { LLMProviderRegistry, UserOut } from "@/lib/api/types";

// Shared router spy: setup.ts mocks next/navigation with a fresh vi.fn()
// per call, so override it here with a stable replace spy we can assert on.
const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    replace: replaceMock,
    push: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/profile/model",
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}));

// Mutable auth state — flip per spec, mirrors studio-access.test.tsx.
const authState: { user: UserOut | null; token: string | null; ready: boolean } = {
  user: null,
  token: "test-token",
  ready: true,
};
vi.mock("@/lib/auth/store", () => ({ useAuth: () => authState }));

// Endpoints feed the two useQuery calls in the page.
const providersList = vi.fn<[], Promise<LLMProviderRegistry>>();
const credentialsList = vi.fn(async () => []);
vi.mock("@/lib/api/endpoints", () => ({
  LLMProviders: { list: () => providersList() },
  LLMCredentials: { list: () => credentialsList() },
}));

// Import after mocks are registered.
import ModelSettingsPage from "@/app/profile/model/page";

function mkUser(): UserOut {
  return {
    id: "u1",
    full_name: "U",
    avatar_url: null,
    bio: null,
    role: "user",
    email: "u@lumen.test",
    is_active: true,
    email_verified_at: null,
    created_at: "2026-01-01T00:00:00Z",
  };
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ModelSettingsPage />
    </QueryClientProvider>,
  );
}

describe("ModelSettingsPage (F6 BYOK gate)", () => {
  beforeEach(() => {
    replaceMock.mockClear();
    providersList.mockReset();
    credentialsList.mockClear();
    authState.user = mkUser();
    authState.token = "test-token";
    authState.ready = true;
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows the unavailable notice and NO form when byok_enabled is false", async () => {
    providersList.mockResolvedValue({ providers: [], byok_enabled: false });

    renderPage();

    // The flag-off notice (en string) appears once the query resolves.
    expect(
      await screen.findByText(
        "Bring-your-own-key is not available right now. Your tutor runs on the free platform model.",
      ),
    ).toBeInTheDocument();

    // No CredentialForm: its provider/model comboboxes must be absent.
    expect(screen.queryByRole("combobox", { name: "Provider" })).toBeNull();
    expect(screen.queryByRole("combobox", { name: "Model" })).toBeNull();
    // Anonymous-redirect must not have fired for an authed user.
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("renders the CredentialForm when providers are non-empty and byok_enabled is true", async () => {
    providersList.mockResolvedValue({
      providers: [
        { provider: "openai", display_name: "OpenAI", models: ["gpt-4o-mini", "gpt-4o"] },
      ],
      byok_enabled: true,
    });

    renderPage();

    // The form's provider/model pickers prove CredentialForm mounted.
    expect(await screen.findByRole("combobox", { name: "Provider" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Model" })).toBeInTheDocument();
    // The flag-off notice must NOT be present when enabled.
    expect(
      screen.queryByText(
        "Bring-your-own-key is not available right now. Your tutor runs on the free platform model.",
      ),
    ).toBeNull();
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("redirects to /login?next=/profile/model when ready && !user", async () => {
    authState.user = null;
    authState.ready = true;
    providersList.mockResolvedValue({ providers: [], byok_enabled: false });

    renderPage();

    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith("/login?next=/profile/model"),
    );
    // Anonymous render is null — no providers fetch fires (query disabled).
    expect(providersList).not.toHaveBeenCalled();
  });
});
