"""The CI mutation baseline, driven and checked (docs/mutation-baseline.md): `web/dev.sh mutate
baseline` and `web/dev.sh mutate stale`.

    web/dev.sh mutate baseline [--repo OWNER/REPO] [--ref REF] [--areas GLOB...]
                               [--jobs NAME...] [--parallel N] [--rounds N] [--new]
    web/dev.sh mutate stale

`baseline` runs the whole loop the baseline takes: it starts the mutate workflow on `--ref`
(main) of `--repo` (MojoKata/MoolaKata; starting it there takes an admin, a fork's takes its
owner), waits for the run to end, and gathers every run so far without recording. A job that
ran nothing stops the loop: its log says why, and once the cause is fixed `--jobs` runs it
again by name. Changes left unrun (jobs out of time) start a `rest` run over every run so far,
round after round, until none is left; then it gathers again and records each area's
`baseline-<area>`. Its runs are kept in web/.dev/mutate-baseline.json, so it picks up where it
stopped when started again (`--new` starts afresh). It stops too when a round leaves as many
unrun as the one before, or after `--rounds` rest rounds.

`stale` names the modules whose content is no longer what their latest run mutated: the
baseline's first run until an area's sweep settles it, then the settling run; and the server's
modules no run has recorded. A pull request that changes one says so (docs/REVIEW.md §11.8).
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .. import paths
from . import mutate

STATE = paths.WEB / ".dev" / "mutate-baseline.json"
WORKFLOW = "mutate.yml"
POLL = 300  # seconds between looks at a run under way


def gh(*args: str) -> str:
    cmd = [shutil.which("gh") or "gh", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout  # noqa: S603


def dispatch(repo: str, ref: str, inputs: dict[str, str]) -> str:
    """Starts the mutate workflow; its run's id."""
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 60))
    fields = [x for k, v in inputs.items() if v for x in ("-f", f"{k}={v}")]
    out = gh("workflow", "run", WORKFLOW, "-R", repo, "--ref", ref, *fields)
    if m := re.search(r"/actions/runs/(\d+)", out):
        return m.group(1)
    for _ in range(20):  # an older gh prints no link: the newest dispatch since
        time.sleep(6)
        listed = json.loads(gh("run", "list", "-R", repo, "--workflow", WORKFLOW, "--branch",
                               ref, "--event", "workflow_dispatch", "-L", "5", "--json",
                               "databaseId,createdAt"))  # fmt: skip
        newer = [r for r in listed if r["createdAt"] >= since]
        if newer:
            return str(newer[0]["databaseId"])
    raise RuntimeError("the run started but can't be found: name it in the state file")


def status(repo: str, run: str) -> tuple[str, dict[str, int], list[str]]:
    """A run's status, its jobs counted by state, and those that failed."""
    got = json.loads(gh("run", "view", run, "-R", repo, "--json", "status,jobs"))
    count: dict[str, int] = {}
    failed = []
    for j in got["jobs"]:
        state = j["conclusion"] or j["status"]
        count[state] = count.get(state, 0) + 1
        if j["conclusion"] in ("failure", "cancelled"):
            failed.append(j["name"])
    return got["status"], count, failed


def wait(repo: str, run: str) -> list[str]:
    """Waits for a run to end, printing its jobs as they change; those that failed."""
    shown = None
    while True:
        st, count, failed = status(repo, run)
        line = ", ".join(f"{n} {k}" for k, n in sorted(count.items()))
        if line != shown:
            print(f"{time.strftime('%b %d %H:%M')} run {run}: {line}", flush=True)
            shown = line
        if st == "completed":
            return failed
        time.sleep(POLL)


def unrun_after(runs: list[str]) -> tuple[list[str], int]:
    """The jobs that ran nothing, and the changes left unrun, over every run so far."""
    jobs = mutate.downloaded(runs)
    by_source: dict[str, list[Path]] = {}
    for name, d in jobs.items():
        if not json.loads((d / "job.json").read_text()).get("unreached"):
            by_source.setdefault(mutate.source_of(name), []).append(d)
    empty = sorted(s for s, ds in by_source.items() if mutate.ran_nothing(ds))
    left = sum(
        c is None
        for s, ds in by_source.items()
        if s not in empty
        for keys in mutate.merged(ds).values()
        for c in keys.values()
    )
    return empty, left


