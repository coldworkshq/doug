"use client";

import { useState } from "react";
import { PawPrint } from "lucide-react";

// Mixes real dog trivia with claims pulled straight from the README/landing
// page (the AUC numbers, the three rules) so this stays a fact list, not a
// joke list dressed up as one. If those source numbers change, update here
// too — this has no test pinning it to them.
const FACTS = [
  "Saint Bernards take their name from the Great St Bernard Hospice, a pass through the Alps monks have staffed since the 11th century.",
  "The brandy keg on the collar is mostly a 19th-century painting's invention — real rescue dogs never carried one. The logo kept it anyway.",
  "The most famous Saint Bernard, Barry, is credited with saving around 40 people in the early 1800s. He's stuffed and on display in Bern.",
  "This particular Doug has never located a buried traveler. His current job is guarding the back of the couch.",
  "Rule two: Doug never writes code and never opens a PR. The moment it authors, it owns the authorship.",
  "Doug's first pre-registered test scored 0.69 ranking AUC on sentry, before a single model call — the best deterministic baseline scored 0.59.",
  "Diff size is deliberately de-weighted in the scoring. A big PR doesn't automatically look scarier to Doug than a small one.",
  "The whole bet is that cheap structural features catch a disproportionate share of bad changes. If they don't, the project says so and stops.",
] as const;

/** A deliberately backend-free "get involved" toy: cycles a fixed fact list
 *  on click. No fetch, no persisted state — the one thing on this page that
 *  needs "use client" is exactly this, and nothing else on the page pulls
 *  it in. */
export function DougFactButton() {
  const [factIndex, setFactIndex] = useState<number | null>(null);

  function next() {
    setFactIndex((prev) => {
      if (FACTS.length <= 1) return 0;
      let candidate = Math.floor(Math.random() * FACTS.length);
      while (candidate === prev) {
        candidate = Math.floor(Math.random() * FACTS.length);
      }
      return candidate;
    });
  }

  return (
    <div className="flex grow flex-col">
      <p className="min-h-10 grow text-sm leading-relaxed text-muted-foreground">
        {factIndex === null
          ? "One click, one fact — about the dog, or the product."
          : FACTS[factIndex]}
      </p>
      <button
        type="button"
        onClick={next}
        className="mt-4 inline-flex w-fit items-center gap-1.5 rounded-full bg-primary px-4 py-2 text-xs font-medium text-primary-foreground transition-transform hover:-translate-y-0.5"
      >
        <PawPrint className="size-3.5" />
        {factIndex === null ? "Ask Doug something" : "Another one"}
      </button>
    </div>
  );
}
