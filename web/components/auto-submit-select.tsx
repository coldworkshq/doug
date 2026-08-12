"use client";

// A <select> that submits its form when its value changes.
//
// This exists as its own file for one reason: app/dashboard/page.tsx may not
// contain a client boundary (lib/dashboard-contract.test.mjs, RULING 2), and
// the scope picker must STAY in that file — its focus ring and its
// aria-label are pinned there, on the grounds that the control which changes
// whose data you are looking at has to be visibly focusable. So the smallest
// possible piece moves: the element that needs an event handler, and nothing
// else. Every other prop is forwarded untouched.
import * as React from "react";

export function AutoSubmitSelect({
  onChange,
  ...props
}: React.ComponentProps<"select">) {
  return (
    <select
      {...props}
      onChange={(event) => {
        // Any caller-supplied handler runs first and can still preventDefault.
        onChange?.(event);
        if (event.defaultPrevented) return;
        // requestSubmit(), not submit(): it fires the submit event, which is
        // what React needs to run the server action bound to the form. Raw
        // submit() bypasses it and would post the form as a plain HTML POST.
        event.currentTarget.form?.requestSubmit();
      }}
    />
  );
}
