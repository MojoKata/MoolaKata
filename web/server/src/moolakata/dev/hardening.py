"""The hardening page (requirements S17.5.8.6): a sweep's findings, the coverage and the mutation
runs, by area, and the path to the end of the sweep. coverage_site builds it beside the coverage
page on each merge to main, and keeps each merge's figures in the history, so a step's result is
what changed by area at its merge.

Its sources: the sweep's GitHub issues (each step an issue labelled `hardening`, its findings
its sub-issues, each with its area's label), docs/hardening/mutation/ (each run's record,
mutate.py), and what coverage measured."""

import json
import os
import re
import urllib.request
from collections import Counter
from pathlib import Path

from . import coverage, mutate

PAGE = Path(__file__).with_name("hardening.html")
LABEL = "hardening"
# A step's title, "H1.8 Sweep server/ledger"; a finding's, "H1.8-1 What goes wrong (CR3-95)".
TITLE = re.compile(r"^H(\d+)\.(\d+)(?:-\d+)? (.*?)(?: \((CR\d+-\d+)\))?$")
SEVERITY = re.compile(r"\bseverity (High|Med|Low)\b")
# The pull request a step was done by, or is being done in: "done by #44", "**Pull request:** #44".
STEP_PR = re.compile(r"(?:done by|\*\*Pull request:\*\*) #(\d+)")
FIXED_BY = re.compile(r"\bFixed by #(\d+)")
GAINS = re.compile(r"\*\*Coverage gains it reported\*\*[^:]*: (.*?)\.?$", re.M)
OTHER = "process and docs"


def fetch_issues(repo: str) -> list[dict]:
    """Every issue labelled `hardening`, open and closed, from GitHub's API (`repo` as
    owner/name); with $GITHUB_TOKEN when it is set, as CI's is."""
    out: list[dict] = []
    page = 1
    while True:
        url = (f"https://api.github.com/repos/{repo}/issues?labels={LABEL}&state=all"
               f"&per_page=100&page={page}")  # fmt: skip
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        if os.environ.get("GITHUB_TOKEN"):
            req.add_header("Authorization", f"Bearer {os.environ['GITHUB_TOKEN']}")
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (https, fixed host)
            batch = json.loads(r.read())
        out += [i for i in batch if "pull_request" not in i]
        if len(batch) < 100:
            return out
        page += 1


def from_issues(issues: list[dict]) -> tuple[list[dict], list[dict]]:
    """The sweep's steps and findings from its issues. A step is an issue with no parent whose
    title is "H<sweep>.<n> …"; its findings are its sub-issues, each in the area its `area:`
    label names, open or a question while open, fixed when closed as completed, else closed."""
    steps: dict[str, dict] = {}
    found = []
    for i in issues:
        m = TITLE.match(i["title"])
        if not m:
            continue
        labels = {lb["name"] for lb in i.get("labels", [])}
        areas = sorted(lb.removeprefix("area:") for lb in labels if lb.startswith("area:"))
        body = i.get("body") or ""
        if not i.get("parent_issue_url"):
            pr = STEP_PR.search(body)
            gains = GAINS.search(body)
            steps[i["url"]] = {
                "n": int(m[2]), "issue": i["number"], "what": m[3], "areas": areas,
                "pr": int(pr[1]) if pr else None, "gains": gains[1] if gains else None,
                "done": i["state"] == "closed", "findings": [],
            }  # fmt: skip
            continue
        sev = SEVERITY.search(body)
        fixed = FIXED_BY.search(body)
        closed = i["state"] == "closed"
        state = ("fixed" if i.get("state_reason") == "completed" else "closed") if closed else (
            "question" if "question" in labels else "open")  # fmt: skip
        found.append({
            "id": i["number"], "cr": m[4], "sev": sev[1] if sev else "Low", "desc": m[3],
            "state": state, "pr": int(fixed[1]) if fixed else None,
            "area": areas[0] if areas else OTHER, "parent": i["parent_issue_url"],
        })  # fmt: skip
    for f in found:
        if f["parent"] in steps:
            steps[f["parent"]]["findings"].append(f["id"])
    path = sorted(steps.values(), key=lambda s: s["n"])
    sev_of = {f["id"]: f["sev"] for f in found}
    for s in path:
        med = any(sev_of[x] != "Low" for x in s["findings"])
        s["kind"] = ("sweep" if s["what"].startswith("Sweep") else "before" if s["gains"] else
                     "med" if med else "tooling")  # fmt: skip
        s["areas"] = s["areas"] or sorted({f["area"] for f in found if f["id"] in s["findings"]})
    return path, [{k: v for k, v in f.items() if k != "parent"} for f in found]


