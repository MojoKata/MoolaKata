"""What the tests reach (requirements S17.5.8), from what `web/check` or `web/dev.sh coverage`
measured into web/.dev/coverage/: coverage.py's data for the server, the servers the browser
tests start and the connector; V8's for the browser app, from `deno test --coverage` and the
browser tests' pages (tests/jscoverage.py), read through `deno coverage`.

    python -m moolakata.dev.coverage report [--check]   totals by area, the changed lines, HTML
    python -m moolakata.dev.coverage floor              raise web/coverage-floor.json to them
    python -m moolakata.dev.coverage site               the site: the reports and their history

`report` prints line and branch coverage by area and of the lines changed since the base (the
merge base with main; in CI the commit before), and writes the HTML reports and summary.md.
In GitHub Actions it also writes the job summary and annotations (the headline, and the
changed lines no test reaches, inline). `--check` fails when an area falls below its floor.
`floor` raises each area's floor to what was measured less its side's SLACK in lines and in
branches, rounded down to a tenth of a point, so run-to-run jitter doesn't fail however small
the area; it never lowers one (that is done by hand, with the reason in the commit). `site`
builds the coverage site (coverage_site.py)."""

import json
import math
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .. import paths

OUT = paths.WEB / ".dev" / "coverage"
FLOOR = paths.WEB / "coverage-floor.json"
SERVER = paths.WEB / "server" / "src" / "moolakata"
CONNECTOR = paths.ROOT / "connector" / "moolakata_connector"
# The browser app's own code: the served directories (static.SERVED_DIRS) that hold scripts,
# less the vendored libraries; api/types.js holds type definitions only.
BROWSER_DIRS = ("app", "api", "store", "screens", "components", "charts", "account-types")
NOT_CODE = {"api/types.js"}
ANNOTATIONS = 9  # GitHub shows 10 notices a step: the headline and the nine largest gaps
# The lines or branches an area's measure may move by between runs: a count, not points, since
# one branch is a point of a one-file area. The server's and the connector's tests measure the
# same each run; the browser's move 10 or more lines and branches with their timing.
SLACK = {"server": 3, "connector": 3, "browser": 20}


@dataclass
class File:
    """One file's measure: the lines that run and those that don't, and its branches."""

    area: str
    covered: set[int] = field(default_factory=set)
    missed: set[int] = field(default_factory=set)
    branches: int = 0
    branches_taken: int = 0


def area_of(rel: str) -> str | None:
    """The area a repository path counts in: a server package, the server's top-level modules,
    a directory of the browser app, or the connector."""
    parts = rel.split("/")
    if rel.startswith("web/server/src/moolakata/"):
        inner = parts[4:]
        return f"server/{inner[0]}" if len(inner) > 1 else "server/core"
    if rel.startswith("connector/moolakata_connector/"):
        return "connector"
    if rel.startswith("web/ui/") and len(parts) > 3 and parts[2] in BROWSER_DIRS:
        return f"browser/{parts[2]}"
    return None


def _rel(name: str, base: Path) -> str:
    return (base / name).resolve().relative_to(paths.ROOT).as_posix()


# ---------- the server and the connector: coverage.py ----------


def server_files() -> dict[str, File]:
    import coverage

    data = OUT / "server"
    if not any(data.glob(".coverage*")):
        return {}
    os.chdir(paths.WEB / "server")
    cov = coverage.Coverage(
        data_file=str(data / ".coverage"), config_file=str(paths.WEB / "server" / "pyproject.toml")
    )
    # Each process wrote its own file (parallel); they are joined once, into .coverage.
    if any(data.glob(".coverage.*")):
        cov.combine()
        cov.save()
    cov.load()
    shutil.rmtree(OUT / "html" / "server", ignore_errors=True)
    cov.html_report(directory=str(OUT / "html" / "server"), title="MoolaKata: the server")
    cov.json_report(outfile=str(OUT / "server.json"))
    report = json.loads((OUT / "server.json").read_text())
    out = {}
    for name, f in report["files"].items():
        rel = _rel(name, Path.cwd())
        area = area_of(rel)
        if area is None:
            continue
        s = f["summary"]
        out[rel] = File(
            area,
            set(f["executed_lines"]),
            set(f["missing_lines"]),
            s.get("num_branches", 0),
            s.get("covered_branches", 0),
        )
    return out


# ---------- the browser app: V8's coverage through deno coverage ----------


def _utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def unloaded(js: Path) -> None:
    """A coverage entry for each of the app's files that no test loaded, so it counts as not
    reached instead of not counting (V8 reports only the scripts it ran)."""
    seen = set()
    for f in js.glob("*.json"):
        seen.add(json.loads(f.read_text())["url"])
    for d in BROWSER_DIRS:
        for f in sorted((paths.UI / d).rglob("*.js")):
            rel = f.relative_to(paths.UI).as_posix()
            if rel in NOT_CODE or f.as_uri() in seen:
                continue
            length = _utf16_length(f.read_text())
            entry = {
                "scriptId": "0",
                "url": f.as_uri(),
                "functions": [
                    {
                        "functionName": "",
                        "ranges": [{"startOffset": 0, "endOffset": length, "count": 0}],
                        "isBlockCoverage": True,
                    }
                ],
            }
            (js / f"unloaded-{rel.replace('/', '-')}.json").write_text(json.dumps(entry))


