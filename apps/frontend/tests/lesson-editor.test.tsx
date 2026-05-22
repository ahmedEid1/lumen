import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LessonEditor } from "@/components/lesson/lesson-editor";
import * as endpoints from "@/lib/api/endpoints";
import type { LessonOut } from "@/lib/api/types";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

// Tiptap drives the block editor — it pulls ProseMirror into the
// page and exercises DOM Selection / Range APIs that happy-dom
// doesn't implement. We swap the block editor for a stub so this
// test stays focused on the lesson-editor wiring (title / preview
// / save), not the editor's own behaviour. There's a dedicated
// block-editor.test.tsx for that.
vi.mock("@/components/lesson/block-editor", () => ({
  BlockEditor: ({ value }: { value: unknown }) => (
    <div data-testid="block-editor" data-value={JSON.stringify(value)} />
  ),
}));

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
  // Legacy shape on the wire — the lesson editor promotes it to the
  // new `blocks` field on first save, exercising the
  // fromLegacyMarkdown path through normalizeData.
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
      <LessonEditor moduleId="m_1" lesson={TEXT_LESSON} onSaved={onSaved} />,
    );

    expect(screen.getByLabelText(/^Title$/i)).toHaveValue("Welcome");
    // The block editor's seeded `value` is the promoted form of
    // the legacy `body_markdown` — a single paragraph block.
    const editor = screen.getByTestId("block-editor");
    expect(editor.getAttribute("data-value")).toContain("Hello world");

    const user = userEvent.setup();
    await user.clear(screen.getByLabelText(/^Title$/i));
    await user.type(screen.getByLabelText(/^Title$/i), "Renamed");
    await user.click(screen.getByLabelText(/free preview/i));
    await user.click(screen.getByRole("button", { name: /save lesson/i }));

    await waitFor(() => {
      expect(patchSpy).toHaveBeenCalled();
    });
    const [lessonId, payload] = patchSpy.mock.calls[0] as [string, Record<string, unknown>];
    expect(lessonId).toBe("l_1");
    expect(payload.title).toBe("Renamed");
    expect(payload.is_preview).toBe(true);
    // Legacy `body_markdown` is promoted to a block-tree doc on save.
    const data = payload.data as { type: string; blocks: { type: string; content: unknown[] } };
    expect(data.type).toBe("text");
    expect(data.blocks.type).toBe("doc");
    expect(JSON.stringify(data.blocks)).toContain("Hello world");
    expect(onSaved).toHaveBeenCalled();
  });

  it("calls createLesson when no lesson is supplied", async () => {
    const onSaved = vi.fn();
    renderWithClient(
      <LessonEditor moduleId="m_1" newType="text" onSaved={onSaved} />,
    );

    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/^Title$/i), "Fresh");
    await user.click(screen.getByRole("button", { name: /save lesson/i }));

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalled();
    });
    const [moduleId, payload] = createSpy.mock.calls[0] as [string, Record<string, unknown>];
    expect(moduleId).toBe("m_1");
    expect(payload.title).toBe("Fresh");
    expect(payload.type).toBe("text");
    expect(payload.is_preview).toBe(false);
    const data = payload.data as { type: string; blocks: { type: string } };
    expect(data.type).toBe("text");
    // Empty new lesson — the block tree is an empty doc, not legacy markdown.
    expect(data.blocks.type).toBe("doc");
  });

  it("Delete invokes deleteLesson and onDeleted", async () => {
    const onDeleted = vi.fn();
    const onSaved = vi.fn();
    renderWithClient(
      <LessonEditor
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
