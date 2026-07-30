"""Backfill the outcome ledger with the probe corpus.

The Phase-1 probes produced ~650 reader verdicts whose outcomes are already
known — every sampled PR carries a revert label or a confirmed-clean label.
That is the seed corpus for the distillation loop's central join
(findings x outcomes), and it belongs in the same ledger the live service
writes. Verdict rows get tier "reader" and the probe's model; outcome rows
carry kind revert/clean with the revert's observed date where we have one.

Backfilled scored_at is the load time, which postdates some outcomes —
inherent to backfill, and why outcome analysis joins on labels, not
timestamps, for this corpus.

    uv run python scripts/backfill_ledger.py --from-gcp doug-prod0  # proxy on :5433
    DATABASE_URL=... uv run python scripts/backfill_ledger.py
"""

import functools
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from rf_kamei import REPOS, load

from doug import store
from doug.backtest.git_labels import find_reverted_prs_dated
from doug.backtest.replay import to_metadata
from doug.reader import MODEL, ReaderVerdict, verdict_from_reader

print = functools.partial(print, flush=True)  # noqa: A001

CACHE = Path(".backtest-cache")
PROBES = [
    ("getsentry/sentry", "llm-probe", "sentry"),
    ("grafana/grafana", "llm-probe-grafana", "grafana"),
]


def _database_url_from_gcp(project: str) -> str:
    url = subprocess.run(
        ["gcloud", "secrets", "versions", "access", "latest",
         "--secret=doug-database-url", f"--project={project}"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    # Rewrite the Cloud SQL socket host to the local auth proxy.
    return url.split("?host=")[0].replace("@/doug", "@127.0.0.1:5433/doug")


def backfill(force: bool) -> int:
    from sqlalchemy import func, select

    engine = store._get_engine()
    if engine is None:
        print("DATABASE_URL not set")
        return 1

    total_v = total_o = 0
    for repo, probe_dir, tag in PROBES:
        with engine.connect() as conn:
            existing = conn.execute(
                select(func.count()).select_from(store.verdicts).where(
                    store.verdicts.c.repo == repo,
                    store.verdicts.c.model == MODEL,
                )
            ).scalar_one()
        if existing and not force:
            print(f"{repo}: {existing} rows already present — skipping (--force to redo)")
            continue

        d = CACHE / probe_dir
        findings = json.loads((d / "findings-main.json").read_text())
        owner, name, limit, before = REPOS[tag]
        prs, defects = load(owner, name, limit, before)
        by = {p.number: p for p in prs}
        dated = find_reverted_prs_dated(owner, name, CACHE)

        for n_str, r in findings.items():
            n = int(n_str)
            pr = by.get(n)
            if pr is None:
                continue
            rv = ReaderVerdict.model_validate(
                {k: r[k] for k in ("risk_score", "rationale", "findings")}
            )
            store.save_review(
                repo, n, "reader", verdict_from_reader(rv), rv,
                model=MODEL, pr_meta=to_metadata(pr).model_dump(mode="json"),
            )
            total_v += 1
            observed = dated.get(n)
            with engine.begin() as conn:
                conn.execute(store.outcomes.insert(), {
                    "repo": repo,
                    "pr_number": n,
                    "kind": "revert" if n in defects else "clean",
                    "observed_at": (
                        datetime.fromisoformat(observed) if observed else datetime.now(UTC)
                    ),
                    "source": "git-labels",
                })
            total_o += 1
        print(f"{repo}: loaded")
    print(f"backfilled {total_v} verdicts, {total_o} outcomes")
    return 0


def _q(v) -> str:
    """SQL literal. Our own probe output, but quote like it's hostile."""
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (dict, list)):
        return _q(json.dumps(v)) + "::json"
    return "'" + str(v).replace("\x00", "").replace("'", "''") + "'"


def emit_sql(out: Path) -> int:
    """The zero-client-connectivity path: a file for `gcloud sql import`.

    IPv6-only networks NAT64-mangle the auth proxy's 3307 stream, so the
    import runs server-side instead. Idempotent — wipes prior backfill
    rows for these repos first; live repos are untouched.
    """
    repos_in = "('getsentry/sentry','grafana/grafana')"
    lines = [
        "BEGIN;",
        "DELETE FROM findings WHERE verdict_id IN (SELECT id FROM verdicts"
        f" WHERE repo IN {repos_in} AND model = {_q(MODEL)});",
        f"DELETE FROM verdicts WHERE repo IN {repos_in} AND model = {_q(MODEL)};",
        f"DELETE FROM outcomes WHERE repo IN {repos_in} AND source = 'git-labels';",
    ]
    n_v = n_o = 0
    for repo, probe_dir, tag in PROBES:
        findings = json.loads((CACHE / probe_dir / "findings-main.json").read_text())
        owner, name, limit, before = REPOS[tag]
        prs, defects = load(owner, name, limit, before)
        by = {p.number: p for p in prs}
        dated = find_reverted_prs_dated(owner, name, CACHE)
        for n_str, r in findings.items():
            n = int(n_str)
            pr = by.get(n)
            if pr is None:
                continue
            rv = ReaderVerdict.model_validate(
                {k: r[k] for k in ("risk_score", "rationale", "findings")}
            )
            verdict = verdict_from_reader(rv)
            cols = (
                f"{_q(repo)}, {n}, now(), 'reader', {verdict.score}, "
                f"{_q(verdict.band.value)}, {verdict.threshold}, {_q(MODEL)}, "
                f"{rv.risk_score}, {_q(rv.rationale)}, {_q(rv.model_dump())}, "
                f"{_q(to_metadata(pr).model_dump(mode='json'))}"
            )
            insert = (
                "INSERT INTO verdicts (repo, pr_number, scored_at, tier, score,"
                " band, threshold, model, risk_score, rationale, raw, pr_meta)"
                f" VALUES ({cols})"
            )
            if verdict.reasons:
                by_desc = {f.description: f for f in rv.findings}
                def _fval(x, fmap=by_desc):
                    f = fmap.get(x.label)
                    return (
                        f"({_q(x.rule)}, {_q(x.label)}, {x.weight}, "
                        f"{_q(f.file if f else None)}, {_q(f.severity if f else None)})"
                    )

                vals = ", ".join(_fval(x) for x in verdict.reasons)
                lines.append(
                    f"WITH v AS ({insert} RETURNING id) "
                    "INSERT INTO findings (verdict_id, rule, label, weight, file, severity) "
                    f"SELECT v.id, x.* FROM v CROSS JOIN (VALUES {vals})"
                    " AS x(rule, label, weight, file, severity);"
                )
            else:
                lines.append(insert + ";")
            n_v += 1
            observed = dated.get(n)
            lines.append(
                "INSERT INTO outcomes (repo, pr_number, kind, observed_at, source) VALUES "
                f"({_q(repo)}, {n}, {_q('revert' if n in defects else 'clean')}, "
                + (f"{_q(observed)}::timestamptz" if observed else "now()")
                + ", 'git-labels');"
            )
            n_o += 1
    lines.append("COMMIT;")
    out.write_text("\n".join(lines))
    print(f"wrote {out}: {n_v} verdicts, {n_o} outcomes")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if "--emit-sql" in args:
        return emit_sql(Path(args[args.index("--emit-sql") + 1]))
    if "--from-gcp" in args:
        project = args[args.index("--from-gcp") + 1]
        os.environ["DATABASE_URL"] = _database_url_from_gcp(project)
    return backfill(force="--force" in args)


if __name__ == "__main__":
    raise SystemExit(main())
