"use client";

import { useEffect, useState } from "react";
import { useTheme } from "next-themes";

/**
 * Workbench HighlightedCode.
 *
 * Client-side Shiki highlighter for the block renderer. Dynamically
 * imports shiki on mount so text-only lessons don't pay for the
 * highlighter bundle — only lessons with a code block do.
 *
 * Theme tracks `next-themes` `resolvedTheme`:
 *   dark  → github-dark
 *   light → github-light
 * Both are Workbench-compatible: GitHub's themes are minimal
 * (keyword / string / comment / function), which matches the
 * restrained design language better than rainbow-style themes.
 *
 * Fallback while loading or on error: plain `<pre><code>` rendering
 * — same shape as the pre-Loop-16 behaviour, so authored content
 * stays readable even if the highlighter never lands.
 */
export function HighlightedCode({
  code,
  lang,
}: {
  code: string;
  lang?: string;
}) {
  const { resolvedTheme } = useTheme();
  const [html, setHtml] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const themeName = resolvedTheme === "light" ? "github-light" : "github-dark";
    // Dynamic import keeps shiki out of the initial bundle.
    import("shiki")
      .then(async (mod) => {
        const result = await mod.codeToHtml(code, {
          lang: lang ?? "text",
          theme: themeName,
        });
        if (!cancelled) setHtml(result);
      })
      .catch(() => {
        // Swallow — fall through to the plain <pre> below.
      });
    return () => {
      cancelled = true;
    };
  }, [code, lang, resolvedTheme]);

  if (html) {
    return (
      <div
        // Shiki returns `<pre class="shiki ..."><code>...</code></pre>`.
        // dangerouslySetInnerHTML is the documented way to consume it.
        // The HTML it generates is safe — Shiki only emits styled
        // spans with no user-attributed attributes.
        dangerouslySetInnerHTML={{ __html: html }}
        className="wb-shiki-block my-4 overflow-x-auto rounded-md border border-border"
      />
    );
  }

  // Fallback: plain pre/code. Same shape as pre-Loop-16.
  return (
    <pre className="my-4 overflow-x-auto rounded-md border border-border bg-card p-4 font-mono text-sm">
      <code className={lang ? `language-${lang}` : undefined}>{code}</code>
    </pre>
  );
}