def load(args) -> dict:
    if STATE.exists() and not args.new:
        return json.loads(STATE.read_text())
    return {"repo": args.repo, "ref": args.ref, "runs": [], "left": []}


def save(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1) + "\n")


def baseline(args) -> int:
    state = load(args)
    repo, ref = state["repo"], state["ref"]
    qualified = lambda run: f"{repo}:{run}"  # noqa: E731 - as gather and the rest input take it
    if args.jobs or not state["runs"]:
        inputs = {"areas": " ".join(args.areas), "jobs": " ".join(args.jobs or []),
                  "parallel": str(args.parallel)}  # fmt: skip
        state["runs"].append(qualified(dispatch(repo, ref, inputs)))
        save(state)
        print(f"started {state['runs'][-1]}")
    while True:
        last = state["runs"][-1]
        failed = wait(repo, last.rpartition(":")[2])
        if failed:
            print(f"failed in {last}: {' '.join(failed)} (their changes count as unrun)")
        empty, left = unrun_after(state["runs"])
        if empty:
            print(f"ran nothing: {' '.join(empty)}. Find the cause in their logs, fix it, "
                  f"then: web/dev.sh mutate baseline --jobs {' '.join(empty)}")  # fmt: skip
            return 1
        if not left:
            break
        rounds = state["left"]
        if rounds and left >= rounds[-1]:
            print(f"{left} changes still unrun, as many as the round before: stopped")
            return 1
        if len(rounds) >= args.rounds:
            print(f"{left} changes still unrun after {len(rounds)} rounds: stopped")
            return 1
        rounds.append(left)
        inputs = {"rest": " ".join(state["runs"]), "parallel": str(args.parallel)}
        state["runs"].append(qualified(dispatch(repo, ref, inputs)))
        save(state)
        print(f"{left} changes unrun: round {len(rounds)} started, {state['runs'][-1]}")
    print("nothing unrun: recording")
    return mutate.gather(argparse.Namespace(run=state["runs"], no_record=False))


def stale(_args) -> int:
    """The modules changed since their record's run, and those no run has recorded."""
    from . import hardening  # it reads mutate's records

    recs = hardening.records()
    modules = sorted(mutate.server_modules())
    here = dict(zip(modules, current(modules), strict=True))
    changed = 0
    # A settled run changed since was run again by the baseline, not yet settled: that's newer.
    again = {m for r in recs if not r.get("pr") for m in r.get("first_content", {})}
    for r in recs:
        ran = r.get("content", {}) if r.get("pr") else r.get("first_content", {})
        these = [m for m in ran if here.get(m) != ran[m] and not (r.get("pr") and m in again)]
        if these:
            when = f"settled in #{r['pr']}" if r.get("pr") else "its first run"
            print(f"{r['name']}: changed since {when}: {' '.join(these)}")
            changed += len(these)
    recorded = {m for r in recs for m in [*r["modules"], *r.get("first_content", {})]}
    new = [m for m in modules if m not in recorded]
    if new:
        print(f"in no run: {' '.join(new)}")
    if not changed and not new:
        print("every module is as its run mutated it")
    return 0


def current(modules: list[str]) -> list[str]:
    """Each module's content in the checkout, as git names it."""
    files = [str(mutate.SERVER / "src" / m) for m in modules]
    cmd = [shutil.which("git") or "git", "hash-object", "--", *files]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout  # noqa: S603
    return out.split()


def add_parsers(sub) -> None:
    b = sub.add_parser("baseline", help="the CI baseline's runs, round after round, recorded")
    b.add_argument("--repo", default=mutate.REPO, help="where the workflow runs")
    b.add_argument("--ref", default="main", help="the branch it runs")
    b.add_argument("--areas", nargs="*", default=["server/*"], help="area globs")
    b.add_argument("--jobs", nargs="*", help="run these jobs again by name, then go on")
    b.add_argument("--parallel", type=int, default=20, help="jobs at once (the account's 20)")
    b.add_argument("--rounds", type=int, default=5, help="rest rounds at most")
    b.add_argument("--new", action="store_true", help="start afresh, not where it stopped")
    sub.add_parser("stale", help="modules changed since their record's run")


COMMANDS = {"baseline": baseline, "stale": stale}

if __name__ == "__main__":
    sys.exit(mutate.main())