def deno(*args: str) -> subprocess.CompletedProcess:
    args_ = [str(paths.WEB / "dev.sh"), "deno", *args]
    return subprocess.run(args_, capture_output=True, text=True, check=True)  # noqa: S603


def git(*args: str) -> subprocess.CompletedProcess:
    args_ = [shutil.which("git") or "git", *args]
    return subprocess.run(args_, cwd=paths.ROOT, capture_output=True, text=True)  # noqa: S603


def browser_files() -> dict[str, File]:
    js = OUT / "js"
    if not any(js.glob("*.json")):
        return {}
    unloaded(js)
    include = "^" + re.escape(paths.UI.as_uri()) + "/(" + "|".join(BROWSER_DIRS) + ")/"
    deno(
        "coverage",
        "--quiet",
        f"--include={include}",
        "--lcov",
        f"--output={OUT / 'browser.lcov'}",
        str(js),
    )
    html = js / "html"
    shutil.rmtree(html, ignore_errors=True)
    deno("coverage", "--quiet", f"--include={include}", "--html", str(js))
    shutil.rmtree(OUT / "html" / "browser", ignore_errors=True)
    shutil.move(str(html), str(OUT / "html" / "browser"))
    out: dict[str, File] = {}
    f = None
    for line in (OUT / "browser.lcov").read_text().splitlines():
        if line.startswith("SF:"):
            rel = _rel(line[3:].removeprefix("file://"), paths.ROOT)
            area = area_of(rel)
            f = out.setdefault(rel, File(area)) if area else None
        elif f is None:
            continue
        elif line.startswith("DA:"):
            n, hits = line[3:].split(",")[:2]
            (f.covered if int(hits) > 0 else f.missed).add(int(n))
        elif line.startswith("BRDA:"):
            f.branches += 1
            f.branches_taken += line.rsplit(",", 1)[1] not in ("-", "0")
    for f in out.values():
        f.missed -= f.covered
    return out


# ---------- totals, the changed lines, and what is shown ----------


def pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def totals(files: dict[str, File]) -> dict[str, dict]:
    by: dict[str, list[File]] = {}
    for f in files.values():
        by.setdefault(f.area, []).append(f)
    out = {}
    for area in sorted(by):
        fs = by[area]
        lines = sum(len(f.covered) + len(f.missed) for f in fs)
        reached = sum(len(f.covered) for f in fs)
        branches, taken = sum(f.branches for f in fs), sum(f.branches_taken for f in fs)
        out[area] = {
            "files": len(fs),
            "lines": pct(reached, lines),
            "branches": pct(taken, branches),
            "lineCount": lines,
            "linesReached": reached,
            "branchCount": branches,
            "branchesReached": taken,
        }
    return out


def base_ref() -> str | None:
    """What the changed lines are counted from: MK_COVERAGE_BASE; in CI the commit before (a
    pull request's merge commit's first parent is its base; on main, the merge before);
    otherwise the merge base with main."""
    if os.environ.get("MK_COVERAGE_BASE"):
        return os.environ["MK_COVERAGE_BASE"]
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return "HEAD^1"
    for main in ("upstream/main", "origin/main", "main"):
        r = git("merge-base", "HEAD", main)
        if r.returncode == 0:
            return r.stdout.strip()
    return None


HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def changed_lines(base: str) -> dict[str, set[int]]:
    """The lines added or changed since `base`, in the working tree, by repository path."""
    r = git("diff", "-U0", "--no-color", base, "--", "web/server/src", "web/ui", "connector")
    if r.returncode != 0:
        return {}
    out: dict[str, set[int]] = {}
    name = None
    for line in r.stdout.splitlines():
        if line.startswith("+++ "):
            name = line[6:] if line.startswith("+++ b/") else None
        elif name and (m := HUNK.match(line)):
            start, count = int(m[1]), int(m[2] if m[2] is not None else 1)
            out.setdefault(name, set()).update(range(start, start + count))
    return out


