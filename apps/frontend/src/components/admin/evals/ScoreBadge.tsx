/**
 * ScoreBadge — small mono pill that renders a 0-5 score with a
 * traffic-light tone derived from the score itself. Used by the
 * eval dashboard pages so the per-axis numbers scan as a
 * dashboard at a glance and not as an undifferentiated table.
 *
 * Lumen v2 Phase H2.
 */

export interface ScoreBadgeProps {
  label?: string;
  value: number | null | undefined;
  /** Show "/ 5" suffix after the value. Defaults to false. */
  showDenominator?: boolean;
}

export function ScoreBadge({ label, value, showDenominator }: ScoreBadgeProps) {
  if (value == null) {
    return (
      <span className="inline-flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
        {label && <span className="uppercase tracking-wider">{label}</span>}
        <span className="tabular-nums">—</span>
      </span>
    );
  }
  // Workbench palette: lime accent reserved for affordances, so we
  // tone the badge background instead. The exact thresholds match
  // the judge prompt's anchor ("a 5 means no flaws; most outputs
  // should land 3-4").
  const tone =
    value >= 4
      ? "text-emerald-300"
      : value >= 3
      ? "text-foreground"
      : value >= 2
      ? "text-amber-300"
      : "text-rose-300";
  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-xs">
      {label && (
        <span className="uppercase tracking-wider text-muted-foreground">
          {label}
        </span>
      )}
      <span className={`tabular-nums ${tone}`}>
        {value.toFixed(2)}
        {showDenominator && (
          <span className="ms-1 text-muted-foreground">/ 5</span>
        )}
      </span>
    </span>
  );
}
