import { Inter, JetBrains_Mono } from "next/font/google";

/**
 * Workbench typography stack — single sans (Inter) used at two weight
 * variables for "display" vs body context, plus JetBrains Mono for
 * IDs / durations / timestamps. Components reference `font-display`,
 * `font-body`, and `font-mono` Tailwind utilities; those resolve via
 * @theme in globals.css to the next/font CSS variables below.
 */

export const interDisplay = Inter({
  subsets: ["latin"],
  variable: "--font-inter-display",
  display: "swap",
  weight: ["500", "600", "700"],
});

export const interBody = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});
