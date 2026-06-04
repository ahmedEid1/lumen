/**
 * Admin users page — grant/revoke-admin toggle + suspend/reinstate (S6.11 /
 * FR-ADMIN-01/03/08).
 *
 * S1 collapsed the role model to `{user, admin}`; S6 replaces the role
 * `<Select>` write path with a grant/revoke-admin toggle plus suspend/
 * reinstate, with the current admin's own-row controls disabled and the
 * last-admin invariant surfaced as a backend 422 the UI handles gracefully.
 *
 * These specs spy on the `Admin` endpoint object and render the real page,
 * mirroring tests/byok-model-page.test.tsx.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { en } from "@/lib/i18n/messages/en";
import * as endpoints from "@/lib/api/endpoints";
import type { UserAdminOut } from "@/lib/api/types";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("@/lib/auth/store", () => ({
  useAuth: () => ({
    user: { id: "me", email: "admin@lumen.test", full_name: "Me Admin", role: "admin" },
    token: "tk",
    ready: true,
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    refresh: vi.fn(),
  }),
}));

import AdminUsersPage from "@/app/admin/users/page";

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AdminUsersPage />
    </QueryClientProvider>,
  );
}

const SELF: UserAdminOut = {
  id: "me",
  email: "admin@lumen.test",
  full_name: "Me Admin",
  role: "admin",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  last_login_at: "2026-08-01T00:00:00Z",
};

const OTHER_USER: UserAdminOut = {
  id: "u2",
  email: "learner@lumen.test",
  full_name: "Learner Two",
  role: "user",
  is_active: true,
  created_at: "2026-02-01T00:00:00Z",
  last_login_at: null,
};

beforeEach(() => {
  vi.spyOn(endpoints.Admin, "users").mockResolvedValue([SELF, OTHER_USER]);
});

afterEach(() => vi.restoreAllMocks());

function rowFor(name: string) {
  const cell = screen.getByText(name);
  const row = cell.closest("tr");
  if (!row) throw new Error(`no row for ${name}`);
  return within(row as HTMLElement);
}

describe("AdminUsersPage toggle (S6.11)", () => {
  it("disables the current admin's own-row grant/revoke + suspend controls", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("Me Admin")).toBeInTheDocument());
    const me = rowFor("Me Admin");
    // Own-row revoke-admin + suspend are disabled (FR-ADMIN-01).
    expect(me.getByRole("button", { name: en["adminUsers.revokeAdmin"] })).toBeDisabled();
    expect(me.getByRole("button", { name: en["adminUsers.suspend"] })).toBeDisabled();
  });

  it("offers only user/admin role semantics (no legacy student/instructor)", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("Learner Two")).toBeInTheDocument());
    // The legacy role <Select> is gone — no student/instructor options anywhere.
    expect(screen.queryByText(en["adminUsers.role.student"])).toBeNull();
    expect(screen.queryByText(en["adminUsers.role.instructor"])).toBeNull();
  });

  it("grant admin requires a confirmation step before firing", async () => {
    const setAdmin = vi
      .spyOn(endpoints.Admin, "setAdmin")
      .mockResolvedValue({ ...OTHER_USER, role: "admin" });
    renderPage();
    await waitFor(() => expect(screen.getByText("Learner Two")).toBeInTheDocument());
    const other = rowFor("Learner Two");
    await userEvent.click(other.getByRole("button", { name: en["adminUsers.grantAdmin"] }));
    // Must not fire until confirmed.
    expect(setAdmin).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(en["adminUsers.confirmGrantTitle"])).toBeInTheDocument();
    await userEvent.click(within(dialog).getByTestId("confirm-user-action"));
    await waitFor(() => expect(setAdmin).toHaveBeenCalledWith("u2", true));
  });

  it("suspend requires confirmation then fires Admin.suspendUser", async () => {
    const suspend = vi
      .spyOn(endpoints.Admin, "suspendUser")
      .mockResolvedValue({ ...OTHER_USER, is_active: false });
    renderPage();
    await waitFor(() => expect(screen.getByText("Learner Two")).toBeInTheDocument());
    const other = rowFor("Learner Two");
    await userEvent.click(other.getByRole("button", { name: en["adminUsers.suspend"] }));
    expect(suspend).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(en["adminUsers.confirmSuspendTitle"])).toBeInTheDocument();
    await userEvent.click(within(dialog).getByTestId("confirm-user-action"));
    await waitFor(() =>
      expect(suspend).toHaveBeenCalledWith("u2", expect.objectContaining({ reason: expect.any(String) })),
    );
  });
});
