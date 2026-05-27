import { ImageResponse } from "next/og";

// QA loop iter 1: every cold visit was hitting /favicon.ico → 404
// because nothing in the app declared one. Next.js' `app/icon.tsx`
// convention auto-wires the result as `<link rel="icon">` so browsers
// stop falling back to /favicon.ico — and the head link wins over the
// legacy path even for browsers that still try both.
//
// Mark matches `opengraph-image.tsx`: open square bracket with lime
// cursor on the Workbench dark background.

export const size = { width: 32, height: 32 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          background: "#0A0B0D",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <svg
          width="22"
          height="22"
          viewBox="0 0 24 24"
          fill="none"
          stroke="#C8FF00"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M7 4H4v16h3" />
          <path d="M17 4h3v16h-3" />
          <circle cx="12" cy="12" r="2.5" fill="#C8FF00" stroke="none" />
        </svg>
      </div>
    ),
    { ...size },
  );
}
