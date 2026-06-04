/**
 * Profile account-delete dialog (S6.11 / S6.8 endpoint, ADR-0030).
 *
 * The danger-zone delete is wired to `Users.deleteMe` (DELETE /api/v1/users/me)
 * behind a type-to-confirm dialog: the user must type the confirm word AND
 * supply their password before the destructive button arms. On success the
 * query cache is cleared, the session is torn down (logout), and the app
 * hard-redirects home.
 *
 * Spies on the `Users` endpoint object + auth store, mirroring
 * tests/byok-model-page.test.tsx.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { en } from "@/lib/i18n/messages/en";
import * as endpoints from "@/lib/api/endpoints";
import type { UserOut } from "@/lib/api/types";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const logoutMock = vi.fn(async () => {});
const authState: { user: UserOut | null; ready: boolean } = {
  user: {
    id: "u1",
    full_name: "Test User",
    avatar_url: null,
    bio: null,
    role: "user",
    email: "u@lumen.test",
    is_active: true,
    email_verified_at: "2026-01-01T00:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
  },
  ready: true,
};
vi.mock("@/lib/auth/store", () => ({
  useAuth: () => ({
    ...authState,
    token: "tk",
    login: vi.fn(),
    register: vi.fn(),
    logout: logoutMock,
    refresh: vi.fn(),
  }),
}));

// Notification prefs fetch fires on mount; stub it so the page settles.
vi.mock("@/lib/api/endpoints", async () => {
  const actual = await vi.importActual<typeof endpoints>("@/lib/api/endpoints");
  return {
    ...actual,
    Me: {
      ...actual.Me,
      notificationPrefs: {
        get: vi.fn(async () => ({
          prefs: {
            enrolled: "in_app",
            lesson_available: "in_app",
            certificate_ready: "in_app",
            review_received: "in_app",
            chat_mention: "in_app",
            security: "in_app",
            discussion_reply: "in_app",
          },
        })),
        update: vi.fn(),
      },
    },
  };
});

import ProfilePage from "@/app/profile/page";

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const clearSpy = vi.spyOn(client, "clear");
  const ui = render(
    <QueryClientProvider client={client}>
      <ProfilePage />
    </QueryClientProvider>,
  );
  return { ...ui, clearSpy };
}

beforeEach(() => {
  logoutMock.mockClear();
});

afterEach(() => vi.restoreAllMocks());

describe("Profile delete dialog (S6.11)", () => {
  it("opens a type-to-confirm dialog; confirm is disabled until word + password", async () => {
    renderPage();
    await userEvent.click(
      await screen.findByRole("button", { name: en["profile.delete.button"] }),
    );
    const dialog = await screen.findByRole("dialog");
    const confirm = within(dialog).getByRole("button", {
      name: en["profile.delete.confirm"],
    });
    // Disabled with nothing typed.
    expect(confirm).toBeDisabled();

    // Typing only the password still leaves it disabled (word gate).
    await userEvent.type(
      within(dialog).getByLabelText(en["profile.delete.confirmPlaceholder"]),
      "hunter2hunter2",
    );
    expect(confirm).toBeDisabled();

    // Typing the confirm word arms the button.
    await userEvent.type(
      within(dialog).getByLabelText(/Type DELETE to confirm/),
      en["profile.delete.typeWord"],
    );
    expect(confirm).toBeEnabled();
  });

  it("confirming calls Users.deleteMe, clears the cache, and logs out", async () => {
    const del = vi
      .spyOn(endpoints.Users, "deleteMe")
      .mockResolvedValue({ ok: true });
    const { clearSpy } = renderPage();
    await userEvent.click(
      await screen.findByRole("button", { name: en["profile.delete.button"] }),
    );
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(
      within(dialog).getByLabelText(en["profile.delete.confirmPlaceholder"]),
      "hunter2hunter2",
    );
    await userEvent.type(
      within(dialog).getByLabelText(/Type DELETE to confirm/),
      en["profile.delete.typeWord"],
    );
    await userEvent.click(
      within(dialog).getByRole("button", { name: en["profile.delete.confirm"] }),
    );
    await waitFor(() => expect(del).toHaveBeenCalledWith("hunter2hunter2"));
    await waitFor(() => expect(clearSpy).toHaveBeenCalled());
    await waitFor(() => expect(logoutMock).toHaveBeenCalled());
  });
});