def ranges(lines: list[int]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for n in sorted(lines):
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return [(a, b) for a, b in out]


def diff(files: dict[str, File], changed: dict[str, set[int]]) -> dict:
    covered = missed = 0
    gaps = []
    for rel, lines in sorted(changed.items()):
        f = files.get(rel)
        if f is None:
            continue
        covered += len(lines & f.covered)
        miss = lines & f.missed
        missed += len(miss)
        gaps += [(rel, a, b) for a, b in ranges(list(miss))]
    return {"covered": covered, "lines": covered + missed, "gaps": gaps}


def show(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}%"


def summary(areas: dict, floors: dict, d: dict | None, base: str | None, below: list) -> str:
    out = ["## Coverage", ""]
    if d is not None and d["lines"]:
        out.append(
            f"**Changed lines** (since `{base}`): {d['covered']} of {d['lines']} reached, "
            f"{show(pct(d['covered'], d['lines']))}."
        )
    elif d is not None:
        out.append(f"**Changed lines** (since `{base}`): none that run.")
    out += [
        "",
        "| Area | Files | Lines | Branches | Floor (lines / branches) |",
        "|---|---:|---:|---:|---|",
    ]
    for area, t in areas.items():
        fl = floors.get(area)
        floor = f"{show(fl.get('lines'))} / {show(fl.get('branches'))}" if fl else "—"
        mark = " ⚠" if area in below else ""
        cells = [f"{area}{mark}", str(t["files"]), show(t["lines"]), show(t["branches"]), floor]
        out.append("| " + " | ".join(cells) + " |")
    if d and d["gaps"]:
        out += ["", "**Changed lines no test reaches:**", ""]
        out += [f"- `{rel}`: {a}" + (f"–{b}" if b > a else "") for rel, a, b in d["gaps"]]
    if below:
        out += ["", f"**Below the floor:** {', '.join(below)}."]
    return "\n".join(out) + "\n"


def overall(areas: dict, kind: str, prefix: str) -> float | None:
    """The areas under `prefix` as one, each weighted by its lines."""
    rows = [t for a, t in areas.items() if a.startswith(prefix) and t[kind] is not None]
    return pct(sum(t[kind] * t["lineCount"] for t in rows), 100 * sum(t["lineCount"] for t in rows))


def annotate(areas: dict, d: dict | None) -> None:
    """GitHub's workflow commands: a notice with the headline, and one on each of the largest
    stretches of changed lines no test reaches, shown on those lines in the pull request."""
    server, browser = (show(overall(areas, "lines", p)) for p in ("server", "browser"))
    head = f"server {server} of lines, browser {browser}"
    if d is not None and d["lines"]:
        head += f"; changed lines {d['covered']} of {d['lines']} reached"
    print(f"::notice title=Coverage::{head}")
    if d:
        for rel, a, b in sorted(d["gaps"], key=lambda g: g[1] - g[2])[:ANNOTATIONS]:
            where = f"file={rel},line={a},endLine={b}"
            print(f"::notice {where},title=Not reached::no test runs these lines")


def measure() -> tuple[dict[str, File], dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    files = server_files() | browser_files()
    return files, totals(files)


def floors() -> dict:
    return json.loads(FLOOR.read_text()) if FLOOR.exists() else {}


def under(areas: dict, fl: dict) -> list[str]:
    out = []
    for area, f in fl.items():
        t = areas.get(area)
        if t is None:
            continue
        if any(
            t[k] is not None and f.get(k) is not None and t[k] < f[k] for k in ("lines", "branches")
        ):
            out.append(area)
    return out


def cmd_report(check: bool) -> int:
    files, areas = measure()
    if not areas:
        print("nothing measured: run web/check or web/dev.sh coverage first")
        return 1
    fl = floors()
    base = base_ref()
    d = diff(files, changed_lines(base)) if base else None
    below = under(areas, fl)
    text = summary(areas, fl, d, base, below)
    (OUT / "summary.md").write_text(text)
    (OUT / "totals.json").write_text(json.dumps(areas, indent=2) + "\n")
    print(text)
    print(
        f"HTML: {OUT / 'html' / 'server' / 'index.html'}, {OUT / 'html' / 'browser' / 'index.html'}"
    )
    if os.environ.get("GITHUB_ACTIONS") == "true":
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
                f.write(text)
        annotate(areas, d)
    return 1 if check and below else 0


def slack_floor(area: str, reached: int, total: int) -> float:
    """What was reached less the area's slack, as a percentage rounded down to a tenth."""
    slack = SLACK[area.split("/")[0]]
    return math.floor(1000 * max(0, reached - slack) / total) / 10


def cmd_floor() -> int:
    totals_file = OUT / "totals.json"
    if not totals_file.exists():
        print("nothing measured: run web/check or web/dev.sh coverage first")
        return 1
    areas = json.loads(totals_file.read_text())
    if any("linesReached" not in t for t in areas.values()):
        print("measured before the counts were kept: run web/check or web/dev.sh coverage again")
        return 1
    old = floors()
    new = {}
    for area, t in areas.items():
        was = old.get(area, {})
        counts = {
            "lines": (t["linesReached"], t["lineCount"]),
            "branches": (t["branchesReached"], t["branchCount"]),
        }
        new[area] = {
            k: max(was.get(k) or 0, slack_floor(area, reached, total))
            for k, (reached, total) in counts.items()
            if total
        }
    FLOOR.write_text(json.dumps(new, indent=2, sort_keys=True) + "\n")
    print(f"{FLOOR.relative_to(paths.ROOT)}: {len(new)} areas")
    return 0


def main(argv: list[str]) -> int:
    what = argv[1] if len(argv) > 1 else "report"
    if what == "floor":
        return cmd_floor()
    if what == "site":
        from . import coverage_site

        return coverage_site.build()
    return cmd_report("--check" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
