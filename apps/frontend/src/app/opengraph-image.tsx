import { ImageResponse } from "next/og";

/**
 * Open Graph + Twitter social card.
 *
 * Loop 19: Lumen had `openGraph` metadata pointing at no image —
 * social shares rendered as text-only previews. This file uses the
 * Next 15 file-system convention (`app/opengraph-image.tsx`) to
 * generate a 1200×630 image at request time, served at
 * `/opengraph-image` and auto-wired into the layout's metadata.
 *
 * Workbench aesthetic: solid dark background, lime accent on the
 * brand mark + the "Now open." cartouche, mono uppercase eyebrow,
 * display-face wordmark, no shadow / gradient / mesh.
 */

// Loop 19 hotfix: dropped `runtime = "edge"` — our standalone Next
// build runs on Node and the edge runtime triggered a 502 through
// the Caddy proxy. Node runtime is fine for OG images — ImageResponse
// works in both.
export const alt = "Lumen — Learn what you actually use.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          background: "#0A0B0D",
          color: "#FAFAF9",
          padding: "80px",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
          {/* Lumen mark — open square bracket with lime cursor. */}
          <svg
            width="44"
            height="44"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#C8FF00"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M7 4H4v16h3" />
            <path d="M17 4h3v16h-3" />
            <circle cx="12" cy="12" r="2.5" fill="#C8FF00" stroke="none" />
          </svg>
          <div
            style={{
              fontSize: "32px",
              fontWeight: 600,
              letterSpacing: "-0.02em",
            }}
          >
            Lumen
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
          <div
            style={{
              fontFamily: "ui-monospace, monospace",
              fontSize: "16px",
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "#C8FF00",
            }}
          >
            Now open.
          </div>
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: "12px",
              fontSize: "84px",
              fontWeight: 600,
              letterSpacing: "-0.03em",
              lineHeight: 1.02,
              maxWidth: "900px",
            }}
          >
            <span>Take a path.</span>
            <span style={{ color: "#7F7F7F" }}>Become it.</span>
          </div>
        </div>

        <div
          style={{
            fontFamily: "ui-monospace, monospace",
            fontSize: "14px",
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "#7F7F7F",
          }}
        >
          lumen.ahmedhobeishy.tech
        </div>
      </div>
    ),
    { ...size },
  );
}
