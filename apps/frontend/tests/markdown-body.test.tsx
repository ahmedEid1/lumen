import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { MarkdownBody } from "@/components/lesson/markdown-body";

/**
 * Regression coverage for the prod bug: legacy `text` lessons stored
 * a raw markdown string that rendered as literal characters
 * (`## heading`, `**bold**`, fenced ```ts blocks) instead of formatted
 * content. MarkdownBody must parse that markdown into real elements.
 */
describe("MarkdownBody", () => {
  it("renders **bold** as <strong> and ## h2 as a heading element (not literal markdown)", () => {
    const { container } = render(
      <MarkdownBody markdown={"## Section title\n\nThis is **bold** and *italic* text."} />,
    );

    const h2 = container.querySelector("h2");
    expect(h2).not.toBeNull();
    expect(h2?.textContent).toBe("Section title");

    expect(container.querySelector("strong")?.textContent).toBe("bold");
    expect(container.querySelector("em")?.textContent).toBe("italic");

    // The raw markdown punctuation must NOT survive as literal text.
    expect(container.textContent).not.toContain("##");
    expect(container.textContent).not.toContain("**bold**");
  });

  it("routes a fenced code block through the HighlightedCode highlighter", () => {
    const { container } = render(
      <MarkdownBody markdown={"```ts\nconst x: number = 1;\n```"} />,
    );

    // Shiki is dynamically imported and won't have resolved synchronously
    // in the test, so HighlightedCode renders its plain <pre><code>
    // fallback — which carries the `language-ts` class it was handed.
    const code = container.querySelector("pre code");
    expect(code).not.toBeNull();
    expect(code?.textContent).toBe("const x: number = 1;");
    expect(code?.className).toContain("language-ts");
  });

  it("renders inline code as a simple <code> without a language class", () => {
    const { container } = render(<MarkdownBody markdown={"Use the `useState` hook."} />);

    const codes = Array.from(container.querySelectorAll("code"));
    const inline = codes.find((c) => c.textContent === "useState");
    expect(inline).toBeTruthy();
    // Inline code lives outside a <pre> and carries no language-* class.
    expect(inline?.closest("pre")).toBeNull();
    expect(inline?.className).not.toContain("language-");
  });

  it("escapes embedded raw HTML instead of executing it (XSS-safe default)", () => {
    const { container } = render(
      <MarkdownBody markdown={'Hello <img src=x onerror="alert(1)"> world'} />,
    );

    // react-markdown's default escapes raw HTML — no <img> node is
    // created, so the onerror handler can never fire.
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    // The angle-bracket text is rendered as visible characters.
    expect(container.textContent).toContain("onerror");
  });

  it("supports GFM tables and strikethrough via remark-gfm", () => {
    const md = ["| A | B |", "| - | - |", "| 1 | 2 |", "", "~~gone~~"].join("\n");
    const { container } = render(<MarkdownBody markdown={md} />);

    expect(container.querySelector("table")).not.toBeNull();
    expect(container.querySelectorAll("td")).toHaveLength(2);
    expect(container.querySelector("del")?.textContent).toBe("gone");
  });
});
