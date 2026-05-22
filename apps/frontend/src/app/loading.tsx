/**
 * Workbench top-level loading state.
 *
 * Uses the `skeleton` utility (single subtle fade, no shimmer sweep) at
 * a layout that roughly mirrors a typical catalogue surface — a title
 * bar, a subtitle row, then a 3-column card grid. Skeleton sits on
 * surface-2 (muted) so the geometry matches a real bordered card.
 */
export default function Loading() {
  return (
    <div className="container mx-auto px-6 py-10">
      <div className="space-y-3">
        <div className="skeleton h-8 w-1/3" />
        <div className="skeleton h-4 w-1/2" />
        <div className="grid gap-4 pt-6 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="skeleton h-72" />
          ))}
        </div>
      </div>
    </div>
  );
}
