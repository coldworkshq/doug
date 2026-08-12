"use client";

// A <select> that navigates when you choose an option — on pointer input
// immediately, on keyboard input only once you commit.
//
// This exists as its own file for one reason: app/dashboard/page.tsx may not
// contain a client boundary (lib/dashboard-contract.test.mjs, RULING 2), and
// the scope picker must STAY in that file — its focus ring and its aria-label
// are pinned there, on the grounds that the control which changes whose data
// you are looking at has to be visibly focusable. So the smallest possible
// piece moves: the element that needs event handlers, and nothing else.
//
// WHY THE KEYBOARD PATH IS DIFFERENT, and it is not an optimisation: on a
// closed native <select>, browsers fire `change` on every ArrowUp/ArrowDown and
// every type-ahead character. Submitting on each one navigates the page out
// from under a keyboard user on their FIRST keystroke, before they reach the
// option they were aiming for — WCAG 3.2.2 (On Input). Arrowing is browsing,
// not choosing. So a change that arrived by keyboard is held until the user
// says they mean it: Enter, Tab, or leaving the control.
import * as React from "react";

/** Keys that MOVE the selection without committing to it. Enter and Tab are
 *  deliberately absent — those are the commit gestures. */
const BROWSING_KEYS = new Set([
  "ArrowUp",
  "ArrowDown",
  "ArrowLeft",
  "ArrowRight",
  "Home",
  "End",
  "PageUp",
  "PageDown",
]);

export function AutoSubmitSelect({
  onChange,
  onKeyDown,
  onBlur,
  onPointerDown,
  ...props
}: React.ComponentProps<"select">) {
  // The last input was a key that browses the list. Says nothing about whether
  // the selection moved — only `change` knows that.
  const browsing = React.useRef(false);
  // A real, uncommitted change arrived by keyboard. Refs, not state: nothing
  // renders differently, and a re-render between the keystroke and the commit
  // would be a wasted pass.
  const pending = React.useRef(false);

  // requestSubmit(), not submit(): it fires the submit event, which is what
  // React needs to run the server action bound to the form. Raw submit()
  // bypasses it and would post as a plain HTML POST.
  const commit = (element: HTMLSelectElement) => {
    pending.current = false;
    browsing.current = false;
    element.form?.requestSubmit();
  };

  return (
    <select
      {...props}
      onKeyDown={(event) => {
        onKeyDown?.(event);
        if (event.defaultPrevented) return;
        if (event.key === "Enter") {
          // A <select> in a form does not re-fire `change` on Enter, so without
          // this an arrowed-to choice would sit unsubmitted until focus moved.
          if (pending.current) commit(event.currentTarget);
          return;
        }
        // Arrows, Home/End/PageUp/PageDown, and type-ahead (a single printable
        // character, which includes the Space that opens the popup). This only
        // marks HOW the next change arrives — it never arms a commit by itself,
        // because a key that moves nothing produces no change to commit.
        if (BROWSING_KEYS.has(event.key) || event.key.length === 1) {
          browsing.current = true;
        }
      }}
      onPointerDown={(event) => {
        onPointerDown?.(event);
        if (event.defaultPrevented) return;
        // A pointer interaction supersedes a stale keyboard flag — otherwise
        // opening the popup with Space and then clicking an option would defer
        // a plainly-pointer choice all the way to blur.
        browsing.current = false;
      }}
      onChange={(event) => {
        // Any caller-supplied handler runs first and can still preventDefault.
        onChange?.(event);
        if (event.defaultPrevented) return;
        if (browsing.current) {
          // Arrowing IS browsing. Hold the choice until the user says they mean
          // it — Enter, Tab, or leaving the control. Committing here navigates
          // the page out from under them on their first keystroke (WCAG 3.2.2).
          pending.current = true;
          return;
        }
        commit(event.currentTarget);
      }}
      onBlur={(event) => {
        onBlur?.(event);
        if (event.defaultPrevented) return;
        // Tab and click-away both land here. A keyboard choice the user walked
        // away from is still a choice they made — but only if they actually
        // made one, which is why this reads `pending` and not `browsing`.
        if (pending.current) commit(event.currentTarget);
      }}
    />
  );
}
