import { cn } from "@/lib/utils";

/**
 * Eye-Divider — a thin horizontal flourish: gold rule, ankh node,
 * eye-of-horus medallion, ankh node, gold rule. Used between page
 * sections that would otherwise be separated by a plain border.
 */
export function EyeDivider({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center justify-center gap-3 text-gold/70", className)} aria-hidden>
      <span className="h-px w-12 bg-gradient-to-r from-transparent via-gold/60 to-gold/30 sm:w-20" />
      <svg width="14" height="18" viewBox="0 0 14 18" fill="none">
        <ellipse cx="7" cy="4" rx="3" ry="3.5" stroke="currentColor" strokeWidth="1" />
        <path d="M7 8v9M2.5 11h9" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
      </svg>
      <svg width="44" height="22" viewBox="0 0 44 22" fill="none">
        <path
          d="M2 11 Q12 3 22 3 Q32 3 42 11 Q32 19 22 19 Q12 19 2 11 Z"
          stroke="currentColor"
          strokeWidth="1"
          strokeLinejoin="round"
        />
        <circle cx="22" cy="11" r="2.6" fill="currentColor" />
        <path d="M6 5 Q16 1 38 4" stroke="currentColor" strokeWidth="1" strokeLinecap="round" fill="none" />
      </svg>
      <svg width="14" height="18" viewBox="0 0 14 18" fill="none">
        <ellipse cx="7" cy="4" rx="3" ry="3.5" stroke="currentColor" strokeWidth="1" />
        <path d="M7 8v9M2.5 11h9" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
      </svg>
      <span className="h-px w-12 bg-gradient-to-l from-transparent via-gold/60 to-gold/30 sm:w-20" />
    </div>
  );
}
