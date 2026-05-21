import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LessonEditor } from "@/components/lesson/lesson-editor";
import * as endpoints from "@/lib/api/endpoints";
import type { LessonOut } from "@/lib/api/types";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function renderWithClient(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const TEXT_LESSON: LessonOut = {
  id: "l_1",
  title: "Welcome",
  type: "text",
  order: 0,
  duration_seconds: 120,
  is_preview: false,
  data: { type: "text", body_markdown: "Hello world" },
};

describe("LessonEditor", () => {
  let patchSpy: ReturnType<typeof vi.spyOn>;
  let createSpy: ReturnType<typeof vi.spyOn>;
  let deleteSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    patchSpy = vi.spyOn(endpoints.Courses, "patchLesson").mockResolvedValue({} as never);
    createSpy = vi.spyOn(endpoints.Courses, "createLesson").mockResolvedValue({} as never);
    deleteSpy = vi.spyOn(endpoints.Courses, "deleteLesson").mockResolvedValue({ ok: true } as never);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("seeds the editor from the existing lesson and patches on save", async () => {
    const onSaved = vi.fn();
    renderWithClient(
      <LessonEditor courseId="c_1" moduleId="m_1" lesson={TEXT_LESSON} onSaved={onSaved} />,
    );

    expect(screen.getByLabelText(/^Title$/i)).toHaveValue("Welcome");
    expect(screen.getByLabelText(/Body \(Markdown\)/i)).toHaveValue("Hello world");

    const user = userEvent.setup();
    await user.clear(screen.getByLabelText(/^Title$/i));
    await user.type(screen.getByLabelText(/^Title$/i), "Renamed");
    await user.click(screen.getByLabelText(/free preview/i));
    await user.click(screen.getByRole("button", { name: /save lesson/i }));

    await waitFor(() => {
      expect(patchSpy).toHaveBeenCalledWith(
        "l_1",
        expect.objectContaining({
          title: "Renamed",
          is_preview: true,
          data: expect.objectContaining({ type: "text", body_markdown: "Hello world" }),
        }),
      );
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it("calls createLesson when no lesson is supplied", async () => {
    const onSaved = vi.fn();
    renderWithClient(
      <LessonEditor courseId="c_1" moduleId="m_1" newType="text" onSaved={onSaved} />,
    );

    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/^Title$/i), "Fresh");
    await user.type(screen.getByLabelText(/Body \(Markdown\)/i), "# Hi");
    await user.click(screen.getByRole("button", { name: /save lesson/i }));

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalledWith(
        "m_1",
        expect.objectContaining({
          title: "Fresh",
          type: "text",
          is_preview: false,
          data: expect.objectContaining({ type: "text", body_markdown: "# Hi" }),
        }),
      );
    });
  });

  it("Delete invokes deleteLesson and onDeleted", async () => {
    const onDeleted = vi.fn();
    const onSaved = vi.fn();
    renderWithClient(
      <LessonEditor
        courseId="c_1"
        moduleId="m_1"
        lesson={TEXT_LESSON}
        onSaved={onSaved}
        onDeleted={onDeleted}
      />,
    );

    await userEvent.setup().click(screen.getByRole("button", { name: /delete/i }));

    await waitFor(() => {
      expect(deleteSpy).toHaveBeenCalledWith("l_1");
    });
    await waitFor(() => expect(onDeleted).toHaveBeenCalled());
  });

  it("the quiz variant lets the instructor add a question", async () => {
    const onSaved = vi.fn();
    renderWithClient(
      <LessonEditor courseId="c_1" moduleId="m_1" newType="quiz" onSaved={onSaved} />,
    );

    // No questions yet — Add question is the only quiz action.
    const addQuestion = screen.getByRole("button", { name: /add question/i });
    await userEvent.setup().click(addQuestion);
    expect(screen.getByPlaceholderText(/^Prompt$/i)).toBeInTheDocument();
  });

  it("disables Save while there is no title", () => {
    renderWithClient(<LessonEditor courseId="c_1" moduleId="m_1" newType="text" onSaved={vi.fn()} />);
    expect(screen.getByRole("button", { name: /save lesson/i })).toBeDisabled();
  });
});
