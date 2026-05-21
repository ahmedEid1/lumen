import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HeaderSearch } from "@/components/shared/header-search";

const pushMock = vi.fn();
let urlParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => urlParams,
}));

describe("HeaderSearch", () => {
  beforeEach(() => {
    pushMock.mockReset();
    urlParams = new URLSearchParams();
  });

  it("routes to /courses with the typed query", async () => {
    render(<HeaderSearch />);
    const input = screen.getByRole("searchbox", { name: /search courses/i });
    const user = userEvent.setup();
    await user.type(input, "fastapi");
    await user.keyboard("{Enter}");
    expect(pushMock).toHaveBeenCalledWith("/courses?q=fastapi");
  });

  it("trims whitespace and goes to /courses with no query when empty", async () => {
    render(<HeaderSearch />);
    const input = screen.getByRole("searchbox", { name: /search courses/i });
    const user = userEvent.setup();
    await user.type(input, "   ");
    await user.keyboard("{Enter}");
    expect(pushMock).toHaveBeenCalledWith("/courses");
  });

  it("seeds the input from URL ?q=", () => {
    urlParams = new URLSearchParams("q=python");
    render(<HeaderSearch />);
    const input = screen.getByRole("searchbox", { name: /search courses/i });
    expect(input).toHaveValue("python");
  });

  it("honors a custom target", async () => {
    render(<HeaderSearch target="/admin/courses" />);
    const input = screen.getByRole("searchbox", { name: /search courses/i });
    const user = userEvent.setup();
    await user.type(input, "ML");
    await user.keyboard("{Enter}");
    expect(pushMock).toHaveBeenCalledWith("/admin/courses?q=ML");
  });
});
