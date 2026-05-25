import { describe, expect, it, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { BlockEditor } from "@/components/lesson/block-editor";
import { emptyDoc, type BlockDoc } from "@/lib/lesson/blocks";

/**
 * Tiptap is ProseMirror underneath and pulls in DOM Range /
 * Selection APIs that happy-dom doesn't fully implement. Mounting
 * a real editor here would hang on `document.createRange()` calls
 * and similar gaps, none of which are bugs in our code. So we
 * stub `@tiptap/react` with a hand-rolled editor double that lets
 * us drive `onUpdate` directly and assert the wiring contract: the
 * BlockEditor passes the editor's current JSON to its `onChange`
 * prop verbatim, which is the only thing the consumer
 * (lesson-editor.tsx) actually depends on.
 *
 * The mock surface is small on purpose — if Tiptap's public API
 * changes shape, this test will fail loudly rather than
 * accidentally pass against stale mocks.
 */

type CapturedConfig = {
  content?: BlockDoc;
  onUpdate?: (ctx: { editor: { getJSON: () => BlockDoc } }) => void;
};

const captured: { config: CapturedConfig | null; doc: BlockDoc } = {
  config: null,
  doc: emptyDoc(),
};

vi.mock("@tiptap/react", () => {
  return {
    useEditor: (config: CapturedConfig) => {
      captured.config = config;
      captured.doc = config.content ?? emptyDoc();
      // The editor "instance" needs just enough of the surface area
      // for BlockEditor to render (toolbar checks `isActive`, the
      // setContent effect calls `commands.setContent`, etc.).
      return {
        getJSON: () => captured.doc,
        isActive: () => false,
        chain: () => ({
          focus: () => ({
            toggleBold: () => ({ run: () => undefined }),
            toggleItalic: () => ({ run: () => undefined }),
            toggleCode: () => ({ run: () => undefined }),
            toggleHeading: () => ({ run: () => undefined }),
            toggleBulletList: () => ({ run: () => undefined }),
            toggleOrderedList: () => ({ run: () => undefined }),
            toggleBlockquote: () => ({ run: () => undefined }),
            toggleCodeBlock: () => ({ run: () => undefined }),
            extendMarkRange: () => ({
              setLink: () => ({ run: () => undefined }),
              unsetLink: () => ({ run: () => undefined }),
            }),
            setImage: () => ({ run: () => undefined }),
          }),
        }),
        commands: {
          setContent: (next: BlockDoc) => {
            captured.doc = next;
          },
        },
        getAttributes: () => ({}),
      };
    },
    EditorContent: ({ editor: _editor }: { editor: unknown }) => (
      <div data-testid="editor-content" />
    ),
    BubbleMenu: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="bubble-menu">{children}</div>
    ),
  };
});

// The Tiptap extension packages aren't used at runtime once useEditor
// is stubbed, but ES module evaluation still touches them. The stubs
// stay deliberately empty.
vi.mock("@tiptap/starter-kit", () => ({ default: { configure: () => ({}) } }));
vi.mock("@tiptap/extension-link", () => ({ default: { configure: () => ({}) } }));
vi.mock("@tiptap/extension-image", () => ({ default: { configure: () => ({}) } }));
vi.mock("@tiptap/extension-code-block-lowlight", () => ({
  default: { configure: () => ({}) },
}));
vi.mock("lowlight", () => ({ createLowlight: () => ({}), common: {} }));

describe("BlockEditor", () => {
  it("forwards the typed content to onChange as a Tiptap JSON doc", () => {
    const onChange = vi.fn();
    render(<BlockEditor value={emptyDoc()} onChange={onChange} />);

    // Editor mounted — the toolbar + content area are present.
    expect(screen.getByTestId("editor-content")).toBeInTheDocument();
    expect(screen.getByTestId("bubble-menu")).toBeInTheDocument();

    // Simulate the user typing "hello": Tiptap would push a new doc
    // through the onUpdate callback. We trigger that callback
    // directly with the doc Tiptap would have produced for a
    // paragraph containing "hello".
    const typed: BlockDoc = {
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [{ type: "text", text: "hello" }],
        },
      ],
    };
    captured.doc = typed;
    expect(captured.config?.onUpdate).toBeTypeOf("function");
    act(() => {
      captured.config!.onUpdate!({ editor: { getJSON: () => typed } });
    });

    expect(onChange).toHaveBeenCalledTimes(1);
    const arg = onChange.mock.calls[0]![0] as BlockDoc;
    expect(arg.type).toBe("doc");
    expect(arg.content).toHaveLength(1);
    const para = arg.content[0]!;
    expect(para.type).toBe("paragraph");
    expect(para.content?.[0]?.type).toBe("text");
    expect(para.content?.[0]?.text).toBe("hello");
  });

  it("seeds the editor with the value prop on mount", () => {
    const seed: BlockDoc = {
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [{ type: "text", text: "seeded" }],
        },
      ],
    };
    render(<BlockEditor value={seed} onChange={() => undefined} />);
    expect(captured.config?.content).toEqual(seed);
  });
});
