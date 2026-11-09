"""A CI run's times, checked before a hardening step is signed off (REVIEW.md §11.7): each
job's wall time, slowest first, the run's own, and how evenly each family of parts (server
tests 1 of 6, …) splits its work. A job past BUDGET, or parts more uneven than SPREAD, is a
reason to split the tests further in that step.

    web/dev.sh ci-times [RUN | --pr N]

With no argument, the run on the current branch's last pushed commit. It reads GitHub's API
through the gh CLI."""

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys

REPO = "MojoKata/MoolaKata"
WORKFLOW = "check"
BUDGET = 6 * 60  # seconds: a job past it is split further
SPREAD = 1.4  # the slowest part over the quickest: past it, the parts are split by time
PART = re.compile(r"^(.*?) (\d+) of (\d+)\b")


def gh(*args: str) -> str:
    cmd = [shutil.which("gh") or "gh", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout  # noqa: S603


def seconds(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    a, b = (dt.datetime.fromisoformat(x.replace("Z", "+00:00")) for x in (start, end))
    return int((b - a).total_seconds())


def clock(s: int | None) -> str:
    return "—" if s is None else f"{s // 60}m{s % 60:02d}s"


def report(jobs: list[dict]) -> tuple[list[str], list[str]]:
    """The run's lines, and what to do about it: each job past the budget, and each family of
    parts whose slowest is more than SPREAD times its quickest."""
    ran = [j for j in jobs if j.get("conclusion") not in ("skipped", None) and j.get("started_at")]
    times = {j["name"]: seconds(j["started_at"], j["completed_at"]) for j in ran}
    starts = [j["started_at"] for j in ran]
    ends = [j["completed_at"] for j in ran if j.get("completed_at")]
    wall = seconds(min(starts), max(ends)) if starts and ends else None
    lines = [f"run: {clock(wall)} from the first job's start to the last one's end"]
    for name, s in sorted(times.items(), key=lambda kv: -(kv[1] or 0)):
        mark = "  ⚠ over budget" if s is not None and s > BUDGET else ""
        lines.append(f"  {clock(s):>8}  {name}{mark}")
    todo = [f"{n}: {clock(s)}, past the {clock(BUDGET)} budget" for n, s in times.items()
            if s is not None and s > BUDGET]  # fmt: skip
    families: dict[str, list[int]] = {}
    for name, s in times.items():
        if (m := PART.match(name)) and s:
            families.setdefault(m[1], []).append(s)
    for family, ts in sorted(families.items()):
        if len(ts) > 1 and max(ts) > SPREAD * min(ts):
            todo.append(f"{family}: parts from {clock(min(ts))} to {clock(max(ts))}, uneven")
    return lines, todo


def find_run(pr: int | None) -> str:
    if pr is not None:
        sha = gh("pr", "view", str(pr), "-R", REPO, "--json", "headRefOid", "-q", ".headRefOid")
    else:
        git = [shutil.which("git") or "git", "rev-parse", "@{push}"]
        sha = subprocess.run(git, capture_output=True, text=True).stdout  # noqa: S603
    runs = json.loads(gh("api", f"repos/{REPO}/actions/runs?head_sha={sha.strip()}"))
    found = [r for r in runs["workflow_runs"] if r["name"] == WORKFLOW]
    if not found:
        raise SystemExit(f"no {WORKFLOW} run for {sha.strip()[:7]} yet")
    return str(found[0]["id"])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="web/dev.sh ci-times", description=__doc__.split("\n\n")[0])
    p.add_argument("run", nargs="?", help="a run id; by default the current branch's last run")
    p.add_argument("--pr", type=int, help="the run on a pull request's head")
    args = p.parse_args(argv)
    run = args.run or find_run(args.pr)
    jobs = json.loads(gh("api", f"repos/{REPO}/actions/runs/{run}/jobs?per_page=100"))["jobs"]
    lines, todo = report(jobs)
    print(f"check run {run}")
    print("\n".join(lines))
    print("\n".join(["", "to split further:", *(f"  {t}" for t in todo)]) if todo else
          "\nwithin budget: nothing to split")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
