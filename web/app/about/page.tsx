import type { Metadata } from "next";

import { BrandMark } from "@/components/brand-mark";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { GITHUB_REPO_SLUG, GITHUB_REPO_URL } from "@/lib/links";

/** The company page. Until the 2026-09-23 naming ruling it was the dog's page
 *  (the product was named after a Saint Bernard); the ruling retired the dog
 *  with the name, and the founder ruled this page be rewritten about
 *  Coldworks. Every sentence below is taken from material already public:
 *  the thesis, the door's own copy (public/landing.html), and the three rules
 *  from the README, word for word. Nothing here states a customer, a team
 *  size, a price, or a comparison, and nothing should: this repo is public. */
export const metadata: Metadata = {
  title: "About — Coldworks",
  description:
    "What Coldworks is, the three rules its reviews run by, and how to get involved.",
};

// The three rules, word for word from the README. They survived the rename
// unchanged except for the name (2026-09-23 naming ruling, item 6).
const RULES = [
  {
    title: "Route, never block.",
    body: "The PR proceeds either way. Coldworks only decides who has to look. Tools that block get disabled.",
  },
  {
    title: "Never write code, never open a PR.",
    body: "The moment it authors, it owns the authorship.",
  },
  {
    title: "Publish the miss rate.",
    body: "Every quarter, including the incidents that came from PRs it cleared. A gate that never publishes its errors is a marketing claim; one that does can survive being wrong. The scoreboard is live; the miss-rate number is not yet.",
  },
] as const;

// GitHub's issue-compose prefill (?title=&body=) — no API call, no stored
// template, just a URL. If the repo ever adds a real issue template this
// can point at it with &template=story.md instead.
const storyIssueUrl = new URL(`${GITHUB_REPO_URL}/issues/new`);
storyIssueUrl.searchParams.set("title", "A PR that needed a human");
storyIssueUrl.searchParams.set(
  "body",
  "**What happened**\n\n\n**What Coldworks would have seen (if you know)**\n\n\n**Repo (optional)**\n",
);
const STORY_ISSUE_URL = storyIssueUrl.toString();

export default function AboutPage() {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto w-full max-w-5xl px-6">
        <section className="py-20 md:py-24">
          <p className="animate-rise panel inline-flex items-center gap-2 rounded-full px-3 py-1 font-mono text-xs text-muted-foreground">
            <BrandMark size={14} /> about
          </p>
          <h1
            className="animate-rise font-heading mt-6 max-w-2xl text-5xl leading-[1.02] font-semibold tracking-tight md:text-6xl"
            style={{ animationDelay: "80ms" }}
          >
            Repeated judgment, <span className="text-molten">compiled</span>.
          </h1>
          <p
            className="animate-rise mt-6 max-w-lg text-lg leading-relaxed text-muted-foreground"
            style={{ animationDelay: "160ms" }}
          >
            Coldworks runs agent workflows and compiles the judgments they keep
            repeating into deterministic, guarded code that you own.
          </p>
        </section>

        <section className="pb-16">
          <p className="lbl">
            The first case
          </p>
          <h2 className="font-heading mt-4 max-w-2xl text-3xl leading-tight font-semibold tracking-tight md:text-4xl">
            Most pull requests don&rsquo;t need a human.
          </h2>
          <div className="mt-6 grid gap-4 text-sm leading-relaxed text-muted-foreground md:max-w-2xl">
            <p>
              Coldworks reviews your pull requests, remembers what your team
              decided, and turns the judgments it keeps repeating into checks
              you own.
            </p>
            <p>
              Every pull request gets a verdict: cleared, or needs a reader.
              Coldworks routes attention. It never blocks a merge, never
              writes code, and publishes its own miss rate.
            </p>
            <p>
              Judgments that come back the same every time become guarded,
              tested checks. A maintainer signs each one, and it runs first in
              your CI.
            </p>
          </div>
        </section>

        <section className="pb-16">
          <p className="lbl">
            Three rules, in writing
          </p>
          <div className="hairline-grid mt-6 rounded-lg md:grid-cols-3">
            {RULES.map((r) => (
              <div key={r.title} className="p-8">
                <h3 className="font-heading text-xl font-semibold">{r.title}</h3>
                <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                  {r.body}
                </p>
              </div>
            ))}
          </div>
        </section>

        <section className="pb-20">
          <p className="lbl">
            Get involved
          </p>
          <h2 className="font-heading mt-4 max-w-2xl text-3xl leading-tight font-semibold tracking-tight md:text-4xl">
            Two ways in.
          </h2>

          <div className="mt-10 grid gap-4 md:grid-cols-2">
            <div className="panel flex flex-col rounded-lg p-8">
              <span className="text-coolant font-mono text-sm">01</span>
              <h3 className="font-heading mt-3 text-xl font-semibold">
                Star it
              </h3>
              <p className="mt-3 grow text-sm leading-relaxed text-muted-foreground">
                Coldworks reviews its own pull requests on this repository. A
                star is the cheapest way to say the live path is worth
                hardening for other installs.
              </p>
              <a
                href={GITHUB_REPO_URL}
                className="mt-4 inline-flex w-fit items-center transition-opacity hover:opacity-80"
              >
                <img
                  src={`https://img.shields.io/github/stars/${GITHUB_REPO_SLUG}?style=flat-square&label=stars&color=E0430A`}
                  alt={`GitHub stars for ${GITHUB_REPO_SLUG}`}
                  loading="lazy"
                  className="h-5"
                />
              </a>
            </div>

            <div className="panel flex flex-col rounded-lg p-8">
              <span className="text-coolant font-mono text-sm">02</span>
              <h3 className="font-heading mt-3 text-xl font-semibold">
                Tell us your story
              </h3>
              <p className="mt-3 grow text-sm leading-relaxed text-muted-foreground">
                Had a PR that needed a human and didn&rsquo;t get one? Or one
                Coldworks would have wrongly flagged? Open it as an issue —
                it&rsquo;s the fastest way to argue with the scoring.
              </p>
              <a
                href={STORY_ISSUE_URL}
                className="mt-4 inline-flex w-fit items-center rounded-full bg-primary px-4 py-2 text-xs font-medium text-primary-foreground transition-transform hover:-translate-y-0.5"
              >
                Open an issue
              </a>
            </div>
          </div>
        </section>

        <SiteFooter />
      </main>
    </>
  );
}
