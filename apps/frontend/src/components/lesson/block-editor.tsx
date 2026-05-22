"use client";

import { useEffect } from "react";
import {
  BubbleMenu,
  EditorContent,
  useEditor,
  type Editor,
  type JSONContent,
} from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Link from "@tiptap/extension-link";
import Image from "@tiptap/extension-image";
import CodeBlockLowlight from "@tiptap/extension-code-block-lowlight";
import { createLowlight, common } from "lowlight";
import {
  Bold,
  Italic,
  Code,
  Link2,
  Heading2,
  List,
  ListOrdered,
  Quote,
  ImageIcon,
  Code2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { BlockDoc } from "@/lib/lesson/blocks";

/**
 * Notion-style block editor for `text` lessons.
 *
 * We picked Tiptap over rolling our own ProseMirror config or using
 * Editor.js / Lexical for three reasons: (1) JSON output is the
 * native data model so storing the doc in `lesson.data.blocks` is
 * a zero-translation pass-through, (2) the bundle stays modular —
 * the player never imports any of this, only the studio does,
 * (3) StarterKit ships paragraphs / headings / lists / quotes /
 * code / horizontal-rule out of the gate, so we only added link,
 * image, and lowlight-highlighted code blocks on top.
 *
 * The toolbar lives in a Tiptap BubbleMenu — it floats next to the
 * current selection. This is the Workbench take on Notion's "/
 * slash menu + selection bubble" pattern: no permanent toolbar
 * eating vertical space at the top of the editor, but rich
 * formatting is always one click away when the author actually
 * has text selected.
 *
 * `immediatelyRender: false` keeps Next.js App Router happy — the
 * editor only spins up on the client, no SSR hydration mismatch.
 */

type Props = {
  value: BlockDoc;
  onChange: (value: BlockDoc) => void;
  placeholder?: string;
};

// One lowlight registry, module-scoped, so multiple editor mounts
// (e.g. switching between two text lessons in the studio without a
// full unmount) share the registered languages rather than each
// rebuilding the syntax tables.
const lowlight = createLowlight(common);

export function BlockEditor({ value, onChange, placeholder }: Props) {
  const editor = useEditor({
    immediatelyRender: false,
    extensions: [
      // StarterKit bundles Document / Paragraph / Text / Bold /
      // Italic / Strike / Code / Heading / BulletList / OrderedList
      // / ListItem / Blockquote / HorizontalRule / HardBreak +
      // History. We disable its built-in codeBlock so the
      // lowlight-aware variant below can take over.
      StarterKit.configure({
        codeBlock: false,
      }),
      Link.configure({
        openOnClick: false,
        autolink: true,
        // Same rationale as the renderer: opener-isolate every link
        // since instructors paste arbitrary URLs.
        HTMLAttributes: { rel: "noopener noreferrer", target: "_blank" },
      }),
      Image.configure({
        // No base64 inlining — images go through the existing asset
        // upload pipeline (see `lesson-editor.tsx` for video/file
        // uploads) and only their resolved URLs end up in the doc.
        allowBase64: false,
      }),
      CodeBlockLowlight.configure({ lowlight }),
    ],
    content: value,
    onUpdate: ({ editor }) => {
      // Cast: Tiptap types `getJSON()` as JSONContent which is the
      // same shape as BlockDoc by construction (top-level type
      // is always "doc"). Centralising the cast here keeps every
      // consumer typed against our own BlockDoc.
      onChange(editor.getJSON() as BlockDoc);
    },
    editorProps: {
      attributes: {
        // `prose` matches the renderer so authoring time and
        // reading time look the same — no jarring repaint when
        // the lesson is published. `font-mono` only applies inside
        // <code>/<pre> via prose-code; we lean on the prose
        // utilities here rather than hand-writing rules.
        class:
          "prose prose-neutral max-w-none font-body dark:prose-invert prose-headings:font-display prose-code:font-mono min-h-[16rem] focus:outline-none px-4 py-3",
        // Native placeholder via data attribute — handled by
        // Tiptap's emptyNodeClass + the CSS below would be the
        // long-term answer, but for the v1 of the block editor we
        // keep it simple: a CSS placeholder via aria-placeholder
        // would interfere with screen readers, so we use a real
        // attribute the editor strips on first keystroke.
        ...(placeholder ? { "data-placeholder": placeholder } : {}),
      },
    },
  });

  // Reconcile external resets: if the parent swaps `value` to a
  // genuinely different doc (e.g. switching lessons in the studio
  // sidebar) we want the editor to pick it up. Same-reference / same
  // content updates are skipped to avoid clobbering the user's caret
  // mid-typing — the editor's own state is the source of truth
  // during interactive editing.
  useEffect(() => {
    if (!editor) return;
    const current = editor.getJSON();
    if (JSON.stringify(current) === JSON.stringify(value)) return;
    // `setContent(content, emitUpdate)` — false skips the onUpdate
    // re-entrant call so we don't bounce our own external value
    // back to the parent as a change.
    editor.commands.setContent(value, false);
  }, [editor, value]);

  if (!editor) {
    // Server-render placeholder. Matches the editor's eventual
    // chrome so there's no layout jump when the client mounts.
    return (
      <div className="surface min-h-[18rem]" aria-busy="true">
        <div className="border-b border-border px-4 py-2 font-mono text-xs uppercase tracking-wider text-muted-foreground">
          Editor
        </div>
        <div className="px-4 py-3 font-body text-sm text-muted-foreground">…</div>
      </div>
    );
  }

  return (
    <div className="surface">
      <BubbleMenu
        editor={editor}
        tippyOptions={{ duration: 80, placement: "top" }}
        className="flex items-center gap-0.5 rounded-md border border-border bg-background p-1 shadow-md"
      >
        <ToolbarButton
          active={editor.isActive("bold")}
          onClick={() => editor.chain().focus().toggleBold().run()}
          label="Bold (Cmd+B)"
        >
          <Bold className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton
          active={editor.isActive("italic")}
          onClick={() => editor.chain().focus().toggleItalic().run()}
          label="Italic (Cmd+I)"
        >
          <Italic className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton
          active={editor.isActive("code")}
          onClick={() => editor.chain().focus().toggleCode().run()}
          label="Inline code"
        >
          <Code className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton
          active={editor.isActive("link")}
          onClick={() => promptForLink(editor)}
          label="Link"
        >
          <Link2 className="h-3.5 w-3.5" />
        </ToolbarButton>
        <Divider />
        <ToolbarButton
          active={editor.isActive("heading", { level: 2 })}
          onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
          label="Heading"
        >
          <Heading2 className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton
          active={editor.isActive("bulletList")}
          onClick={() => editor.chain().focus().toggleBulletList().run()}
          label="Bulleted list"
        >
          <List className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton
          active={editor.isActive("orderedList")}
          onClick={() => editor.chain().focus().toggleOrderedList().run()}
          label="Numbered list"
        >
          <ListOrdered className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton
          active={editor.isActive("blockquote")}
          onClick={() => editor.chain().focus().toggleBlockquote().run()}
          label="Quote"
        >
          <Quote className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton
          active={editor.isActive("codeBlock")}
          onClick={() => editor.chain().focus().toggleCodeBlock().run()}
          label="Code block"
        >
          <Code2 className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton onClick={() => promptForImage(editor)} label="Image">
          <ImageIcon className="h-3.5 w-3.5" />
        </ToolbarButton>
      </BubbleMenu>
      <EditorContent editor={editor} />
    </div>
  );
}

function ToolbarButton({
  active,
  onClick,
  label,
  children,
}: {
  active?: boolean;
  onClick: () => void;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      aria-pressed={active || undefined}
      className={cn(
        "inline-flex h-7 w-7 items-center justify-center rounded-sm text-muted-foreground transition-colors duration-[160ms] hover:bg-muted hover:text-foreground",
        active && "bg-muted text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function Divider() {
  return <span aria-hidden="true" className="mx-0.5 h-4 w-px bg-border" />;
}

function promptForLink(editor: Editor) {
  // `window.prompt` is intentionally crude — a real modal would be
  // nicer but slash-menu-style URL entry is out of scope for the
  // first cut. The prompt covers the 95% case (paste a URL, press
  // enter) and screen-reader users get a native, accessible
  // dialog for free.
  const previous = editor.getAttributes("link").href as string | undefined;
  const url = window.prompt("URL", previous ?? "");
  if (url === null) return; // cancelled
  if (url === "") {
    editor.chain().focus().extendMarkRange("link").unsetLink().run();
    return;
  }
  editor.chain().focus().extendMarkRange("link").setLink({ href: url }).run();
}

function promptForImage(editor: Editor) {
  const url = window.prompt("Image URL");
  if (!url) return;
  editor.chain().focus().setImage({ src: url }).run();
}

// Re-export the Tiptap JSON type alias for callers that want the
// canonical name without depending on @tiptap/core directly.
export type { JSONContent };
