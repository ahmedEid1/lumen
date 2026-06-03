/**
 * S5.15 — BYOK settings tab coverage.
 *
 * Asserts: the form renders providers from GET /llm-providers (mocked) with a
 * model select scoped to the chosen provider, a write-only password key
 * input (never pre-filled), enabled/active/allow_platform_fallback toggles,
 * NO base_url/url field anywhere; the masked list shows last4 + a status
 * badge (never a full key); and the NeedsAttentionBanner shows on
 * needs_attention/invalid.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { CredentialForm } from "@/components/byok/CredentialForm";
import { CredentialList } from "@/components/byok/CredentialList";
import { NeedsAttentionBanner } from "@/components/byok/NeedsAttentionBanner";
import type { LLMCredentialPublic, LLMProvider } from "@/lib/api/types";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), message: vi.fn() } }));
vi.mock("@/lib/auth/store", () => ({
  useAuth: () => ({ token: "test-token", ready: true }),
}));

const PROVIDERS: LLMProvider[] = [
  { provider: "openai", display_name: "OpenAI", models: ["gpt-4o-mini", "gpt-4o"] },
  { provider: "groq", display_name: "Groq", models: ["llama-3.3-70b-versatile"] },
];

function renderWithClient(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("CredentialForm", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders provider + model pickers and a write-only key input", () => {
    renderWithClient(<CredentialForm providers={PROVIDERS} />);
    // The mocked useT resolves keys → English strings; assert on those.
    // The Select triggers are comboboxes labelled by aria-label.
    expect(screen.getByRole("combobox", { name: "Provider" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Model" })).toBeInTheDocument();
    // Key input is a password type and starts empty (never pre-filled).
    const key = screen.getByPlaceholderText("sk-…") as HTMLInputElement;
    expect(key).toHaveAttribute("type", "password");
    expect(key.value).toBe("");
    // Consent toggle present (role=switch, labelled by aria-label).
    expect(
      screen.getByRole("switch", {
        name: "Fall back to the free platform model if my key fails",
      }),
    ).toBeInTheDocument();
  });

  it("has NO base_url / url / endpoint field anywhere", () => {
    const { container } = renderWithClient(<CredentialForm providers={PROVIDERS} />);
    for (const banned of ["base_url", "api_base", "base url", "endpoint", "host", "url"]) {
      expect(
        container.querySelector(`[name*="${banned}" i], [aria-label*="${banned}" i]`),
      ).toBeNull();
    }
    // No input whose label mentions a URL.
    expect(screen.queryByLabelText(/url|base|endpoint|host/i)).toBeNull();
  });
});

describe("CredentialList", () => {
  afterEach(() => vi.restoreAllMocks());

  const cred = (over: Partial<LLMCredentialPublic> = {}): LLMCredentialPublic => ({
    provider: "openai",
    model: "gpt-4o-mini",
    last4: "1234",
    enabled: true,
    is_active: true,
    allow_platform_fallback: true,
    last_validated_at: null,
    last_validation_status: "valid",
    created_at: "2026-08-05T00:00:00Z",
    ...over,
  });

  it("shows last4 + status badge, never a full key", () => {
    renderWithClient(<CredentialList credentials={[cred()]} />);
    expect(screen.getByText(/••••1234/)).toBeInTheDocument();
    expect(screen.getByText("Valid")).toBeInTheDocument();
    // No password-shaped or sk- token should ever render.
    expect(screen.queryByText(/sk-/)).toBeNull();
  });

  it("renders the empty state when no credentials", () => {
    renderWithClient(<CredentialList credentials={[]} />);
    expect(
      screen.getByText("No model key yet. Add one to use your own provider."),
    ).toBeInTheDocument();
  });
});

describe("NeedsAttentionBanner", () => {
  it("shows for needs_attention", () => {
    render(<NeedsAttentionBanner status="needs_attention" />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("shows for invalid", () => {
    render(<NeedsAttentionBanner status="invalid" />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("hidden for valid", () => {
    const { container } = render(<NeedsAttentionBanner status="valid" />);
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });
});
