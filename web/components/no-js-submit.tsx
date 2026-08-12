"use client";

// A submit button that exists until the client proves it is not needed.
//
// It replaces a `<noscript>` wrapper, which covered strictly less. `<noscript>`
// renders only when scripting is DISABLED — so it does nothing in the two cases
// that actually happen: the seconds before hydration on a slow device, and a
// client bundle that loaded and then threw. In both, scripting is enabled, the
// noscript content is absent, and `AutoSubmitSelect`'s handlers are not
// attached: the space picker has no working control at all, and the operator
// cannot switch spaces. Before this change the button was always present and
// submitted natively, so that was a regression, not a pre-existing gap.
//
// Rendered server-side, removed once hydration succeeds. The button is in the
// HTML for everyone; it disappears only as the proof arrives that something
// better has taken over.
import * as React from "react";

/** The store never changes, so this never re-subscribes. The whole mechanism is
 *  the SNAPSHOT PAIR below, not the subscription. */
const subscribe = () => () => {};

/** `useSyncExternalStore` rather than an effect that calls setState: this is the
 *  documented way to render one thing on the server and another after
 *  hydration, and it is the only one that does not trip
 *  `react-hooks/set-state-in-effect` or risk a hydration mismatch warning.
 *  React uses the server snapshot through hydration, then swaps. */
function useHydrated(): boolean {
  return React.useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
}

export function NoJsSubmit({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  if (useHydrated()) return null;
  return (
    <button type="submit" className={className}>
      {children}
    </button>
  );
}
