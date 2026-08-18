import type { Metadata } from "next";

import { DougFactButton } from "@/components/about/doug-fact-button";
import { DougLogo } from "@/components/doug-logo";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { GITHUB_REPO_SLUG, GITHUB_REPO_URL } from "@/lib/links";

export const metadata: Metadata = {
  title: "About — Doug",
  description:
    "Why a pull-request router is named after a Saint Bernard, who built it, and how to get involved.",
};

// Four real photos of the real Doug. Filenames are placeholders — drop the
// actual files into web/public/about/doug/ with these exact names and the
// gallery below picks them up with no code change.
const PHOTOS = [
  {
    src: "/about/doug/kitchen-selfie.jpg",
    alt: "Andrew and Doug, nose to nose in the kitchen",
    caption: "Nose to nose in the kitchen.",
  },
  {
    src: "/about/doug/couch-loaf.jpg",
    alt: "Doug loafed over the back of the couch",
    caption: "Off duty, guarding the back of the couch.",
  },
  {
    src: "/about/doug/rock-hike.jpg",
    alt: "Doug and Andrew sitting on rocks after a hike",
    caption: "Post-hike, still working the smile.",
  },
  {
    src: "/about/doug/nose-boop.jpg",
    alt: "Extreme close-up of Doug's nose",
    caption: "The business end.",
  },
] as const;

// GitHub's issue-compose prefill (?title=&body=) — no API call, no stored
// template, just a URL. If the repo ever adds a real issue template this
// can point at it with &template=story.md instead.
const storyIssueUrl = new URL(`${GITHUB_REPO_URL}/issues/new`);
storyIssueUrl.searchParams.set("title", "A PR that needed a human");
storyIssueUrl.searchParams.set(
  "body",
  "**What happened**\n\n\n**What Doug would have seen (if you know)**\n\n\n**Repo (optional)**\n",
);
const STORY_ISSUE_URL = storyIssueUrl.toString();

export default function AboutPage() {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto w-full max-w-5xl px-6">
        <section className="py-20 md:py-24">
          <p className="animate-rise panel inline-flex items-center gap-2 rounded-full px-3 py-1 font-mono text-xs text-muted-foreground">
            <DougLogo size={14} /> about
          </p>
          <h1
            className="animate-rise font-heading mt-6 max-w-2xl text-5xl leading-[1.02] font-semibold tracking-tight md:text-6xl"
            style={{ animationDelay: "80ms" }}
          >
            The dog <span className="text-iridescent">came first</span>.
          </h1>
          <p
            className="animate-rise mt-6 max-w-lg text-lg leading-relaxed text-muted-foreground"
            style={{ animationDelay: "160ms" }}
          >
            Doug the product is named after Doug the dog, not the other way
            around. Here&rsquo;s how that happened, who built it, and how to
            get involved.
          </p>
        </section>

        <section className="pb-16">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
            Origin
          </p>
          <h2 className="font-heading mt-4 max-w-2xl text-3xl leading-tight font-semibold tracking-tight md:text-4xl">
            Saint Bernards have had one job for three centuries.
          </h2>
          <div className="mt-6 grid gap-4 text-sm leading-relaxed text-muted-foreground md:max-w-2xl">
            <p>
              Monks at the Great St Bernard Hospice, high in the Alps between
              Switzerland and Italy, have bred the dogs since the 17th
              century for exactly one task: find the traveler buried in the
              snow, and bring help. They don&rsquo;t dig you out themselves.
              They find you, and they get a person.
            </p>
            <p>
              That&rsquo;s the whole shape of the product, too. Doug
              doesn&rsquo;t fix your code and doesn&rsquo;t hold your merge —
              it finds the pull request that&rsquo;s actually in trouble and
              puts a human in front of it. Everything else clears.
            </p>
            <p>
              This Doug is a real dog, not a mascot invented for the pitch.
              He mostly guards a couch. The metaphor is aspirational.
            </p>
          </div>

          <div className="mt-10 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {PHOTOS.map((p) => (
              <figure
                key={p.src}
                className="panel group overflow-hidden rounded-2xl"
              >
                <img
                  src={p.src}
                  alt={p.alt}
                  loading="lazy"
                  className="aspect-square w-full object-cover transition-transform duration-300 group-hover:scale-105"
                />
                <figcaption className="border-t border-border px-3 py-2 font-mono text-[11px] text-muted-foreground">
                  {p.caption}
                </figcaption>
              </figure>
            ))}
          </div>
        </section>

        <section className="pb-16">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
            Who&rsquo;s behind it
          </p>
          <h2 className="font-heading mt-4 max-w-2xl text-3xl leading-tight font-semibold tracking-tight md:text-4xl">
            Built by one person, for now.
          </h2>
          {/* Draft bio — Andrew, edit or replace freely. Facts as given:
              82nd Airborne Division; 4th Brigade Combat Team (Airborne),
              25th Infantry Division; signals intelligence analyst, then a
              19D cavalry scout; Purdue; now a principal engineer in
              insurtech. */}
          <div className="mt-6 grid gap-4 text-sm leading-relaxed text-muted-foreground md:max-w-2xl">
            <p>
              Andrew served with the 82nd Airborne Division and later the
              4th Brigade Combat Team (Airborne), 25th Infantry Division —
              first as a signals intelligence analyst, then as a 19D cavalry
              scout. Both jobs came down to the same thing: read the
              terrain, work out what actually mattered, and let the rest go.
            </p>
            <p>
              He studied at Purdue afterward and works today as a principal
              engineer in insurtech. Doug is a side project, built at night
              on the same instinct — most pull requests don&rsquo;t need a
              human, so find the ones that do, and say so honestly when
              you&rsquo;re wrong.
            </p>
          </div>
        </section>

        <section className="pb-20">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
            Get involved
          </p>
          <h2 className="font-heading mt-4 max-w-2xl text-3xl leading-tight font-semibold tracking-tight md:text-4xl">
            Three ways in.
          </h2>

          <div className="mt-10 grid gap-4 md:grid-cols-3">
            <div className="panel flex flex-col rounded-2xl p-8">
              <span className="text-iridescent font-mono text-sm">01</span>
              <h3 className="font-heading mt-3 text-xl font-semibold">
                Star it
              </h3>
              <p className="mt-3 grow text-sm leading-relaxed text-muted-foreground">
                Doug is pre-build — a star is the cheapest way to tell us
                it&rsquo;s worth finishing.
              </p>
              <a
                href={GITHUB_REPO_URL}
                className="mt-4 inline-flex w-fit items-center transition-opacity hover:opacity-80"
              >
                <img
                  src={`https://img.shields.io/github/stars/${GITHUB_REPO_SLUG}?style=flat-square&label=stars&color=D1571E`}
                  alt={`GitHub stars for ${GITHUB_REPO_SLUG}`}
                  loading="lazy"
                  className="h-5"
                />
              </a>
            </div>

            <div className="panel flex flex-col rounded-2xl p-8">
              <span className="text-iridescent font-mono text-sm">02</span>
              <h3 className="font-heading mt-3 text-xl font-semibold">
                Ask Doug something
              </h3>
              <DougFactButton className="mt-3" />
            </div>

            <div className="panel flex flex-col rounded-2xl p-8">
              <span className="text-iridescent font-mono text-sm">03</span>
              <h3 className="font-heading mt-3 text-xl font-semibold">
                Tell us your story
              </h3>
              <p className="mt-3 grow text-sm leading-relaxed text-muted-foreground">
                Had a PR that needed a human and didn&rsquo;t get one? Or one
                Doug would have wrongly flagged? Open it as an issue —
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
