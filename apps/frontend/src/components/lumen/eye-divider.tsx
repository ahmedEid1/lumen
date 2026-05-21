import { Glyph } from "@/components/lumen/glyph";
import { cn } from "@/lib/utils";

/**
 * Eye-Divider — a thin horizontal flourish: gold rule, ankh node,
 * eye-of-horus medallion, ankh node, gold rule. All glyphs use the
 * tint mode so they inherit the surrounding gold colour.
 */
export function EyeDivider({ className }: { className?: string }) {
  return (
    <div
      className={cn("flex items-center justify-center gap-4 text-gold/70", className)}
      aria-hidden
    >
      <span className="h-px w-12 bg-gradient-to-r from-transparent via-gold/60 to-gold/30 sm:w-20" />
      <Glyph name="ankh" size={18} mode="tint" />
      <Glyph name="eye" size={26} mode="tint" />
      <Glyph name="ankh" size={18} mode="tint" />
      <span className="h-px w-12 bg-gradient-to-l from-transparent via-gold/60 to-gold/30 sm:w-20" />
    </div>
  );
}
