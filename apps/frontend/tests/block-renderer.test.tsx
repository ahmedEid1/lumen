import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { BlockRenderer } from "@/components/lesson/block-renderer";
import { fromLegacyMarkdown, emptyDoc, type BlockDoc } from "@/lib/lesson/blocks";

describe("BlockRenderer", () => {
  it("renders paragraph, heading, and bulletList nodes as the expected HTML elements", () => {
    const doc: BlockDoc = {
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [{ type: "text", text: "intro paragraph" }],
        },
        {
          type: "heading",
          attrs: { level: 2 },
          content: [{ type: "text", text: "section title" }],
        },
        {
          type: "bulletList",
          content: [
            {
              type: "listItem",
              content: [
                {
                  type: "paragraph",
                  content: [{ type: "text", text: "first bullet" }],
                },
              ],
            },
            {
              type: "listItem",
              content: [
                {
                  type: "paragraph",
                  content: [{ type: "text", text: "second bullet" }],
                },
              ],
            },
          ],
        },
      ],
    };

    const { container } = render(<BlockRenderer value={doc} />);

    // Paragraph
    const paragraphs = container.querySelectorAll("p");
    expect(paragraphs.length).toBeGreaterThanOrEqual(1);
    expect(container.textContent).toContain("intro paragraph");

    // Heading
    const heading = container.querySelector("h2");
    expect(heading).not.toBeNull();
    expect(heading?.textContent).toBe("section title");

    // Bullet list — <ul> with two <li> children, each carrying a paragraph
    const ul = container.querySelector("ul");
    expect(ul).not.toBeNull();
    const items = ul!.querySelectorAll("li");
    expect(items).toHaveLength(2);
    expect(items[0]!.textContent).toContain("first bullet");
    expect(items[1]!.textContent).toContain("second bullet");
  });

  it("applies inline marks (bold / italic / code / link) on text nodes", () => {
    const doc: BlockDoc = {
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [
            { type: "text", marks: [{ type: "bold" }], text: "loud" },
            { type: "text", text: " " },
            { type: "text", marks: [{ type: "italic" }], text: "lean" },
            { type: "text", text: " " },
            { type: "text", marks: [{ type: "code" }], text: "snippet" },
            { type: "text", text: " " },
            {
              type: "text",
              marks: [{ type: "link", attrs: { href: "https://example.org" } }],
              text: "site",
            },
          ],
        },
      ],
    };

    const { container } = render(<BlockRenderer value={doc} />);
    expect(container.querySelector("strong")?.textContent).toBe("loud");
    expect(container.querySelector("em")?.textContent).toBe("lean");
    expect(container.querySelector("code")?.textContent).toBe("snippet");
    const link = container.querySelector("a");
    expect(link?.getAttribute("href")).toBe("https://example.org");
    expect(link?.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("renders codeBlock, blockquote, and horizontalRule", () => {
    const doc: BlockDoc = {
      type: "doc",
      content: [
        {
          type: "codeBlock",
          attrs: { language: "ts" },
          content: [{ type: "text", text: "const x: number = 1;" }],
        },
        {
          type: "blockquote",
          content: [
            { type: "paragraph", content: [{ type: "text", text: "wisdom" }] },
          ],
        },
        { type: "horizontalRule" },
      ],
    };

    const { container } = render(<BlockRenderer value={doc} />);
    const pre = container.querySelector("pre code");
    expect(pre?.textContent).toBe("const x: number = 1;");
    expect(pre?.className).toContain("language-ts");
    expect(container.querySelector("blockquote")?.textContent).toContain("wisdom");
    expect(container.querySelector("hr")).not.toBeNull();
  });

  it("handles the legacy-markdown promotion path: empty doc renders without crash", () => {
    const { container } = render(<BlockRenderer value={emptyDoc()} />);
    // One paragraph (the placeholder), no headings, no lists.
    expect(container.querySelector("article")).not.toBeNull();
    expect(container.querySelector("h1")).toBeNull();
  });

  it("promotes a legacy markdown string into a single paragraph block", () => {
    const promoted = fromLegacyMarkdown("# This was markdown but stays verbatim");
    const { container } = render(<BlockRenderer value={promoted} />);
    // Verbatim — no markdown parsing, the hash is preserved as text.
    expect(container.textContent).toContain("# This was markdown but stays verbatim");
    // It's a paragraph, not an h1 — the promotion path is deliberately dumb.
    expect(container.querySelector("h1")).toBeNull();
    expect(container.querySelector("p")).not.toBeNull();
  });

  it("renders images with src and alt attributes", () => {
    const doc: BlockDoc = {
      type: "doc",
      content: [
        {
          type: "image",
          attrs: { src: "https://cdn.example.org/diagram.png", alt: "a diagram" },
        },
      ],
    };
    render(<BlockRenderer value={doc} />);
    const img = screen.getByAltText("a diagram") as HTMLImageElement;
    expect(img.getAttribute("src")).toBe("https://cdn.example.org/diagram.png");
  });
});