def records() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(mutate.RECORDS.glob("*.json"))]


def head_blobs() -> dict[str, str]:
    """Each server module's content at HEAD, as git names it: moolakata/x.py → its blob id."""
    r = coverage.git("ls-tree", "-r", "HEAD", "--", "web/server/src/moolakata")
    out = {}
    for line in r.stdout.splitlines():
        meta, path = line.split("\t", 1)
        out[path.removeprefix("web/server/src/")] = meta.split()[2]
    return out


def module_runs(recs: list[dict], blobs: dict[str, str]) -> dict[str, dict]:
    """Each recorded module's latest settled run: the run, its pull request, and whether its
    content has changed since. A run not yet settled (no pull request) doesn't count."""
    out = {}
    for r in recs:
        if not r.get("pr"):
            continue
        for m in r["modules"]:
            stale = r.get("content", {}).get(m) != blobs.get(m)
            out[m] = {"run": r["name"], "pr": r["pr"], "stale": stale}
    return out


def baseline_runs(recs: list[dict], blobs: dict[str, str]) -> dict[str, str]:
    """Each module's first run not yet settled (the CI baseline's), "changed" when its content
    is no longer what that run mutated, else "current": a changed one's survivors are stale."""
    out = {}
    for r in recs:
        if r.get("pr"):
            continue
        for m, b in r.get("first_content", {}).items():
            out[m] = "current" if blobs.get(m) == b else "changed"
    return out


def catch(c: dict) -> tuple[int, int]:
    """Changes caught, of those a test reached or should have: timeouts count as caught."""
    caught = c["killed"] + c["timeout"]
    return caught, caught + c["survived"] + c["no tests"]


def figures(
    areas: dict, files: list[dict], found: list[dict], recs: list[dict], blobs: dict
) -> dict:
    """This commit's hardening figures by area, as the history keeps them."""
    runs = module_runs(recs, blobs)
    out = {a: {"open": 0, "med": 0, "fixed": 0, "all": 0, "statements": 0, "current": 0, "stale": 0}
           for a in [*areas, OTHER]}  # fmt: skip
    for f in found:
        t = out.setdefault(f["area"], {"open": 0, "med": 0, "fixed": 0, "all": 0})
        t["all"] += 1
        if f["state"] in ("open", "question"):
            t["open"] += 1
            t["med"] += f["sev"] != "Low"
        else:
            t["fixed"] += 1
    for f in files:
        t = out.get(f["area"])
        if t is None or not f["path"].startswith("web/server/src/"):
            continue
        t["statements"] += f["lineCount"]
        run = runs.get(f["path"].removeprefix("web/server/src/"))
        if run:
            t["stale" if run["stale"] else "current"] += f["lineCount"]
    return out


def steps(path: list[dict], history: list[dict]) -> list[dict]:
    """The path's steps, each done once its issue is closed, and, for one done since the page
    kept its history, what changed by area at its pull request's merge."""
    return [{**s, "result": result(s, history) if s["done"] else None} for s in path]


def result(step: dict, history: list[dict]) -> dict | None:
    """What changed in the step's areas at its merge, from the history's figures before and
    after it; None where the history has no figures for it."""
    at = next((i for i, h in enumerate(history) if h.get("pr") == step["pr"]), None)
    if at is None or at == 0 or "hardening" not in history[at]:
        return None
    before, after = history[at - 1], history[at]
    if "hardening" not in before:
        return None
    out = {}
    for a in step["areas"]:
        h0, h1 = before["hardening"].get(a, {}), after["hardening"].get(a, {})
        c0, c1 = before["areas"].get(a, {}), after["areas"].get(a, {})
        out[a] = {
            "fixed": h1.get("fixed", 0) - h0.get("fixed", 0),
            "mutated": h1.get("current", 0) - h0.get("current", 0),
            "lines": _change(c1.get("lines"), c0.get("lines")),
            "branches": _change(c1.get("branches"), c0.get("branches")),
        }
    return out


