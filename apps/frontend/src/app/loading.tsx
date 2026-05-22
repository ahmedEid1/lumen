export default function Loading() {
  return (
    <div className="container mx-auto px-6 py-10">
      <div className="space-y-3">
        <div className="h-8 w-1/3 animate-pulse rounded-md border border-border/60 bg-muted" />
        <div className="h-4 w-1/2 animate-pulse rounded-md border border-border/60 bg-muted" />
        <div className="grid gap-6 pt-6 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="h-72 animate-pulse rounded-md border border-border/60 bg-card/40"
            />
          ))}
        </div>
      </div>
    </div>
  );
}
