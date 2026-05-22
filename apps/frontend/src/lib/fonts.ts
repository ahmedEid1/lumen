import { Instrument_Serif, Geist, Geist_Mono } from "next/font/google";

/**
 * Display face — Instrument Serif. High-contrast, slightly editorial
 * serif. Pairs cleanly with a modern grotesque; carries headlines at
 * any size from 18px to 144px without losing its character.
 */
export const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  variable: "--font-instrument-serif",
  display: "swap",
  weight: ["400"],
  style: ["normal", "italic"],
});

/**
 * Body face — Geist. Vercel's neutral grotesque. Functions as the
 * SF-Pro stand-in for cross-platform consistency and renders crisply
 * at body and UI sizes.
 */
export const geist = Geist({
  subsets: ["latin"],
  variable: "--font-geist",
  display: "swap",
});

/**
 * Mono face — Geist Mono. Used for code, kbd, and any tabular data
 * (durations, counts) where the body grotesque would feel wobbly.
 */
export const geistMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-geist-mono",
  display: "swap",
});
