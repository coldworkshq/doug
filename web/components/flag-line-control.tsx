import {
  setDeepReadAction,
  setFlagLineAction,
  setFlagLineCommentAction,
} from "@/app/dashboard/actions";

/** Hung off a 210px table cell: absolutely positioned, and sized to its own
 *  content rather than to the column, so the open form can be wider than the
 *  cell it belongs to. */
const CELL_PANEL =
  "absolute z-10 mt-1 flex w-max max-w-[360px] flex-col gap-2.5 rounded-[5px] " +
  "border border-border bg-card p-2 shadow-[0_10px_28px_-10px_rgba(0,0,0,.22)]";

/** On /dashboard/settings the panel already has the width and floats above
 *  nothing, so it takes no border, no shadow, no z-index and no absolute
 *  position. */
const PAGE_PANEL = "flex max-w-[560px] flex-col gap-3";

/** The per-repository FLAG LINE — Doug's setting, not the preview gear.
 *
 *  Server-rendered, no client boundary: a <details>, two <form>s and a server
 *  action. The gear beside it needs JavaScript because a Radix popover and
 *  slider do; this does not, and a setting that silently stops working when a
 *  bundle fails to load is worse than one that never needed the bundle.
 *
 *  FORWARD-ONLY, and the copy says so where the change is made. The API writes
 *  the line for future scoring runs only — verdicts already recorded keep the
 *  line they were scored against (it is stamped per row), and an open PR keeps
 *  its existing check until a new commit triggers a re-review. Stating that in
 *  a tooltip somewhere else would leave the person who just moved the number
 *  believing the table in front of them was about to move with it.
 *
 *  Unset prints BOTH defaults, because production scores with the reader
 *  (DOUG_READER_THRESHOLD) and falls back to the deterministic line
 *  (DOUG_THRESHOLD); one number would be a claim that is false half the time.
 *  Both arrive from the API, so this component never guesses either.
 *
 *  TWO FORMS, NOT TWO SUBMIT BUTTONS — the opposite of the threshold gear, and
 *  deliberately. A named submit button contributes its entry AT ITS OWN
 *  POSITION without replacing anything else, so a "reset" button sharing
 *  `needs_you_threshold` with the number input above it would submit both, and
 *  `formData.get` takes the first: pressing reset on a repository set to 0.75
 *  would have re-saved 0.75 and reported success. The gear can own its field
 *  from two buttons because it has no input; this one cannot, so clearing gets
 *  a form of its own where nothing else can travel.
 *
 *  THE PR COMMENT TOGGLE IS THE THIRD FORM, for that same reason and no other.
 *  It posts `pr_comment` and the repository id and nothing else: sharing a form
 *  with the input above would submit `needs_you_threshold` alongside it, and
 *  `formData.get` takes the first entry — so every toggle click would re-save
 *  whatever the flag-line box happened to hold, including an empty box, which
 *  clears the override. The API's PATCH is field-set-gated on the same
 *  principle: it writes the keys the body names and leaves the rest alone.
 *
 *  THE DEEP READ TOGGLE IS THE FOURTH FORM, and the most consequential of the
 *  four. It is the only control here that changes WHICH SCORER RUNS, and on a
 *  repository with no flag line of its own it moves the band with it: unset,
 *  Doug uses the reader default on a deep read and the deterministic default
 *  when the reader did not run, so switching the read off switches the line
 *  too. Stating one without the other would let someone turn off "the AI bit"
 *  and silently halve how often Doug asks for a human. The copy says both, and
 *  says the second only when it is true of THIS repository.
 *
 *  TWO LAYOUTS, ONE COPY OF THE PROSE. `cell` is the repositories table's
 *  collapsed disclosure; `page` is /dashboard/settings, where the controls are
 *  the content and a click to reveal them would sit in front of the only thing
 *  on the screen. Only the box changes — every word inside it is shared,
 *  because both surfaces describe the same forward-only write and a second
 *  copy of that promise would drift the first time one was edited. */
