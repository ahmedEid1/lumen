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

/**
 * Pull the legacy free-form markdown string off a `text` lesson's
 * data, if that's the shape it's stored in.
 *
 * Returns `null` when the lesson uses the newer structured `blocks`
 * shape (which `resolveTextLessonDoc` + `BlockRenderer` handle) or
 * when there's no legacy body at all. When it returns a string, that
 * string is raw markdown authored by an instructor and should be
 * rendered through `MarkdownBody` (react-markdown) — NOT dumped
 * verbatim. `fromLegacyMarkdown` is the old verbatim path and is kept
 * only as a fallback for the editor's promotion-on-first-edit flow.
 */
export function legacyMarkdownOf(
  data: { blocks?: unknown; body_markdown?: unknown; body?: unknown } | null | undefined,
): string | null {
  if (!data) return null;
  // Structured blocks win — that path is already formatted.
  if (isBlockDoc(data.blocks)) return null;
  const legacy =
    typeof data.body_markdown === "string"
      ? data.body_markdown
      : typeof data.body === "string"
        ? data.body
        : "";
  return legacy.trim().length > 0 ? legacy : null;
}

/* ---------------------------------------------------------------- */
/*  Serialization: block doc → markdown                              */
/* ---------------------------------------------------------------- */

/**
 * Serialize a block doc into a markdown string.
 *
 * Why this exists: the backend `text` lesson schema
 * (`TextLessonData`) requires a non-empty `body_markdown` — it's the
 * canonical text projection consumed by RAG chunking + Postgres
 * full-text search. The editor only ever wrote `data.blocks`, so
 * every Studio text-lesson save 422'd on the missing field. We derive
 * `body_markdown` from the block tree on save so both the structured
 * `blocks` (what the player reads) and the flat `body_markdown` (what
 * the AI/search read) stay in sync.
 *
 * Scope / lossiness — this is intentionally a *minimal* serializer
 * covering exactly the node + mark types the Tiptap config in
 * `block-editor.tsx` can produce (StarterKit + Link + Image +
 * CodeBlockLowlight). Known, accepted lossiness for v1:
 *   - nested lists flatten to a single indent level (Tiptap can nest
 *     but the indent depth isn't tracked here);
 *   - the `callout` node (renderer-only, not authorable in the
 *     editor) degrades to its inner blocks with no marker;
 *   - link `title`/`target` attrs are dropped (href is kept);
 *   - image `title` is dropped (alt + src kept).
 * It is NOT a round-trippable markdown ⇄ blocks bridge — `blocks`
 * remains the source of truth; this projection is write-only and
 * exists to satisfy the search/RAG contract.
 */
export function blocksToMarkdown(doc: BlockDoc | null | undefined): string {
  if (!doc || !Array.isArray(doc.content)) return "";
  const out = doc.content.map((node) => blockToMarkdown(node)).filter((s) => s.length > 0);
  // Blank line between top-level blocks is the markdown paragraph
  // separator; collapse the trailing whitespace so we don't ship a
  // doc that's all newlines.
  return out.join("\n\n").trim();
}

function blockToMarkdown(node: BlockNode): string {
  switch (node.type) {
    case "paragraph":
      return inlineToMarkdown(node.content);
    case "heading": {
      const raw = Number((node.attrs as { level?: unknown } | undefined)?.level ?? 2);
      const level = Math.min(6, Math.max(1, Number.isFinite(raw) ? raw : 2)) | 0;
      return `${"#".repeat(level)} ${inlineToMarkdown(node.content)}`;
    }
    case "bulletList":
      return (node.content ?? [])
        .map((li) => `- ${listItemToMarkdown(li)}`)
        .join("\n");
    case "orderedList":
      return (node.content ?? [])
        .map((li, i) => `${i + 1}. ${listItemToMarkdown(li)}`)
        .join("\n");
    case "blockquote":
      return (node.content ?? [])
        .map((child) => blockToMarkdown(child))
        .filter((s) => s.length > 0)
        .join("\n\n")
        .split("\n")
        .map((line) => `> ${line}`)
        .join("\n");
    case "codeBlock": {
      const lang = (node.attrs as { language?: unknown } | undefined)?.language;
      const fence = typeof lang === "string" ? lang : "";
      return `\`\`\`${fence}\n${textOf(node.content)}\n\`\`\``;
    }
    case "horizontalRule":
      return "---";
    case "image": {
      const attrs = (node.attrs ?? {}) as { src?: unknown; alt?: unknown };
      if (typeof attrs.src !== "string" || attrs.src.length === 0) return "";
      const alt = typeof attrs.alt === "string" ? attrs.alt : "";
      return `![${alt}](${attrs.src})`;
    }
    case "hardBreak":
      return "";
    case "text":
      return inlineToMarkdown([node]);
    default:
      // Unknown / non-authorable block (e.g. renderer-only `callout`):
      // emit its children so we never silently drop content from the
      // search projection.
      if (Array.isArray(node.content)) {
        return node.content
          .map((child) => blockToMarkdown(child))
          .filter((s) => s.length > 0)
          .join("\n\n");
      }
      return "";
  }
}

/** A list item holds block children; collapse them onto one line item. */
function listItemToMarkdown(node: BlockNode): string {
  return (node.content ?? [])
    .map((child) => blockToMarkdown(child))
    .filter((s) => s.length > 0)
    .join(" ");
}

/** Render inline children (text nodes + marks, hard breaks) to markdown. */
function inlineToMarkdown(children: BlockNode[] | undefined): string {
  if (!children) return "";
  return children
    .map((child) => {
      if (child.type === "hardBreak") return "\n";
      if (child.type === "text") return textWithMarks(child);
      // A nested inline-ish block (rare) — fall back to its plain text.
      return textOf(child.content);
    })
    .join("");
}

function textWithMarks(node: BlockNode): string {
  let text = node.text ?? "";
  const marks = (node.marks ?? []) as BlockMark[];
  // Apply marks inside-out. Order is commutative for the wrappers we
  // emit, so the result is stable regardless of mark ordering.
  for (const mark of marks) {
    switch (mark.type) {
      case "bold":
        text = `**${text}**`;
        break;
      case "italic":
        text = `*${text}*`;
        break;
      case "code":
        text = `\`${text}\``;
        break;
      case "strike":
        text = `~~${text}~~`;
        break;
      case "link": {
        const attrs = (mark.attrs ?? {}) as { href?: unknown };
        const href = typeof attrs.href === "string" ? attrs.href : "";
        text = `[${text}](${href})`;
        break;
      }
      // `underline` has no markdown equivalent — emit the text plain
      // (matches the renderer treating it as a soft style).
      default:
        break;
    }
  }
  return text;
}

/** Flatten a node's text descendants to a single plain string. */
function textOf(children: BlockNode[] | undefined): string {
  if (!children) return "";
  return children.map((c) => (c.type === "text" ? (c.text ?? "") : textOf(c.content))).join("");
}

/* ---------------------------------------------------------------- */
/*  Guards                                                           */
/* ---------------------------------------------------------------- */

export function isBlockDoc(value: unknown): value is BlockDoc {
  if (!value || typeof value !== "object") return false;
  const v = value as { type?: unknown; content?: unknown };
  return v.type === "doc" && Array.isArray(v.content);
}
