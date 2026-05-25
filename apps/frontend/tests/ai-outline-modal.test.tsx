import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AIOutlineModal } from "@/components/studio/ai-outline-modal";
import * as endpoints from "@/lib/api/endpoints";
import type { CourseOutline } from "@/lib/api/endpoints";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function renderWithClient(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const OUTLINE: CourseOutline = {
  title: "FastAPI Crash Course",
  overview: "A short overview.",
  modules: [
    {
      title: "Module One",
      lessons: [
        { title: "Intro lesson", type: "text" },
        { title: "Module quiz", type: "quiz" },
      ],
    },
    {
      title: "Module Two",
      lessons: [{ title: "Routing", type: "text" }],
    },
  ],
};

describe("AIOutlineModal", () => {
  let outlineSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    outlineSpy = vi.spyOn(endpoints.AI, "outline").mockResolvedValue(OUTLINE);
    // Subjects fetch is harmless in this test — Create is exercised
    // elsewhere; we only need it to not blow up.
    vi.spyOn(endpoints.Catalog, "subjects").mockResolvedValue([]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the brief form on mount", () => {
    renderWithClient(<AIOutlineModal onClose={() => {}} />);
    expect(screen.getByLabelText(/^Brief$/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /generate$/i })).toBeInTheDocument();
  });

  it("calls the outline endpoint and renders modules + lessons in the preview", async () => {
    renderWithClient(<AIOutlineModal onClose={() => {}} />);
    const user = userEvent.setup();
    await user.type(
      screen.getByLabelText(/^Brief$/i),
      "Teach FastAPI to beginners.",
    );
    await user.click(screen.getByRole("button", { name: /generate$/i }));

    await waitFor(() => {
      expect(outlineSpy).toHaveBeenCalledWith({
        brief: "Teach FastAPI to beginners.",
        target_modules: 4,
      });
    });

    // Module + lesson rows should render with their titles editable.
    const preview = await screen.findByTestId("ai-outline-preview");
    expect(preview).toBeInTheDocument();
    // Module title input
    expect(screen.getByDisplayValue("Module One")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Module Two")).toBeInTheDocument();
    // Lesson title inputs
    expect(screen.getByDisplayValue("Intro lesson")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Module quiz")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Routing")).toBeInTheDocument();
    // Course title pre-populated from the outline.
    expect(screen.getByDisplayValue("FastAPI Crash Course")).toBeInTheDocument();
  });

  it("Generate button is disabled until the brief is non-empty", async () => {
    renderWithClient(<AIOutlineModal onClose={() => {}} />);
    const btn = screen.getByRole("button", { name: /generate$/i });
    expect(btn).toBeDisabled();
    await userEvent.setup().type(screen.getByLabelText(/^Brief$/i), "anything");
    expect(btn).not.toBeDisabled();
  });
});
