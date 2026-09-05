# HANDOFF — doug

State:    review — PR #314 open off main a8e015f, branch
          `claude/doug-deterministic-checks-d81757`, closing #307 and #232.
          api 1887 pass, ruff clean, four guard mutations each red.
Next:     Andrew reviews and merges #314, then checks main carries the
          branch tip (squash merges have dropped the last commit before).
          Remaining survey issues, in the order recommended: #308 (evidence
          class at emit time), #303 (exclude generated content), #304
          (same-hunks replay), then #306 + #199.
Blockers: none.

Decisions this session (2026-09-04):
- Ten deterministic-check issues filed: #303–#312. #307 is this one;
  #199 (verify candidates) and #203 (one client per drain) already existed.
- Ground truth is `checks.list_for_ref` at head_sha plus the workflow YAML
  at head (both under permissions Doug already holds) — rejected: the
  Actions jobs API (needs `actions: read`, an R11 org click; would have
  been cleaner because step names carry the command).
- Stdlib-only YAML-subset parser in `ci_evidence.py`; any job it cannot
  name is skipped, so a parse miss keeps findings — rejected: PyYAML
  (shipped code stays on stdlib).
- A falsifier kind is green only when EVERY job running it is green, and
  it covers a file only through a root (working-directory / --workspace)
  the command ran over — rejected: any-green (a green `web` build would
  settle a finding in `console/`).
- Ruff class vetoes, each from REVIEWING.md's boundary table: name read at
  runtime, not TYPE_CHECKING-bound, no F821-silencing noqa, F821 selected
  by nearest config (tomllib walk, ruff precedence), "before" claims out.
- JS class needs lint AND build green over the file — rejected: either
  (the claim names one gate loosely; both means never resting on a gate
  the repo does not run).
- Findings-log recount: earlier "22 of 91 disproved by a check that
  already ran" was inflated; tool-shaped instances are PRs 28, 75, 198
  plus #232's two. Stated honestly in #307.

Pointers: api/doug/ci_evidence.py · api/doug/settle.py (third class) ·
          api/doug/review.py head_ci_evidence / score_one(resolve_ci=) ·
          api/doug/worker.py resolve_ci · tests/test_ci_evidence.py ·
          tests/test_settle.py · tests/test_review.py · docs/REVIEWING.md
