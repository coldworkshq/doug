"use client";

// Route-level boundary for both / and /queue. Before it existed, any
// render-time throw fell through to Next's unstyled default error screen —
// no branding, no explanation, no retry. Doug's whole pitch is saying so
// when something is wrong; the error page is not exempt.
export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col items-center justify-center px-6 text-center">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
        Something broke
      </p>
      <h1 className="font-heading mt-4 max-w-md text-4xl font-semibold tracking-tight">
        This page failed to render.
      </h1>
      <p className="mt-4 max-w-sm text-sm leading-relaxed text-muted-foreground">
        The queue and the ledger are unaffected — this is the dashboard
        tripping over itself, and it says so instead of pretending.
        {error.digest ? ` Reference: ${error.digest}.` : ""}
      </p>
      <button
        onClick={reset}
        className="mt-8 rounded-full bg-primary px-6 py-3 text-sm font-medium text-primary-foreground transition-transform hover:-translate-y-0.5"
      >
        Try again
      </button>
    </main>
  );
}
