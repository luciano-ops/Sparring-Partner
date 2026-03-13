export default function LoadingState() {
  const skeletonCards = Array.from({ length: 8 }, (_, i) => i);

  return (
    <div className="mx-auto max-w-6xl px-6 pb-16">
      <div className="mb-6 flex items-center gap-3">
        <div className="h-5 w-48 rounded bg-border animate-shimmer" />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {skeletonCards.map((i) => (
          <div
            key={i}
            className="rounded-lg border border-border bg-surface p-6"
          >
            <div className="mb-4 flex items-center gap-2">
              <div className="h-4 w-8 rounded bg-border animate-shimmer" />
              <div className="h-4 w-1 rounded bg-border" />
              <div
                className="h-4 w-32 rounded bg-border animate-shimmer"
                style={{ animationDelay: `${i * 0.1}s` }}
              />
            </div>
            <div className="h-px bg-border mb-4" />
            <div className="space-y-2.5">
              <div
                className="h-3 w-full rounded bg-border animate-shimmer"
                style={{ animationDelay: `${i * 0.1 + 0.1}s` }}
              />
              <div
                className="h-3 w-5/6 rounded bg-border animate-shimmer"
                style={{ animationDelay: `${i * 0.1 + 0.2}s` }}
              />
              <div
                className="h-3 w-4/6 rounded bg-border animate-shimmer"
                style={{ animationDelay: `${i * 0.1 + 0.3}s` }}
              />
              <div
                className="h-3 w-3/4 rounded bg-border animate-shimmer"
                style={{ animationDelay: `${i * 0.1 + 0.4}s` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
