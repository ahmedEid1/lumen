/**
 * Block-tree types + serialization helpers for the lesson body.
 *
 * Storage shape is Tiptap / ProseMirror JSON — picked so the editor
 * (Tiptap, see `block-editor.tsx`) can read/write the structure
 * directly with zero serialization layer in between, and the
 * read-only renderer (`block-renderer.tsx`) can walk the same tree
 * without pulling in the Tiptap runtime. The wire payload stays
 * inside the existing `lesson.data` JSONB column under
 * `data.blocks`.
 *
 * Backwards compat: legacy lessons stored a free-form markdown
 * string in `data.body_markdown`. We don't ship a full markdown
 * parser — instead, on first edit, the legacy text is dropped into
 * a single paragraph block verbatim. The next save writes
 * `data.blocks` and the editor takes over from there.
 */

/* ---------------------------------------------------------------- */
/*  JSON shape                                                       */
/* ---------------------------------------------------------------- */

/**
 * Re-declared locally instead of imported from `@tiptap/core` so the
 * renderer + types stay importable from server components and tests
 * without dragging the Tiptap runtime into the bundle. The shape is
 * intentionally identical to Tiptap's `JSONContent`.
 */
export interface BlockNode {
  type?: string;
  attrs?: Record<string, unknown>;
  content?: BlockNode[];
  marks?: BlockMark[];
  text?: string;
  [key: string]: unknown;
}

export interface BlockMark {
  type: string;
  attrs?: Record<string, unknown>;
  [key: string]: unknown;
}

/** The top-level document a Tiptap editor reads and writes. */
export type BlockDoc = BlockNode & { type: "doc"; content: BlockNode[] };

/* ---------------------------------------------------------------- */
/*  Factories                                                        */
/* ---------------------------------------------------------------- */

/** A fresh, empty doc — one blank paragraph so the caret has something to land on. */
export function emptyDoc(): BlockDoc {
  return {
    type: "doc",
    content: [{ type: "paragraph" }],
  };
}

/**
 * Promote a legacy markdown string to a block doc.
 *
 * Deliberately NOT a markdown parser. The contract is:
 *   - empty / whitespace-only string → an empty doc
 *   - anything else → one paragraph block containing the string verbatim
 *
 * The user sees their old content unchanged; the next edit
 * round-trips through Tiptap and produces real block structure. A
 * proper markdown→blocks upgrade can come later as a one-shot
 * migration if it's ever worth the complexity.
 */
export function fromLegacyMarkdown(md: string | null | undefined): BlockDoc {
  const text = typeof md === "string" ? md : "";
  if (text.trim().length === 0) return emptyDoc();
  return {
    type: "doc",
    content: [
      {
        type: "paragraph",
        content: [{ type: "text", text }],
      },
    ],
  };
}

/**
 * Choose what to feed the editor / renderer for a `text` lesson.
 * Prefers the new `blocks` field; falls back to legacy `body_markdown`
 * / `body`. Centralised here so editor and player resolve identically.
 */
export function resolveTextLessonDoc(
  data: { blocks?: unknown; body_markdown?: unknown; body?: unknown } | null | undefined,
): BlockDoc {
  if (!data) return emptyDoc();
  if (isBlockDoc(data.blocks)) return data.blocks;
  // legacy support: `body_markdown` is the historical field name in
  // this codebase; `body` is what the rebuild spec used in writing.
  // Honour both so neither shape regresses.
  const legacy =
    typeof data.body_markdown === "string"
      ? data.body_markdown
      : typeof data.body === "string"
        ? data.body
        : "";
  return fromLegacyMarkdown(legacy);
}

/* ---------------------------------------------------------------- */
/*  Guards                                                           */
/* ---------------------------------------------------------------- */

export function isBlockDoc(value: unknown): value is BlockDoc {
  if (!value || typeof value !== "object") return false;
  const v = value as { type?: unknown; content?: unknown };
  return v.type === "doc" && Array.isArray(v.content);
}
