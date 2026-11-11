"""The hardening page (requirements S17.5.8.6): a review's findings, the coverage and the mutation
runs, by area, and the path to the end of the review's sweep. coverage_site builds it beside the
coverage page on each merge to main, and keeps each merge's figures in the history, so a step's
result is what changed by area at its merge.

Its sources, all in the repository: the review's summary tables and claims (each finding's area
is that of the first code it names, else its section's), docs/hardening/mutation/ (each run's
record, mutate.py), docs/hardening/path.toml (the steps), and what coverage measured."""

import json
import re
import tomllib
from collections import Counter
from pathlib import Path

from .. import paths
from . import coverage, mutate

PATH = paths.ROOT / "docs" / "hardening" / "path.toml"
PAGE = Path(__file__).with_name("hardening.html")
OTHER = "process and docs"
# A finding that names no code counts in its section's area; the first match wins, so a
# subsection comes before its section.
SECTIONS = (
    ("S1.6", "server/bitcoin"), ("S1.7", "server/loans"), ("S1.8", "server/assets"),
    ("S1.10", "server/assets"), ("S6.8", "server/education"), ("S7.7", "server/gifts"),
    ("S7.8", "server/gifts"), ("S7.9", "server/giving"), ("S10.10", "server/people"),
    ("S1", "server/ledger"), ("S2", "server/ledger"), ("S3", "server/options"),
    ("S4", "server/prices"), ("S5", "server/ui"), ("S6", "server/projections"),
    ("S7", "server/budgets"), ("S8", "server/taxes"), ("S9", "server/receipts"),
    ("S10", "server/auth"), ("S11", "server/links"), ("S12", "browser/screens"),
    ("S13", "server/core"), ("S14", "server/store"), ("S15", "server/keys"),
    ("S16", "server/ui"), ("S18", "connector"),
)  # fmt: skip
ROW = re.compile(
    r"^\| \[CR\d+-(\d+)\]\(#[^)]*\) \| ([^|\n]*)\| (\w+) \| \d+ \| ([^|\n]*)\| ([^|\n]*)", re.M
)
CLAIM = re.compile(r"^### CR\d+-(\d+):(.*?)(?=^### |^## |\Z)", re.M | re.S)
CODE_LINE = re.compile(r"\*\*(?:Code|Where)[^*]*\*\*:?(.*?)(?=\n- \*\*|\n\n)", re.S)
CODE_PATH = re.compile(
    r"((?:web/server/src/moolakata|web/ui|connector/moolakata_connector)/[\w/.-]+\.(?:py|js))"
)
PR_IN = re.compile(r"\(#(\d+)\)")


def section_area(text: str) -> str | None:
    for m in re.finditer(r"\bS(\d+(?:\.\d+)?)", text):
        for prefix, area in SECTIONS:
            if m[1] == prefix[1:] or m[1].startswith(prefix[1:] + "."):
                return area
    return None


def findings(text: str) -> list[dict]:
    """Each finding of a review: its id, severity, state, description, the pull request that
    fixed it, and its area."""
    claims = {int(m[1]): m[2] for m in CLAIM.finditer(text)}
    out = []
    for m in ROW.finditer(text):
        n, req, sev, status, desc = int(m[1]), m[2].strip(), m[3], m[4].strip(), m[5].strip()
        body = claims.get(n, "")
        code = CODE_LINE.search(body)
        named = CODE_PATH.findall(code[1] if code else "") or CODE_PATH.findall(body)
        area = next((a for a in map(coverage.area_of, named) if a), None)
        area = area or section_area(req) or section_area(body[:600]) or OTHER
        state = status.split()[0] if status else "open"
        prs = PR_IN.findall(status)
        out.append({
            "id": n, "sev": sev, "desc": desc,
            "state": state if state in ("fixed", "open", "question") else "closed",
            "pr": int(prs[0]) if prs else None, "area": area,
        })  # fmt: skip
    return out


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


def merged(history: list[dict]) -> set[int]:
    """The pull requests merged to main: those of the history's merges, and those git's log
    names where the checkout holds it."""
    prs = {h["pr"] for h in history if h.get("pr")}
    r = coverage.git("log", "--format=%s", "HEAD")
    prs |= {int(m[1]) for s in r.stdout.splitlines() if (m := re.search(r"\(#(\d+)\)$", s))}
    return prs


def steps(plan: dict, found: list[dict], history: list[dict]) -> list[dict]:
    """The path's steps with their numbers, areas, whether done, and, for a step merged since
    the page kept its history, what changed by area at its merge."""
    area_of = {f["id"]: f["area"] for f in found}
    done = merged(history)
    out = []
    for n, s in enumerate(plan["step"], 1):
        ids = s.get("findings", [])
        areas = s.get("areas") or list(dict.fromkeys(area_of[i] for i in ids if i in area_of))
        what = s.get("what") or "Sweep"
        step = {"n": n, "kind": s["kind"], "what": what, "pr": s.get("pr"), "areas": areas,
                "findings": ids, "gains": s.get("gains"), "done": s.get("pr") in done}  # fmt: skip
        step["result"] = result(step, history) if step["done"] else None
        out.append(step)
    return out


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


def data(history: list[dict], files: list[dict], repo: str) -> dict:
    """What the page shows, from the history (this commit's entry last, with its figures) and
    each file's coverage."""
    plan = tomllib.loads(PATH.read_text())
    found = findings((paths.ROOT / plan["review"]).read_text())
    recs = records()
    blobs = head_blobs()
    runs = module_runs(recs, blobs)
    baseline = baseline_runs(recs, blobs)
    last = history[-1]
    base = next((h for h in history if "hardening" in h), last)
    bugs = {int(i.split("-")[-1]) for r in recs for i in r.get("found", [])}
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
                {k: f[k] for k in ("id", "sev", "state", "desc", "pr")} | {"mut": f["id"] in bugs}
                for f in found if f["area"] == a
            ],
        })  # fmt: skip
    return {
        "repo": repo,
        "head": {k: last.get(k) for k in ("commit", "pr", "date", "subject")},
        "base": {k: base.get(k) for k in ("commit", "pr", "date")} if base is not last else None,
        "review": plan["review"],
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
        "path": steps(plan, found, history),
    }


def entry_figures(areas: dict, files: list[dict]) -> dict:
    """This commit's figures for its history entry."""
    plan = tomllib.loads(PATH.read_text())
    found = findings((paths.ROOT / plan["review"]).read_text())
    return figures(areas, files, found, records(), head_blobs())


def page(history: list[dict], files: list[dict], repo: str) -> str:
    script = json.dumps(data(history, files, repo), separators=(",", ":")).replace("</", "<\\/")
    return PAGE.read_text().replace("/*DATA*/", script)
