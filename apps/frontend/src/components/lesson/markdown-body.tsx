"use client";

import type { ComponentPropsWithoutRef } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { HighlightedCode } from "@/components/lesson/highlighted-code";

/**
 * MarkdownBody — renders an instructor-authored *markdown string* as
 * formatted content for the learner.
 *
 * Why this exists: pre-Phase-E6 `text` lessons stored their body as a
 * free-form markdown string in `data.body_markdown` / `data.body`.
 * The legacy promotion path (`fromLegacyMarkdown`) dropped that whole
 * string into a single paragraph block *verbatim*, so on the live
 * learner surface students saw raw `## heading`, `**bold**`,
 * `*italic*`, and fenced ```ts blocks as literal characters instead
 * of formatted prose. This component closes that gap by parsing the
 * markdown with `react-markdown` + `remark-gfm` (tables, strikethrough,
 * task lists) at render time. The newer `data.blocks` shape is
 * unaffected — that still renders through `BlockRenderer`.
 *
 * SECURITY: lesson content is instructor-authored and therefore
 * UNTRUSTED. We rely on react-markdown's DEFAULT behaviour, which
 * ESCAPES any raw HTML embedded in the markdown source. There is
 * deliberately NO `rehype-raw` and NO `dangerouslySetInnerHTML` on
 * the markdown path — adding either would turn instructor markdown
 * into a stored-XSS vector. Markdown syntax only.
 *
 * Styling mirrors `BlockRenderer`: the same `<article>` wrapper +
 * Workbench font tokens, so the legacy markdown path and the block
 * path read identically on the page.
 */

type CodeProps = ComponentPropsWithoutRef<"code"> & {
  // react-markdown v9+ no longer passes `inline`; we infer block vs.
  // inline from the className it sets on fenced blocks (`language-*`)
  // and the presence of a newline in the content.
  node?: unknown;
};

const components: Components = {
  code({ className, children, ...props }: CodeProps) {
    const text = String(children ?? "");
    const match = /language-(\w[\w+-]*)/.exec(className ?? "");
    // A fenced code block is the only place react-markdown attaches a
    // `language-*` class; multi-line content is also treated as a
    // block so unlabeled fences still reach the highlighter rather
    // than rendering as a cramped inline span.
    const isBlock = Boolean(match) || text.includes("\n");

    if (isBlock) {
      // Fenced block → reuse the existing Shiki highlighter so syntax
      // highlighting is preserved (and shiki stays dynamically loaded).
      // Trailing newline trimmed: react-markdown includes the final
      // line break before the closing fence.
      return <HighlightedCode code={text.replace(/\n$/, "")} lang={match?.[1]} />;
    }

    // Inline code → a simple, readable styled <code>.
    return (
      <code
        className="rounded-sm border border-border bg-muted px-1 py-0.5 font-mono text-[0.9em]"
        {...props}
      >
        {children}
      </code>
    );
  },
  // react-markdown wraps a fenced block as `<pre><code>`. Our `code`
  // override renders fenced blocks via <HighlightedCode>, which is itself
  // a block element (a `<div>`/`<pre>` wrapper) — so leaving react-markdown's
  // `<pre>` in place nests a block inside `<pre>` (invalid markup; codex
  // iter16 P2). Render `pre` as a passthrough so the highlighter provides
  // the sole block container. Inline code isn't wrapped in `<pre>`, so this
  // doesn't touch it.
  pre({ children }: ComponentPropsWithoutRef<"pre">) {
    return <>{children}</>;
  },
  // Links: instructors paste arbitrary URLs, so mirror BlockRenderer's
  // policy — open in a new tab and strip window.opener with
  // `noopener noreferrer` so a learner click can't leak the opener to
  // a third party.
  a({ children, href, ...props }) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
        {children}
      </a>
    );
  },
};

export function MarkdownBody({ markdown }: { markdown: string }) {
  return (
    <article className="prose prose-neutral max-w-none font-body dark:prose-invert prose-headings:font-display prose-code:font-mono">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {markdown}
      </ReactMarkdown>
    </article>
  );
}