def _change(now, was):
    return None if now is None or was is None else round(now - was, 1)


def bug_ids(recs: list[dict], found: list[dict]) -> set[int]:
    """The findings a mutation run found, as the records name them: "CR3-412" (a review's
    number, in the finding's title) or "#412" (its issue)."""
    by_cr = {f["cr"]: f["id"] for f in found if f["cr"]}
    out = set()
    for name in (i for r in recs for i in r.get("found", [])):
        n = int(name[1:]) if name.startswith("#") else by_cr.get(name)
        if n is not None:
            out.add(n)
    return out


def data(history: list[dict], files: list[dict], repo: str, issues: list[dict]) -> dict:
    """What the page shows, from the history (this commit's entry last, with its figures),
    each file's coverage and the sweep's issues."""
    path, found = from_issues(issues)
    recs = records()
    blobs = head_blobs()
    runs = module_runs(recs, blobs)
    baseline = baseline_runs(recs, blobs)
    last = history[-1]
    base = next((h for h in history if "hardening" in h), last)
    bugs = bug_ids(recs, found)
    by_area: dict[str, list] = {}
    for f in files:
        mod = f["path"].removeprefix("web/server/src/")
        by_area.setdefault(f["area"], []).append({
            "path": coverage.short(f["path"]),
            "lines": [f["linesReached"], f["lineCount"]],
            "branches": [f["branchesReached"], f["branchCount"]],
            "run": runs.get(mod),
            "baseline": baseline.get(mod),
            "python": not f["path"].startswith("web/ui/"),
        })  # fmt: skip
    first: dict[str, list[int]] = {}
    for r in recs:
        if not r.get("pr"):
            continue
        per = r["first"].get("files") or {}
        touched = Counter()
        for m in r["modules"]:
            area = coverage.area_of("web/server/src/" + m)
            if per.get(m):
                c, t = catch(per[m])
                first.setdefault(area, [0, 0])
                first[area][0] += c
                first[area][1] += t
            else:
                touched[area] += 1
        if touched:  # no outcomes by file: the run's whole figure, for each area it touched
            c, t = catch(r["first"])
            for area in touched:
                first.setdefault(area, [0, 0])
                first[area][0] += c
                first[area][1] += t
    areas = []
    for a in [*last["areas"], OTHER]:
        now = last["areas"].get(a)
        was = base["areas"].get(a) if base is not last else None
        areas.append({
            "area": a, "files": by_area.get(a, []),
            "now": now, "was": was,
            "hardening": last["hardening"].get(a, {}),
            "first": first.get(a),
            "browser": a.startswith("browser/"),
            "findings": [
                {k: f[k] for k in ("id", "cr", "sev", "state", "desc", "pr")}
                | {"mut": f["id"] in bugs}
                for f in found if f["area"] == a
            ],
        })  # fmt: skip
    return {
        "repo": repo,
        "head": {k: last.get(k) for k in ("commit", "pr", "date", "subject")},
        "base": {k: base.get(k) for k in ("commit", "pr", "date")} if base is not last else None,
        "issues": f"{repo}/issues?q=label%3A{LABEL}+no%3Aparent-issue",
        "areas": areas,
        "runs": [
            {
                "name": r["name"],
                "pr": r.get("pr"),
                "modules": r["modules"],
                "note": r.get("note", ""),
                "found": r.get("found", []),
                "catch": catch(r["first"]),
                "changes": sum(r["first"][k] for k in mutate.COUNTED),
                "stale": [m for m in r["modules"] if runs.get(m, {}).get("stale")]
                if r.get("pr")
                else [m for m, b in r.get("first_content", {}).items() if blobs.get(m) != b],
            }
            for r in recs
        ],
        "path": steps(path, history),
    }


def entry_figures(areas: dict, files: list[dict], issues: list[dict]) -> dict:
    """This commit's figures for its history entry."""
    return figures(areas, files, from_issues(issues)[1], records(), head_blobs())


def page(history: list[dict], files: list[dict], repo: str, issues: list[dict]) -> str:
    script = json.dumps(data(history, files, repo, issues), separators=(",", ":"))
    script = script.replace("</", "<\\/")
    return PAGE.read_text().replace("/*DATA*/", script)
