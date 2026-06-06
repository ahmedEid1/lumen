import { describe, expect, it } from "vitest";
import { blocksToMarkdown, emptyDoc, type BlockDoc } from "@/lib/lesson/blocks";

/**
 * Unit coverage for the block-doc → markdown projection added in W11.
 *
 * The backend `TextLessonData` schema requires a non-empty
 * `body_markdown` (it's the canonical flat text the RAG chunker +
 * Postgres full-text search read). The editor only writes structured
 * `blocks`, so every Studio text-lesson save 422'd until we started
 * deriving `body_markdown` from the doc. These tests pin the
 * serialization for exactly the node + mark types the Tiptap config
 * in `block-editor.tsx` can produce.
 */

function doc(...content: BlockDoc["content"]): BlockDoc {
  return { type: "doc", content };
}

describe("blocksToMarkdown", () => {
  it("returns empty string for an empty / paragraph-only doc", () => {
    expect(blocksToMarkdown(emptyDoc())).toBe("");
    expect(blocksToMarkdown(null)).toBe("");
    expect(blocksToMarkdown(undefined)).toBe("");
  });

  it("serializes a plain paragraph", () => {
    expect(
      blocksToMarkdown(doc({ type: "paragraph", content: [{ type: "text", text: "Hello" }] })),
    ).toBe("Hello");
  });

  it("serializes headings with their level", () => {
    expect(
      blocksToMarkdown(
        doc({ type: "heading", attrs: { level: 2 }, content: [{ type: "text", text: "Title" }] }),
      ),
    ).toBe("## Title");
    expect(
      blocksToMarkdown(
        doc({ type: "heading", attrs: { level: 3 }, content: [{ type: "text", text: "Sub" }] }),
      ),
    ).toBe("### Sub");
  });

  it("applies inline marks (bold/italic/code/strike/link)", () => {
    const node = doc({
      type: "paragraph",
      content: [
        { type: "text", text: "a", marks: [{ type: "bold" }] },
        { type: "text", text: "b", marks: [{ type: "italic" }] },
        { type: "text", text: "c", marks: [{ type: "code" }] },
        { type: "text", text: "d", marks: [{ type: "strike" }] },
        { type: "text", text: "e", marks: [{ type: "link", attrs: { href: "https://x.test" } }] },
      ],
    });
    expect(blocksToMarkdown(node)).toBe("**a***b*`c`~~d~~[e](https://x.test)");
  });

  it("drops underline marks (no markdown equivalent) but keeps the text", () => {
    expect(
      blocksToMarkdown(
        doc({
          type: "paragraph",
          content: [{ type: "text", text: "plain", marks: [{ type: "underline" }] }],
        }),
      ),
    ).toBe("plain");
  });

  it("serializes bullet and ordered lists", () => {
    const bullets = doc({
      type: "bulletList",
      content: [
        { type: "listItem", content: [{ type: "paragraph", content: [{ type: "text", text: "one" }] }] },
        { type: "listItem", content: [{ type: "paragraph", content: [{ type: "text", text: "two" }] }] },
      ],
    });
    expect(blocksToMarkdown(bullets)).toBe("- one\n- two");

    const ordered = doc({
      type: "orderedList",
      content: [
        { type: "listItem", content: [{ type: "paragraph", content: [{ type: "text", text: "first" }] }] },
        { type: "listItem", content: [{ type: "paragraph", content: [{ type: "text", text: "second" }] }] },
      ],
    });
    expect(blocksToMarkdown(ordered)).toBe("1. first\n2. second");
  });

  it("serializes blockquotes with a leading marker on every line", () => {
    expect(
      blocksToMarkdown(
        doc({
          type: "blockquote",
          content: [{ type: "paragraph", content: [{ type: "text", text: "quoted" }] }],
        }),
      ),
    ).toBe("> quoted");
  });

  it("serializes code blocks with an optional language fence", () => {
    expect(
      blocksToMarkdown(
        doc({
          type: "codeBlock",
          attrs: { language: "python" },
          content: [{ type: "text", text: "print(1)" }],
        }),
      ),
    ).toBe("```python\nprint(1)\n```");
    expect(
      blocksToMarkdown(
        doc({ type: "codeBlock", content: [{ type: "text", text: "noop" }] }),
      ),
    ).toBe("```\nnoop\n```");
  });

  it("serializes horizontal rules and images", () => {
    expect(blocksToMarkdown(doc({ type: "horizontalRule" }))).toBe("---");
    expect(
      blocksToMarkdown(
        doc({ type: "image", attrs: { src: "https://x.test/a.png", alt: "cat" } }),
      ),
    ).toBe("![cat](https://x.test/a.png)");
    // No src → dropped (nothing to project).
    expect(blocksToMarkdown(doc({ type: "image", attrs: { alt: "x" } }))).toBe("");
  });

  it("joins top-level blocks with a blank line", () => {
    expect(
      blocksToMarkdown(
        doc(
          { type: "heading", attrs: { level: 2 }, content: [{ type: "text", text: "H" }] },
          { type: "paragraph", content: [{ type: "text", text: "p" }] },
        ),
      ),
    ).toBe("## H\n\np");
  });

  it("falls through unknown blocks to their children (no silent drop)", () => {
    // `callout` is renderer-only, not authorable — but if it ever
    // shows up in a doc its inner text must still reach the search
    // projection.
    expect(
      blocksToMarkdown(
        doc({
          type: "callout",
          attrs: { variant: "info" },
          content: [{ type: "paragraph", content: [{ type: "text", text: "note" }] }],
        }),
      ),
    ).toBe("note");
  });
});
