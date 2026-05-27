import { ImageResponse } from "next/og";

/**
 * L31 — per-route OG for /case-study.
 */

export const alt =
  "Lumen case study — how an agentic tutor was built on a real LLM budget.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function CaseStudyOpengraphImage() {
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
            Lumen / case-study
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
            Case study
          </div>
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: "12px",
              fontSize: "72px",
              fontWeight: 600,
              letterSpacing: "-0.03em",
              lineHeight: 1.05,
              maxWidth: "1000px",
            }}
          >
            <span>How I built an agentic tutor.</span>
            <span style={{ color: "#7F7F7F" }}>On a real LLM budget.</span>
          </div>
        </div>

        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "4px",
            fontFamily: "ui-monospace, monospace",
            fontSize: "14px",
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "#7F7F7F",
          }}
        >
          <div>Architecture · prompt iteration · what I did not use · lessons</div>
          <div>lumen.ahmedhobeishy.tech/case-study</div>
        </div>
      </div>
    ),
    { ...size },
  );
}
