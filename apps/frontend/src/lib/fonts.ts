import localFont from "next/font/local";

/**
 * Workbench typography stack — single sans (Inter) used at two weight
 * variables for "display" vs body context, plus JetBrains Mono for
 * IDs / durations / timestamps. Components reference `font-display`,
 * `font-body`, and `font-mono` Tailwind utilities; those resolve via
 * @theme in globals.css to the CSS variables below.
 *
 * **Self-hosted** (was `next/font/google`). `next/font/google` fetches
 * the woff2 from `fonts.gstatic.com` at *build* time; when Google
 * rate-limited / blocked the CI runner IPs the container build failed
 * (`Failed to fetch 'Inter' from Google Fonts`) and every deploy was
 * blocked. The variable woff2 files now live in `./fonts` (latin
 * subset, sourced from @fontsource — same typefaces) so the build has
 * no external dependency, matching Lumen's self-hostable posture. The
 * exported `.variable` class names + CSS-var names are unchanged, so
 * layout.tsx and globals.css need no edits.
 */

export const interDisplay = localFont({
  src: "./fonts/inter-latin-wght-normal.woff2",
  variable: "--font-inter-display",
  display: "swap",
  weight: "100 900",
});

export const interBody = localFont({
  src: "./fonts/inter-latin-wght-normal.woff2",
  variable: "--font-inter",
  display: "swap",
  weight: "100 900",
});

export const jetbrainsMono = localFont({
  src: "./fonts/jetbrains-mono-latin-wght-normal.woff2",
  variable: "--font-jetbrains-mono",
  display: "swap",
  weight: "100 800",
});
