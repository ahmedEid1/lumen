/**
 * S1.11 — Studio access gate inversion (ADR-0025).
 *
 * Before the collapse, a `student`-role session was redirected off /studio to
 * /dashboard. After: Studio is open to any authenticated user — only an
 * anonymous visitor is bounced to /login. These tests assert the redirect
 * behavior via a mocked router, without a full page render (the page pulls in
 * heavy modals + TanStack Query that are out of scope here).
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { UserOut } from "@/lib/api/types";

const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn(), prefetch: vi.fn() }),
}));

// Heavy children — stub to no-ops so the page renders in happy-dom.
vi.mock("@/components/onboarding/onboarding-tour", () => ({ OnboardingTour: () => null }));
vi.mock("@/components/studio/ai-outline-modal", () => ({ AIOutlineModal: () => null }));
vi.mock("@/components/studio/ingest-modal", () => ({ IngestModal: () => null }));
vi.mock("@/lib/api/endpoints", () => ({ Courses: { mine: vi.fn().mockResolvedValue([]) } }));
vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({ data: [], isLoading: false }),
}));
vi.mock("@/lib/i18n/provider", () => ({
  useT: () => (k: string) => k,
  useTN: () => (k: string) => k,
}));

const authState: { user: UserOut | null; ready: boolean } = { user: null, ready: true };
vi.mock("@/lib/auth/store", () => ({ useAuth: () => authState }));

function mkUser(role: UserOut["role"]): UserOut {
  return {
    id: "u1",
    full_name: "U",
    avatar_url: null,
    bio: null,
    role,
    email: "u@lumen.test",
    is_active: true,
    email_verified_at: null,
    created_at: "2026-01-01T00:00:00Z",
  };
}

// Import after mocks are registered.
import StudioPage from "@/app/studio/page";

describe("Studio access (S1.11)", () => {
  beforeEach(() => replaceMock.mockClear());

  it("does NOT redirect a regular user away from Studio", () => {
    authState.user = mkUser("user");
    authState.ready = true;
    render(<StudioPage />);
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("does NOT redirect an admin away from Studio", () => {
    authState.user = mkUser("admin");
    authState.ready = true;
    render(<StudioPage />);
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("redirects an anonymous visitor to login", () => {
    authState.user = null;
    authState.ready = true;
    render(<StudioPage />);
    expect(replaceMock).toHaveBeenCalledWith("/login?next=/studio");
  });

  // S7 — URL ingest is admin-only AND flag-gated server-side
  // (`can_ingest_url`). The button's visibility mirrors the identity half of
  // that rule so non-admins never see a control whose API 403s.
  it("hides the Import-from-URL button from a regular user", () => {
    authState.user = mkUser("user");
    authState.ready = true;
    render(<StudioPage />);
    expect(screen.queryByText("studio.import.button")).toBeNull();
  });

  it("shows the Import-from-URL button to an admin", () => {
    authState.user = mkUser("admin");
    authState.ready = true;
    render(<StudioPage />);
    expect(screen.getByText("studio.import.button")).toBeInTheDocument();
  });
});
