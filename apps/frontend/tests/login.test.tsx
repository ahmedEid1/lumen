import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import LoginPage from "@/app/login/page";

// useAuth pulls from a context provider that isn't mounted in tests.
// Stub it to a no-op so the form renders.
vi.mock("@/lib/auth/store", () => ({
  useAuth: () => ({
    user: null,
    token: null,
    ready: true,
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    refresh: vi.fn(),
  }),
}));

describe("LoginPage", () => {
  it("renders the email and password fields empty on mount (no prefilled dev creds)", async () => {
    render(<LoginPage />);
    const email = await screen.findByLabelText(/email/i);
    const password = await screen.findByLabelText(/password/i);
    expect(email).toHaveValue("");
    expect(password).toHaveValue("");
  });
});
