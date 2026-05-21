/* eslint-disable @next/next/no-img-element */
import { cn } from "@/lib/utils";

/**
 * Glyph — renders an Egyptian hieroglyph asset from the public
 * `/glyphs/` directory.
 *
 * All sources are drawings from Wikimedia Commons (see CREDITS.md
 * in that directory), preserved at their original artistic intent.
 *
 * Two render modes:
 *
 * - `mode="art"` (default) — renders an <img> with the original
 *   colour treatment intact. Use when the glyph is the visual hero
 *   (hero ornaments, dividers, large display pieces).
 *
 * - `mode="tint"` — renders a CSS-masked span coloured with
 *   `currentColor`. Use when the glyph sits inside text or chrome
 *   and needs to inherit the surrounding colour (header logo,
 *   button glyph accents, sidebar nav).
 */
export type GlyphName =
  | "ankh"
  | "eye"
  | "djed"
  | "was"
  | "feather"
  | "sun-disk"
  | "aten"
  | "scroll";

/** Aspect ratios let us reserve correct space and avoid CLS. Sourced
 *  from each SVG's intrinsic dimensions. `scroll` reuses the ankh
 *  ratio since we render it as a stand-in for the un-sourced
 *  papyrus-roll glyph (Gardiner V12). */
const RATIO: Record<GlyphName, number> = {
  ankh: 500 / 878,
  eye: 650 / 500,
  djed: 1,
  was: 22 / 542,
  feather: 35 / 110,
  "sun-disk": 172 / 128,
  aten: 781 / 337,
  scroll: 500 / 878,
};

const SRC: Record<GlyphName, string> = {
  ankh: "/glyphs/ankh.svg",
  eye: "/glyphs/eye.svg",
  djed: "/glyphs/djed.svg",
  was: "/glyphs/was.svg",
  feather: "/glyphs/feather.svg",
  "sun-disk": "/glyphs/sun-disk.svg",
  aten: "/glyphs/aten.svg",
  scroll: "/glyphs/ankh.svg",
};

export interface GlyphProps extends Omit<React.HTMLAttributes<HTMLElement>, "children"> {
  name: GlyphName;
  /** Long edge in px (or any CSS length). The short edge is derived
   *  from each glyph's intrinsic aspect ratio. */
  size?: number | string;
  mode?: "art" | "tint";
}

export function Glyph({ name, size = 24, mode = "tint", className, style, ...rest }: GlyphProps) {
  const src = SRC[name];
  const ratio = RATIO[name];
  // Long edge is whichever dimension is larger in the source. We size
  // the long edge and let the short edge auto-scale via aspect-ratio.
  const longEdge = typeof size === "number" ? `${size}px` : size;

  if (mode === "art") {
    return (
      <img
        src={src}
        alt=""
        aria-hidden="true"
        loading="lazy"
        decoding="async"
        className={cn("inline-block shrink-0 select-none", className)}
        style={{
          height: longEdge,
          width: "auto",
          ...style,
        }}
        {...(rest as React.ImgHTMLAttributes<HTMLImageElement>)}
      />
    );
  }

  // tint mode — CSS mask with background-color: currentColor lets the
  // glyph inherit the surrounding text colour for chrome use.
  return (
    <span
      role="img"
      aria-hidden="true"
      className={cn("inline-block shrink-0 select-none align-text-bottom", className)}
      style={{
        height: longEdge,
        aspectRatio: String(ratio),
        backgroundColor: "currentColor",
        WebkitMaskImage: `url("${src}")`,
        maskImage: `url("${src}")`,
        WebkitMaskRepeat: "no-repeat",
        maskRepeat: "no-repeat",
        WebkitMaskPosition: "center",
        maskPosition: "center",
        WebkitMaskSize: "contain",
        maskSize: "contain",
        ...style,
      }}
      {...rest}
    />
  );
}