/** One boolean setting, as a switch you can read without pressing it.
 *
 *  BOTH CARRIERS, because neither alone is enough. The track's position says
 *  the state at a glance; the word beside it says the same thing in text, for
 *  anyone who cannot pick a 28px track's fill out of a light surface and for
 *  anyone reading by ear. The button that shipped first had only the word, in
 *  a bordered box that looked exactly like the `save` and `reset to default`
 *  buttons next to it — three identical-looking controls where one was a state
 *  and two were actions.
 *
 *  IT IS A `<button type="submit">`, not an input, and that is what keeps this
 *  component free of JavaScript: the form posts, the server writes, the page
 *  re-renders with the new state. `role="switch"` + `aria-checked` is the ARIA
 *  pattern for exactly this — a control that reports a state and toggles it —
 *  so screen readers announce "switch, on" rather than "button".
 *
 *  IT READS THE CURRENT STATE AND SUBMITS THE OPPOSITE. The hidden input
 *  carries the negation; the label never shows the pending value. On a control
 *  whose whole job is "what is Doug allowed to do on my repository", showing
 *  the value you are about to get is the one error that matters.
 *
 *  ITS OWN <form>, always. `formData.get` returns the first entry for a name,
 *  so a switch sharing a form with the flag-line input would re-save that box
 *  on every press — including an empty box, which clears the override. */
function SettingSwitch({
  action,
  githubRepoId,
  name,
  label,
  on,
}: {
  action: (formData: FormData) => Promise<void>;
  githubRepoId: number;
  name: string;
  label: string;
  on: boolean;
}) {
  return (
    <form action={action}>
      <input type="hidden" name="github_repo_id" value={githubRepoId} />
      <input type="hidden" name={name} value={on ? "false" : "true"} />
      <button
        type="submit"
        role="switch"
        aria-checked={on}
        aria-label={`${label} is ${on ? "on" : "off"} — turn it ${on ? "off" : "on"}`}
        className="flex cursor-pointer items-center gap-2.5 rounded-[4px] border-0 bg-transparent p-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color-mix(in_srgb,var(--iridescent)_35%,transparent)]"
      >
        {/* --foreground, not the accent: the accent is a hair off --flag on
            this surface, and a control that is not about a verdict must not
            borrow the colour that is. */}
        <span
          aria-hidden
          className={`relative flex h-[16px] w-[28px] flex-none items-center rounded-full border transition-colors ${
            on ? "border-foreground bg-foreground" : "border-border bg-muted"
          }`}
        >
          <span
            className={`block size-[10px] rounded-full transition-transform ${
              on ? "translate-x-[15px] bg-background" : "translate-x-[2px] bg-muted-foreground"
            }`}
          />
        </span>
        <span className="mono text-[10.5px] uppercase tracking-[.08em] text-muted-foreground">{label}</span>
        <span className={`mono text-[10.5px] ${on ? "font-medium text-foreground" : "text-muted-foreground"}`}>
          {on ? "on" : "off"}
        </span>
      </button>
    </form>
  );
}

