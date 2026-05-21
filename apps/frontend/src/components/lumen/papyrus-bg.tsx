import { cn } from "@/lib/utils";

/**
 * Layered hero backdrop. Server-renderable. Composes:
 *
 *  1. base wash — radial gold halo over the lapis ground
 *  2. tiled hieroglyph pattern (low opacity) — visible only on close
 *     inspection, gives the eye texture to settle on
 *  3. SVG grain overlay — breaks up flat colour fields on OLED
 *  4. vignette to the page edges
 *
 * Each layer is its own absolutely-positioned div so the parent only
 * needs `relative overflow-hidden`.
 */
export function PapyrusBg({ className }: { className?: string }) {
  return (
    <div aria-hidden className={cn("pointer-events-none absolute inset-0 -z-20 overflow-hidden", className)}>
      {/* 1 — base wash */}
      <div className="absolute inset-0 hypostyle" />

      {/* 2 — hieroglyph tile */}
      <svg className="absolute inset-0 h-full w-full opacity-[0.07]" aria-hidden>
        <defs>
          <pattern id="lumen-glyph-tile" width="220" height="220" patternUnits="userSpaceOnUse" patternTransform="rotate(-6)">
            <g fill="none" stroke="hsl(var(--gold-leaf))" strokeWidth="0.9" strokeLinecap="round">
              {/* Eye */}
              <path d="M22 50 Q34 38 52 38 Q70 38 82 50 Q70 60 52 60 Q34 60 22 50 Z" />
              <circle cx="52" cy="50" r="4" fill="hsl(var(--gold-leaf))" stroke="none" />
              {/* Ankh */}
              <ellipse cx="150" cy="40" rx="9" ry="10" />
              <line x1="150" y1="50" x2="150" y2="90" />
              <line x1="135" y1="65" x2="165" y2="65" />
              {/* Djed */}
              <line x1="55" y1="120" x2="55" y2="170" />
              <line x1="40" y1="120" x2="70" y2="120" />
              <line x1="40" y1="126" x2="70" y2="126" />
              <line x1="40" y1="132" x2="70" y2="132" />
              <line x1="40" y1="138" x2="70" y2="138" />
              {/* Feather */}
              <path d="M165 130 Q172 145 168 175 Q166 185 162 192" />
              <path d="M165 130 Q158 145 162 175 Q164 185 162 192" />
            </g>
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#lumen-glyph-tile)" />
      </svg>

      {/* 3 — grain */}
      <svg className="absolute inset-0 h-full w-full opacity-[0.12] mix-blend-overlay" aria-hidden>
        <filter id="lumen-grain">
          <feTurbulence type="fractalNoise" baseFrequency="0.92" numOctaves="2" stitchTiles="stitch" />
          <feColorMatrix values="0 0 0 0 0.95  0 0 0 0 0.85  0 0 0 0 0.6  0 0 0 0.6 0" />
        </filter>
        <rect width="100%" height="100%" filter="url(#lumen-grain)" />
      </svg>

      {/* 4 — vignette */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse at center, transparent 55%, hsl(var(--background) / 0.7) 100%)",
        }}
      />
    </div>
  );
}
