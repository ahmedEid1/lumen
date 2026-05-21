import { cn } from "@/lib/utils";

/**
 * Hand-drawn hieroglyph marks. Pure SVG so they render identically
 * across OSes that may or may not ship a Unicode hieroglyph carrier.
 * Each mark inherits currentColor; pair with text-primary / text-accent
 * to recolour.
 */
export type GlyphName = "ankh" | "eye" | "djed" | "was" | "feather" | "sun" | "scroll";

const PATHS: Record<GlyphName, React.ReactNode> = {
  // Ankh — life, cross under a loop.
  ankh: (
    <g fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="12" cy="8" rx="5.4" ry="6.4" />
      <path d="M12 14.4v15.6M4.8 19.2h14.4" />
    </g>
  ),
  // Eye of Horus — protection, knowledge.
  eye: (
    <g fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12 Q8 4 16 4 Q24 4 30 12 Q24 18 16 18 Q8 18 2 12 Z" />
      <circle cx="16" cy="12" r="2.6" fill="currentColor" stroke="none" />
      <path d="M5 5.5 Q14 1.5 26 4.5" />
      <path d="M14 18 Q11.5 22 13.5 25" />
      <path d="M22 18 Q22 24 28.5 22" />
    </g>
  ),
  // Djed pillar — stability, the spine of Osiris.
  djed: (
    <g fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <line x1="10" y1="14" x2="10" y2="30" />
      <path d="M2 4h16M2 7h16M2 10h16M2 13h16" />
      <path d="M1.5 14h17" strokeWidth="1.8" />
    </g>
  ),
  // Was sceptre — dominion. Forked base, stylised animal head.
  was: (
    <g fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <line x1="10" y1="8" x2="10" y2="26" />
      <path d="M6 5 Q10 2 14 5 L14 7 L6 7 Z" />
      <path d="M7 26 L5 31 M13 26 L15 31" />
    </g>
  ),
  // Feather of Ma'at — truth, balance.
  feather: (
    <g fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10 2 Q14 8 13 18 Q11 28 9 30" />
      <path d="M10 2 Q6 8 7 18 Q9 26 9 30" />
      <path d="M10 8 L7 9 M10 12 L6 13 M10 16 L6 18 M10 20 L7 22" />
    </g>
  ),
  // Sun disc / Aten — knowledge that illuminates.
  sun: (
    <g fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round">
      <circle cx="16" cy="16" r="6" fill="currentColor" />
      {[0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330].map((deg) => (
        <line
          key={deg}
          x1="16"
          y1="4"
          x2="16"
          y2="1"
          transform={`rotate(${deg} 16 16)`}
        />
      ))}
    </g>
  ),
  // Papyrus scroll — knowledge inscribed.
  scroll: (
    <g fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="6" cy="16" rx="3" ry="12" />
      <ellipse cx="26" cy="16" rx="3" ry="12" />
      <path d="M6 4 L26 4 M6 28 L26 28" />
      <path d="M10 10h12M10 14h10M10 18h12M10 22h8" opacity="0.6" />
    </g>
  ),
};

const VIEW: Record<GlyphName, string> = {
  ankh: "0 0 24 32",
  eye: "0 0 32 24",
  djed: "0 0 20 32",
  was: "0 0 20 32",
  feather: "0 0 20 32",
  sun: "0 0 32 32",
  scroll: "0 0 32 32",
};

export interface GlyphProps extends React.SVGAttributes<SVGSVGElement> {
  name: GlyphName;
  size?: number | string;
}

export function Glyph({ name, size = 24, className, ...rest }: GlyphProps) {
  return (
    <svg
      viewBox={VIEW[name]}
      width={size}
      height={size}
      role="img"
      aria-hidden="true"
      className={cn("inline-block shrink-0", className)}
      {...rest}
    >
      {PATHS[name]}
    </svg>
  );
}