export function FlagLineControl({
  githubRepoId,
  value,
  prComment,
  defaults,
  deepRead,
  layout = "cell",
}: {
  githubRepoId: number;
  value: number | null;
  prComment: boolean;
  deepRead: boolean;
  defaults: { reader: number; fallback: number };
  layout?: "cell" | "page";
}) {
  const shown =
    value === null
      ? `default · ${defaults.reader.toFixed(2)} deep read / ${defaults.fallback.toFixed(2)} fallback`
      : value.toFixed(2);

  /** One setting: its controls, then the words that explain them.
   *
   *  CONTROL FIRST, PROSE SECOND, three times. Before this the panel was a
   *  flat run — prose, controls, prose, control, prose, prose — and on the
   *  settings page, where every block is open at once, nothing said which
   *  sentence belonged to which button. The PR-comment toggle sitting in the
   *  flag line's own row read as part of the flag line. Grouping is the fix,
   *  and it is the same grouping in the popover: a reader who learns the
   *  shape on one surface should not have to relearn it on the other. */
  const setting = (control: React.ReactNode, prose: React.ReactNode) => (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-2">{control}</div>
      {prose}
    </div>
  );

  const panel = (
    <div className={layout === "page" ? PAGE_PANEL : CELL_PANEL}>
      {setting(
        <>
          <form action={setFlagLineAction} className="flex items-center gap-2">
            <input type="hidden" name="github_repo_id" value={githubRepoId} />
            <label className="mono text-[10.5px] uppercase tracking-[.08em] text-muted-foreground">
              flag line
              <input
                name="needs_you_threshold"
                type="number"
                min={0}
                max={1}
                step={0.01}
                defaultValue={value ?? ""}
                list={`flag-line-marks-${githubRepoId}`}
                /* 88, not 72: a `type="number"` reserves room for its spinner
                   arrows, so a four-character value like 0.75 measured 76px of
                   content in a 72px box and rendered as "0.7". THE ONE CONTROL
                   ON THIS PANEL THAT HAS A VALUE RATHER THAN A STATE cannot be
                   the one that hides it — every other setting here is a switch
                   you can read at a glance, and a clipped number is worse than
                   no number because it looks like a number. */
                className="mono ml-2 h-[26px] w-[88px] rounded-[4px] border border-border bg-card px-1.5 text-[12px] text-foreground"
              />
              {/* The defaults as MARKS, never as a prefilled value: an input
                  showing 0.30 on an unset repository would claim a setting that
                  does not exist, which is the one thing this row must not say. */}
              <datalist id={`flag-line-marks-${githubRepoId}`}>
                <option value={defaults.reader} label="deep read default" />
                <option value={defaults.fallback} label="fallback default" />
              </datalist>
            </label>
            <button type="submit" className="mono h-[26px] rounded-[4px] border border-border px-2 text-[11px]">save</button>
          </form>
          <form action={setFlagLineAction}>
            <input type="hidden" name="github_repo_id" value={githubRepoId} />
            <input type="hidden" name="needs_you_threshold" value="" />
            <button type="submit" className="mono h-[26px] rounded-[4px] border border-border px-2 text-[11px] text-muted-foreground">reset to default</button>
          </form>
        </>,
        <>
          <p className="text-[10.5px] text-muted-foreground">
            One line for both scorers. Unset, Doug uses {defaults.reader.toFixed(2)} on deep reads and {defaults.fallback.toFixed(2)} when the reader didn&apos;t run.
            Applies to reviews from now on — past verdicts keep the line they were scored against, and open PRs keep their check until a new commit.
            {value !== null && value >= 0.9 && " Close to flag-nothing on the fallback scorer."}
          </p>
          {/* Only where the gear actually is. On /dashboard/settings there is
              no preview gear, and copy naming a control that is not on the
              screen sends the reader hunting for it. The distinction the
              sentence draws still holds there — it is just not the confusion
              that surface has. */}
          {layout === "cell" && (
            <p className="text-[10.5px] text-muted-foreground">
              This is Doug&apos;s line for new reviews — the preview gear above only re-bands what&apos;s on screen.
            </p>
          )}
        </>,
      )}

      {/* The button READS the current state and SUBMITS the opposite. A
          label showing the pending value would tell whoever is looking at
          this repository the wrong thing about it, which on a setting whose
          whole job is "does Doug speak on my PRs" is the one error that
          matters. `aria-label` spells the action out, because "PR comment ·
          on" alone does not say what pressing it does. */}
      {setting(
        <SettingSwitch
          action={setFlagLineCommentAction}
          githubRepoId={githubRepoId}
          name="pr_comment"
          label="PR comment"
          on={prComment}
        />,
        /* BOTH DIRECTIONS, because the decision is made here. On is an edit
           loop; off is a STOP, not an undo — D3: turning it off ends the
           updates and leaves the last comment where Doug posted it. Stating
           only the on-state would let someone switch this off expecting the
           comment to disappear, which is the reading the flag-line paragraph
           above already refuses to allow about itself.

           There is no rollout sentence any more. It existed while
           `DOUG_PR_COMMENT_INSTALLATIONS` (D3a) could hold a space dark with
           this toggle reading "on" and no denial banner to explain it, and it
           went with the allowlist in #144. Do not reinstate copy hedging what
           this control does: the toggle is now the only thing that decides,
           and saying otherwise would be the D8 dishonesty in reverse. */
        <p className="text-[10.5px] text-muted-foreground">
          On, Doug mirrors each verdict into one comment on the pull request and edits that same comment on every later review — it never adds a second one.
          Off, Doug stops updating the comment; the last one it posted stays where it is.
        </p>,
      )}

      {/* The fourth form, and the only one that changes which scorer runs. Its
          own <form> for the same reason the two toggles above have one:
          `formData.get` takes the first entry for a name, so sharing a form
          with the flag-line input would re-save that box on every click. */}
      {setting(
        <SettingSwitch
          action={setDeepReadAction}
          githubRepoId={githubRepoId}
          name="deep_read"
          label="Deep read"
          on={deepRead}
        />,
        /* BOTH CONSEQUENCES, the second one conditionally, because it is only
           true of a repository with no line of its own. A repo that has set
           0.75 keeps 0.75 through this toggle, and telling its owner the line
           is about to move would be the same lie in the other direction.

           AND IN THE RIGHT TENSE. On a repository where the read is ALREADY
           off, the line has already moved — describing what turning it off
           "would" do reads as a warning about a future the reader is standing
           in, and invites them to think the band is still the reader's. Two
           sentences, one per state, rather than one sentence that is wrong
           half the time. */
        <p className="text-[10.5px] text-muted-foreground">
          On, Doug sends the diff to the reader and scores what it finds. Off, no diff leaves your repository — Doug scores on
          structural signals alone and records no findings.
          {value === null &&
            (deepRead
              ? ` Because this repository has no flag line of its own, turning the read off also moves the line Doug bands against, from ${defaults.reader.toFixed(2)} to ${defaults.fallback.toFixed(2)} — so Doug asks for a human less often, not just differently.`
              : ` Because this repository has no flag line of its own, the line Doug bands against moved with the read: it is banding at ${defaults.fallback.toFixed(2)} rather than ${defaults.reader.toFixed(2)}, so it is asking for a human less often here than it would with the read on.`)}
        </p>,
      )}

      {/* Not attached to any one control: it is true of all three, and the
          third rule Doug is built on. Route, never block. */}
      <p className="text-[10.5px] text-muted-foreground">
        Doug routes either way: every pull request still gets a check run, and no setting here blocks a merge.
      </p>
    </div>
  );

  // Flat on the settings page. The readout survives the disclosure it was
  // attached to, because an unset repository has an EMPTY number box — and an
  // empty box is not the same statement as
  // "default · 0.30 deep read / 0.62 fallback".
  if (layout === "page") {
    return (
      <div className="flex flex-col gap-1.5">
        <p className="mono text-[12px] text-muted-foreground">{shown}</p>
        {panel}
      </div>
    );
  }

  return (
    // `relative` is load-bearing: it makes this <details> the containing block
    // for the panel below, which is absolutely positioned so the open form can
    // be wider than the 210px table column it lives in. Laid out inside the
    // cell, the label + input + save + reset row wrapped into four lines.
    <details className="group relative">
      {/* The accessible name carries the VALUE as well as the word, because the
          value is the whole point of the row: a bare aria-label="flag line"
          would replace "default · 0.30 deep read / 0.62 fallback" for anyone
          reading by ear, leaving them a control whose current setting they
          cannot hear.

          COLLAPSED, THIS IS ONE LINE. The unset summary is ~40 monospace
          characters and the column is 210px, so without `truncate` it wrapped
          to three lines and pushed every other cell in the row down. `title`
          carries the full string for the mouse; `aria-label` already carried
          it for the ear; opening the disclosure carries it for everyone else.
          The marker rule matches the repo's other two <details>. */}
      <summary
        className="mono cursor-pointer list-none truncate text-[12px] text-muted-foreground hover:text-foreground [&::-webkit-details-marker]:hidden"
        aria-label={`flag line — ${shown}`}
        title={shown}
      >
        {shown}
      </summary>
      {panel}
    </details>
  );
}
