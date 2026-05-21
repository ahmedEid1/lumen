import { Fraunces, Lora } from "next/font/google";

/**
 * Display face — Fraunces variable. Display optical size + slight WONK
 * lend the headings a carved, slightly off-axis character without
 * tipping into pastiche. Tuned through CSS font-variation-settings on
 * specific elements when needed.
 */
export const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--font-fraunces",
  display: "swap",
  weight: ["300", "400", "500", "600", "700", "900"],
  style: ["normal", "italic"],
});

/**
 * Body face — Lora. Warm transitional serif designed for long reading,
 * pairs with Fraunces by sharing a humanist axis without copying its
 * personality.
 */
export const lora = Lora({
  subsets: ["latin"],
  variable: "--font-lora",
  display: "swap",
  weight: ["400", "500", "600", "700"],
  style: ["normal", "italic"],
});
