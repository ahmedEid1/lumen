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
  // tone the badge text via semantic tokens — success/warning/
  // destructive — instead of raw Tailwind hues that would break
  // light mode and fight the surface ramp. The exact thresholds
  // match the judge prompt's anchor ("a 5 means no flaws; most
  // outputs should land 3-4"). Loop 14 swapped the prior
  // text-emerald-300/amber-300/rose-300 literals to these tokens.
  const tone =
    value >= 4
      ? "text-success"
      : value >= 3
      ? "text-foreground"
      : value >= 2
      ? "text-warning"
      : "text-destructive";
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
