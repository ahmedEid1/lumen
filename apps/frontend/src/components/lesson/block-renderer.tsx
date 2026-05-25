import type { JSX } from "react";
import type { BlockDoc, BlockMark, BlockNode } from "@/lib/lesson/blocks";

/**
 * Read-only renderer for the lesson block tree.
 *
 * Deliberately framework-runtime-free: it walks the JSON shape from
 * `blocks.ts` with a tiny recursive visitor and never imports any
 * Tiptap or ProseMirror code. That keeps the lesson player bundle
 * small for the learner-facing path (no ~200 kB editor download
 * just to read a paragraph) and lets the renderer run in tests +
 * server components without a DOM shim.
 *
 * The Workbench prose styling is applied here, not on the editor —
 * the editor needs the toolbar/selection chrome and a slightly more
 * generous padding; the player just wants clean reading text.
 */
export function BlockRenderer({ value }: { value: BlockDoc }) {
  return (
    <article className="prose prose-neutral max-w-none font-body dark:prose-invert prose-headings:font-display prose-code:font-mono">
      {(value.content ?? []).map((node, i) => (
        <RenderNode key={i} node={node} />
      ))}
    </article>
  );
}

function RenderNode({ node }: { node: BlockNode }) {
  switch (node.type) {
    case "paragraph":
      return <p>{renderInline(node.content)}</p>;
    case "heading": {
      // Tiptap stores level on attrs.level (1..6). Clamp + default to
      // h2 — h1 is reserved for the lesson title rendered by the
      // page shell, so authoring an h1 inside a lesson would create
      // two competing document outlines.
      const raw = Number((node.attrs as { level?: unknown } | undefined)?.level ?? 2);
      const level = (Math.min(6, Math.max(1, Number.isFinite(raw) ? raw : 2)) | 0) as
        | 1
        | 2
        | 3
        | 4
        | 5
        | 6;
      const Tag = `h${level}` as keyof JSX.IntrinsicElements;
      return <Tag>{renderInline(node.content)}</Tag>;
    }
    case "bulletList":
      return (
        <ul>
          {(node.content ?? []).map((child, i) => (
            <RenderNode key={i} node={child} />
          ))}
        </ul>
      );
    case "orderedList":
      return (
        <ol>
          {(node.content ?? []).map((child, i) => (
            <RenderNode key={i} node={child} />
          ))}
        </ol>
      );
    case "listItem":
      return (
        <li>
          {(node.content ?? []).map((child, i) => (
            <RenderNode key={i} node={child} />
          ))}
        </li>
      );
    case "blockquote":
      return (
        <blockquote>
          {(node.content ?? []).map((child, i) => (
            <RenderNode key={i} node={child} />
          ))}
        </blockquote>
      );
    case "codeBlock": {
      const lang =
        (node.attrs as { language?: unknown } | undefined)?.language;
      // Code blocks intentionally render as plain monospaced text —
      // the editor wires up lowlight for syntax highlighting at
      // authoring time, but the player keeps the read path simple
      // (no highlighter shipped to the learner bundle). The
      // language attribute is preserved for downstream tools that
      // want to colourise later.
      return (
        <pre>
          <code className={typeof lang === "string" ? `language-${lang}` : undefined}>
            {textOf(node.content)}
          </code>
        </pre>
      );
    }
    case "horizontalRule":
      return <hr />;
    case "image": {
      const attrs = (node.attrs ?? {}) as { src?: unknown; alt?: unknown; title?: unknown };
      if (typeof attrs.src !== "string" || attrs.src.length === 0) return null;
      return (
        // eslint-disable-next-line @next/next/no-img-element -- instructor-controlled URLs, no next/image needed
        <img
          src={attrs.src}
          alt={typeof attrs.alt === "string" ? attrs.alt : ""}
          title={typeof attrs.title === "string" ? attrs.title : undefined}
        />
      );
    }
    case "callout": {
      // Notion-style note block. Stored shape mirrors how Tiptap
      // serialises custom blocks: `attrs.variant` ∈ "info" | "warn"
      // | "success" — but treated tolerantly here so an unknown
      // variant degrades to the neutral info style instead of
      // disappearing.
      const variant = String(
        (node.attrs as { variant?: unknown } | undefined)?.variant ?? "info",
      );
      const cls =
        variant === "warn"
          ? "border-amber-500/40 bg-amber-500/10"
          : variant === "success"
            ? "border-emerald-500/40 bg-emerald-500/10"
            : "border-border bg-muted";
      return (
        <aside className={`my-4 rounded-md border p-4 font-body text-sm ${cls}`}>
          {(node.content ?? []).map((child, i) => (
            <RenderNode key={i} node={child} />
          ))}
        </aside>
      );
    }
    case "hardBreak":
      return <br />;
    case "text":
      // A bare text node at block level shouldn't happen in a valid
      // doc, but tolerate it rather than crash on malformed input.
      return <>{renderText(node)}</>;
    default:
      // Unknown block type — render its children if it has any so
      // we don't drop content silently when an extension is added
      // server-side and the renderer hasn't caught up yet.
      if (Array.isArray(node.content)) {
        return (
          <>
            {node.content.map((child, i) => (
              <RenderNode key={i} node={child} />
            ))}
          </>
        );
      }
      return null;
  }
}

/* ---------------------------------------------------------------- */
/*  Inline children — text nodes + marks                             */
/* ---------------------------------------------------------------- */

function renderInline(children: BlockNode[] | undefined) {
  if (!children) return null;
  return children.map((child, i) => {
    if (child.type === "text") return <span key={i}>{renderText(child)}</span>;
    if (child.type === "hardBreak") return <br key={i} />;
    return <RenderNode key={i} node={child} />;
  });
}

function renderText(node: BlockNode) {
  let element: JSX.Element | string = node.text ?? "";
  const marks = (node.marks ?? []) as BlockMark[];
  // Walk marks outside-in so the outermost wrapper is the last mark
  // listed; matches Tiptap's serialisation order. Wrapping is
  // commutative for the marks we support so the visual result is
  // identical either way.
  for (const mark of marks) {
    element = wrapWithMark(element, mark);
  }
  return element;
}

function wrapWithMark(child: JSX.Element | string, mark: BlockMark): JSX.Element {
  switch (mark.type) {
    case "bold":
      return <strong>{child}</strong>;
    case "italic":
      return <em>{child}</em>;
    case "code":
      return <code>{child}</code>;
    case "strike":
      return <s>{child}</s>;
    case "underline":
      return <u>{child}</u>;
    case "link": {
      const attrs = (mark.attrs ?? {}) as { href?: unknown; target?: unknown };
      const href = typeof attrs.href === "string" ? attrs.href : "#";
      // `noopener noreferrer` on every link — instructors paste
      // arbitrary URLs and we don't want a learner click to leak
      // window.opener to a third party.
      return (
        <a
          href={href}
          target={typeof attrs.target === "string" ? attrs.target : "_blank"}
          rel="noopener noreferrer"
        >
          {child}
        </a>
      );
    }
    default:
      return <>{child}</>;
  }
}

/** Flatten a code-block's children to a single string. */
function textOf(children: BlockNode[] | undefined): string {
  if (!children) return "";
  return children.map((c) => (c.type === "text" ? (c.text ?? "") : textOf(c.content))).join("");
}
