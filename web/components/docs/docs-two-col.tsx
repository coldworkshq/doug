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
      {/* min-w-0 matters MOST below lg, where this stops being a column and
          becomes the second row of a single-column grid. As a grid item its
          min-width:auto resolves to min-content, and CodeBlock's <pre> is a
          long unwrapped terminal line — so the implicit column stretched to
          the widest line (462px in a 375px viewport) and dragged the prose
          <article> out with it, clipping body copy off the right edge on
          every phone. The <pre>'s own overflow-x-auto could never engage,
          because nothing above it would shrink. */}
      <div className="min-w-0 space-y-4 lg:sticky lg:top-28">{rail}</div>
    </div>
  );
}
