"use client";

/**
 * L26 — Sparkline for eval suite trends.
 *
 * Pure SVG, no chart library. Workbench aesthetic = minimal,
 * monochromatic — a 64×16 line with a single point per data row.
 *
 * The data shape is `{ value, label? }[]` so callers can pass
 * either pre-computed scores or richer rows. Values outside [0, 5]
 * are clamped (eval scores are bounded; callers don't need to
 * normalize themselves).
 *
 * Accessibility: the component emits a `<title>` element with a
 * spoken summary ("mean score over last 5 runs: 3.85, 4.10, ..."),
 * so screen-readers don't get a silent SVG.
 */

interface SparklineDatum {
  value: number;
  label?: string;
}

export interface SparklineProps {
  data: SparklineDatum[];
  /** Min and max of the axis; defaults to [0, 5] (eval score range). */
  range?: [number, number];
  className?: string;
  ariaLabel?: string;
}

const W = 64;
const H = 16;
const PAD = 1.5;

export function Sparkline({
  data,
  range = [0, 5],
  className,
  ariaLabel,
}: SparklineProps) {
  if (data.length === 0) {
    return (
      <div
        className={
          "inline-flex h-4 w-16 items-center text-[10px] text-muted-foreground/40 " +
          (className ?? "")
        }
        aria-label={ariaLabel ?? "No trend yet"}
        title={ariaLabel ?? "No trend yet"}
      >
        ——
      </div>
    );
  }

  const [lo, hi] = range;
  const span = Math.max(hi - lo, 1e-6);
  const innerW = W - 2 * PAD;
  const innerH = H - 2 * PAD;

  // X-positions: evenly spaced across the inner width.
  const denom = Math.max(data.length - 1, 1);
  const points: { x: number; y: number; v: number }[] = data.map((d, i) => {
    const clamped = Math.min(hi, Math.max(lo, d.value));
    const x = PAD + (i / denom) * innerW;
    const y = PAD + innerH - ((clamped - lo) / span) * innerH;
    return { x, y, v: clamped };
  });

  // SVG path "M x y L x y L x y ...".
  const path = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`)
    .join(" ");

  const title =
    ariaLabel ??
    `Recent scores: ${data.map((d) => d.value.toFixed(2)).join(", ")}`;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width={W}
      height={H}
      className={"inline-block " + (className ?? "")}
      role="img"
      aria-label={title}
    >
      <title>{title}</title>
      <path
        d={path}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {points.length > 0 && (
        <circle
          cx={points[points.length - 1].x}
          cy={points[points.length - 1].y}
          r={1.6}
          fill="currentColor"
        />
      )}
    </svg>
  );
}
