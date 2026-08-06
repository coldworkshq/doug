"use client"; // Error boundaries must be Client Components

// Route-level boundary for every console screen. The console's whole
// premise is that it never fabricates a state (see the global "no fixture
// fallback" constraint) — a render crash gets the same honesty: an
// explicit failure, not Next's default blank error page.
//
// unstable_retry, not reset: in this Next version reset() only clears the
// boundary's error state without re-fetching, so it would replay the same
// failed render. unstable_retry() re-fetches and re-renders the segment —
// the only retry that can actually recover from a failed runs/verdict
// fetch. (Confirmed against node_modules/next/dist/docs — see task report.)
export default function ErrorPage({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  return (
    <main className="mx-auto flex min-h-[70vh] w-full max-w-lg flex-col items-center justify-center px-5 text-center">
      <p className="mono text-xs uppercase tracking-[.16em] text-muted-foreground">
        console error
      </p>
      <h1 className="font-heading mt-3 text-xl font-semibold tracking-tight">
        This screen failed to render.
      </h1>
      <p className="mt-3 max-w-sm text-sm leading-relaxed text-muted-foreground">
        Nothing shown here is invented — this is the console tripping over
        itself, and it says so instead of guessing.
        {error.digest ? ` Reference: ${error.digest}.` : ""}
      </p>
      <button
        onClick={() => unstable_retry()}
        className="mono mt-6 rounded-[5px] border border-border bg-card px-4 py-2 text-xs uppercase tracking-[.08em] transition-colors hover:border-[var(--iridescent)]"
      >
        Try again
      </button>
    </main>
  );
}
