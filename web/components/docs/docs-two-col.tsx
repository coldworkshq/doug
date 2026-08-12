import type { ReactNode } from "react";

/** The "Stripe two-col" layout the gh-pages docs source's own CSS comment
 *  named: prose on the left, a sticky code/output rail on the right. Pages
 *  with no meaningful example (Changelog) just pass no `rail` and get a
 *  single flowing column instead of an empty second one. */
export function DocsTwoCol({
  prose,
  rail,
}: {
  prose: ReactNode;
  rail?: ReactNode;
}) {
  if (!rail) {
    return <article className="max-w-[46rem]">{prose}</article>;
  }
  return (
    <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_26rem] lg:items-start lg:gap-12">
      <article className="min-w-0 max-w-[46rem]">{prose}</article>
      <div className="space-y-4 lg:sticky lg:top-28">{rail}</div>
    </div>
  );
}
