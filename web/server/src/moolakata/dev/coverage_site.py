"""The coverage site (requirements S17.5.8): each merge to main publishes its coverage reports
and the history of each area's line and branch coverage to the repository's GitHub Pages site.

    python -m moolakata.dev.coverage site

builds it into web/.dev/coverage/site/ from what `report` measured and the history the
published site holds, with this commit's totals added last; check.yml's `coverage site` job
publishes it. Run anywhere else it builds the same pages as a preview of what publishing this
commit would show, and publishes nothing.

The history lives on the site alone: each merge reads it back and adds its own entry. A site
that answers with no history.json starts one only while there is no site at all; any other
failure to read it fails the build in CI, so a bad moment never starts the history over."""

import html
import json
import os
import re
import shutil
import urllib.error
import urllib.request

from . import coverage

SITE = coverage.OUT / "site"
PUBLISHED = "https://mojokata.github.io/MoolaKata/"
REPO = "https://github.com/MojoKata/MoolaKata"
PR = re.compile(r"\(#(\d+)\)$")
# Each chart's frame, in SVG units; the page's script places the crosshair from the same.
W, H, LEFT, RIGHT, TOP, BOTTOM = 360, 150, 40, 12, 10, 24
SERIES = (("lines", "Lines"), ("branches", "Branches"))


def in_ci() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def site_url() -> str:
    """The published site: MK_COVERAGE_SITE; in GitHub Actions, the repository's own Pages;
    otherwise MoolaKata's."""
    if os.environ.get("MK_COVERAGE_SITE"):
        return os.environ["MK_COVERAGE_SITE"].rstrip("/") + "/"
    if in_ci() and os.environ.get("GITHUB_REPOSITORY"):
        owner, name = os.environ["GITHUB_REPOSITORY"].split("/")
        return f"https://{owner.lower()}.github.io/{name}/"
    return PUBLISHED


def repo_url() -> str:
    if in_ci() and os.environ.get("GITHUB_REPOSITORY"):
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
        return f"{server}/{os.environ['GITHUB_REPOSITORY']}"
    return REPO


def get(url: str) -> bytes | None:
    """What the site serves at `url`, or None when it answers 404."""
    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=30) as r:  # noqa: S310
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def fetch_history(base: str, nonce: str) -> list[dict]:
    """The published history; empty while there is no site. `nonce` keeps a cache on the way
    from answering with an older copy."""
    body = get(f"{base}history.json?{nonce}")
    if body is not None:
        return json.loads(body)
    if get(base) is not None:
        raise SystemExit(f"{base} is up but has no history.json: not starting it over")
    return []


def entry(areas: dict) -> dict:
    """This commit's point in the history: its totals by area, and the pull request its
    subject names (a squash merge ends with "(#19)")."""
    r = coverage.git("log", "-1", "--format=%H%n%cI%n%s", "HEAD")
    commit, date, subject = [*r.stdout.splitlines(), "", "", ""][:3]
    m = PR.search(subject)
    return {
        "commit": commit,
        "date": date,
        "pr": int(m[1]) if m else None,
        "subject": subject,
        "areas": areas,
    }


def add(history: list[dict], e: dict) -> list[dict]:
    """The history with `e` last; a commit already in it (a run done again) moves to the end
    with what was measured this time."""
    return [h for h in history if h["commit"] != e["commit"]] + [e]


def figure(h: dict, area: str, kind: str) -> float | None:
    """An entry's figure for an area, or for the server's or browser's areas as one."""
    if area in ("server", "browser"):
        return coverage.overall(h["areas"], kind, area + "/")
    return (h["areas"].get(area) or {}).get(kind)


# ---------- the page ----------


def x_at(i: int, n: int) -> float:
    return LEFT + (W - LEFT - RIGHT) * (i / (n - 1) if n > 1 else 0.5)


def y_at(v: float) -> float:
    return TOP + (H - TOP - BOTTOM) * (1 - v / 100)


def label(h: dict) -> str:
    return f"#{h['pr']}" if h["pr"] else h["commit"][:7]


def chart(history: list[dict], area: str) -> str:
    """One area's line and branch coverage over the merges: a 0–100% scale, a hairline grid,
    2px lines, a ringed dot on each series' last point (and on any point alone)."""
    n = len(history)
    out = [
        f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(area)}: line and '
        f'branch coverage over the merges">'
    ]
    for v in (0, 50, 100):
        y = y_at(v)
        out.append(f'<line class="grid" x1="{LEFT}" x2="{W - RIGHT}" y1="{y:.1f}" y2="{y:.1f}"/>')
        at = f'x="{LEFT - 6}" y="{y + 3.5:.1f}" text-anchor="end"'
        out.append(f'<text class="axis" {at}>{v}%</text>')
    ends = [(0, "start"), (n - 1, "end")] if n > 1 else [(0, "middle")]
    for i, anchor in ends:
        at = f'x="{x_at(i, n):.1f}" y="{H - 6}" text-anchor="{anchor}"'
        out.append(f'<text class="axis" {at}>{html.escape(label(history[i]))}</text>')
    for kind, _ in SERIES:
        values = [figure(h, area, kind) for h in history]
        path, dots = [], []
        for i, v in enumerate(values):
            if v is None:
                continue
            joined = i > 0 and values[i - 1] is not None
            path.append(f"{'L' if joined else 'M'}{x_at(i, n):.1f} {y_at(v):.1f}")
            alone = not joined and (i == n - 1 or values[i + 1] is None)
            last = all(w is None for w in values[i + 1 :])
            if alone or last:
                at = f'cx="{x_at(i, n):.1f}" cy="{y_at(v):.1f}"'
                dots.append(f'<circle class="dot {kind}" {at} r="4"/>')
        if path:
            out.append(f'<path class="line {kind}" d="{" ".join(path)}"/>')
        out += dots
    at = f'x1="0" x2="0" y1="{TOP}" y2="{H - BOTTOM}"'
    out.append(f'<line class="cross" {at} visibility="hidden"/>')
    out.append("</svg>")
    return "".join(out)


def pct(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}%"


def change(now: float | None, was: float | None) -> str:
    if now is None or was is None or round(now - was, 1) == 0:
        return ""
    return f"{now - was:+.1f}".replace("-", "−")


def keyed(kind: str, text: str) -> str:
    return f'<span class="key {kind}"></span>{text}'


def short(rel: str) -> str:
    """A file's path from its side's root: ledger/post.py, components/share.js."""
    for root in coverage.ROOTS:
        if rel.startswith(root):
            return rel.removeprefix(root)
    return rel


def meter(kind: str, v: float | None, floor: float | None = None, was: float | None = None) -> str:
    """A bar for a percentage, a tick at the floor (red below it), the figure and its change."""
    if v is None:
        return "<td class='m'><span class='meter none'></span><span class='pct'>—</span></td>"
    below = " below" if floor is not None and v < floor else ""
    tick = f"<i style='left:{floor}%' title='floor {pct(floor)}'></i>" if floor is not None else ""
    delta = change(v, was)
    return (
        f"<td class='m'><span class='meter {kind}{below}'><b style='width:{v}%'></b>{tick}</span>"
        f"<span class='pct'>{pct(v)}</span><span class='delta'>{delta}</span></td>"
    )


def cells(t: dict, floor: dict | None = None, was: dict | None = None) -> str:
    """A row's figures: lines and branches, each a bar and the count reached."""
    out = []
    for kind, _ in SERIES:
        f = (floor or {}).get(kind)
        w = (was or {}).get(kind) if was else None
        out.append(meter(kind, t[kind], f, w))
        out.append(f"<td class='n'>{coverage.reached(t, kind)}</td>")
    return "".join(out)


def sort_keys(name: str, t: dict, q: str = "") -> str:
    """What the page's script sorts and filters a row by."""
    keys = {
        "name": name,
        "lines": t["lines"],
        "lc": t["lineCount"],
        "branches": t["branches"],
        "bc": t["branchCount"],
    }
    attrs = "".join(
        f' data-{k}="{html.escape("" if v is None else str(v))}"' for k, v in keys.items()
    )
    return attrs + (f' data-q="{html.escape(q.lower())}"' if q else "")


def area_group(area: str, t: dict, floor: dict | None, was: dict | None, files: list[dict]) -> str:
    """An area's row, and its files' rows under it, shown when it is opened."""
    fl = floor or {}
    floor_text = f"{pct(fl.get('lines'))} / {pct(fl.get('branches'))}" if floor else ""
    floor_text = floor_text.replace("% /", " /")
    rows = [
        f"<tr class='head'{sort_keys(area, t, area)}><th><span class='caret'></span>"
        f"{html.escape(area)}</th>{cells(t, floor, was)}<td class='n'>{t['files']:,}</td>"
        f"<td class='floor'>{floor_text}</td></tr>"
    ]
    for f in files:
        name = html.escape(short(f["path"]))
        link = f"<a href='{html.escape(f['report'])}'>{name}</a>" if f.get("report") else name
        rows.append(
            f"<tr class='file'{sort_keys(short(f['path']), f, f['path'])}><th>{link}</th>"
            f"{cells(f)}<td></td><td></td></tr>"
        )
    return f"<tbody class='area'>{''.join(rows)}</tbody>"


def banner(areas: dict) -> str:
    """The headline: everything as one, and each side."""
    t = coverage.total(areas)
    sides = " · ".join(
        f"{name} <b>{pct(coverage.total(areas, prefix)['lines'])}</b>"
        for name, prefix in (
            ("Server", "server/"),
            ("Browser", "browser/"),
            ("Connector", "connector"),
        )
    )
    return (
        f"<div class='banner'><div class='label'>Overall</div>"
        f"<div><div class='big'>{pct(t['lines'])}</div>"
        f"<div>of {t['lineCount']:,} lines reached</div></div>"
        f"<div><div class='big b'>{pct(t['branches'])}</div>"
        f"<div>of {t['branchCount']:,} branches taken</div></div>"
        f"<div class='sides'><div>Lines by side</div><div>{sides}</div>"
        f"<div>{t['files']:,} files</div></div></div>"
    )


def page(history: list[dict], floors: dict, files: list[dict], base: str, repo: str) -> str:
    last = history[-1]
    before = history[-2] if len(history) > 1 else None
    areas = ["server", "browser", *last["areas"]]
    commit = html.escape(last["commit"][:7])
    pr = f' (<a href="{repo}/pull/{last["pr"]}">#{last["pr"]}</a>)' if last["pr"] else ""

    by_area: dict[str, list[dict]] = {}
    for f in files:
        by_area.setdefault(f["area"], []).append(f)
    groups = []
    for area, t in last["areas"].items():
        was = (before["areas"].get(area) if before else None) or None
        groups.append(area_group(area, t, floors.get(area), was, by_area.get(area, [])))
    sums = []
    for name, prefix in coverage.SUMS:
        t = coverage.total(last["areas"], prefix)
        was = coverage.total(before["areas"], prefix) if before else None
        sums.append(
            f"<tr class='sum'><th>{name}</th>{cells(t, None, was)}"
            f"<td class='n'>{t['files']:,}</td><td></td></tr>"
        )

    figures = []
    for area in areas:
        latest = " · ".join(keyed(k, f"{name} {pct(figure(last, area, k))}") for k, name in SERIES)
        figures.append(
            f'<figure class="chart" data-area="{html.escape(area)}"><figcaption>'
            f"<b>{html.escape(area)}</b><span>{latest}</span></figcaption>"
            f'{chart(history, area)}<div class="tip" hidden></div></figure>'
        )

    merges = []
    for h in reversed(history):
        link = f'<a href="{repo}/commit/{h["commit"]}">{html.escape(h["commit"][:7])}</a>'
        pr_cell = f'<a href="{repo}/pull/{h["pr"]}">#{h["pr"]}</a>' if h["pr"] else ""
        figs = "".join(
            f"<td>{pct(figure(h, a, k))}</td>" for a in ("server", "browser") for k, _ in SERIES
        )
        merges.append(
            f"<tr><td>{html.escape(h['date'][:10])}</td><td>{pr_cell}</td><td>{link}</td>{figs}"
            f"<td class='subject'>{html.escape(h['subject'])}</td></tr>"
        )

    data = {
        "frame": {"w": W, "left": LEFT, "right": RIGHT},
        "merges": [{"label": label(h), "date": h["date"][:10]} for h in history],
        "series": {a: {k: [figure(h, a, k) for h in history] for k, _ in SERIES} for a in areas},
    }
    script = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.format(
        commit=commit,
        commit_url=f"{repo}/commit/{last['commit']}",
        pr=pr,
        subject=html.escape(last["subject"]),
        date=html.escape(last["date"][:10]),
        merges_count=len(history),
        banner=banner(last["areas"]),
        groups="\n".join(groups),
        sums="\n".join(sums),
        figures="\n".join(figures),
        merges="\n".join(merges),
        data=script,
        base=html.escape(base),
    )


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MoolaKata coverage</title>
<style>
:root {{
  color-scheme: light;
  --surface: #fcfcfb; --raised: #f3f2ee; --text: #0b0b0b; --text-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --track: #e9e8e2; --border: rgba(11, 11, 11, 0.10);
  --lines: #2a78d6; --branches: #eb6834; --bad: #c8312b;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    color-scheme: dark;
    --surface: #1a1a19; --raised: #232321; --text: #f0efec; --text-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --track: #34342f; --border: rgba(255, 255, 255, 0.10);
    --lines: #3987e5; --branches: #d95926; --bad: #e5534b;
  }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0 auto; max-width: 1400px; padding: 24px 16px 48px; background: var(--surface);
  color: var(--text); font: 19px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }}
a {{ color: inherit; }}
h1 {{ font-size: 29px; margin: 0 0 4px; }}
h2 {{ font-size: 21px; margin: 32px 0 8px; }}
p {{ margin: 4px 0; color: var(--text-2); }}
table {{ border-collapse: collapse; font-variant-numeric: tabular-nums; }}
th, td {{ padding: 5px 10px; border-bottom: 1px solid var(--border); text-align: right;
  white-space: nowrap; }}
th:first-child, td.subject {{ text-align: left; }}
thead th {{ color: var(--text-2); font-weight: 600; }}
td.delta, td.floor {{ color: var(--text-2); }}
td.subject {{ white-space: normal; color: var(--text-2); }}
.scroll {{ overflow-x: auto; }}

.banner {{ display: flex; flex-wrap: wrap; gap: 16px 48px; align-items: flex-end;
  margin: 20px 0 8px; padding: 20px 24px; border: 1px solid var(--border); border-radius: 12px;
  background: var(--raised); color: var(--text-2); }}
.banner .big {{ font-size: 47px; font-weight: 700; line-height: 1.1; color: var(--lines);
  font-variant-numeric: tabular-nums; }}
.banner .big.b {{ color: var(--branches); }}
.banner .label {{ width: 100%; margin-bottom: -12px; font-weight: 600; }}
.banner .sides {{ margin-left: auto; text-align: right; }}
.banner .sides b {{ color: var(--text); }}

.tools {{ display: flex; gap: 16px; align-items: center; margin: 12px 0; color: var(--text-2); }}
.tools input {{ font: inherit; width: 22em; padding: 6px 10px; color: var(--text);
  background: var(--surface); border: 1px solid var(--border); border-radius: 6px; }}
#areas thead th button {{ font: inherit; color: inherit; background: none; border: 0; padding: 0;
  cursor: pointer; }}
#areas thead th[aria-sort] button::after {{ content: " ↑"; }}
#areas thead th[aria-sort="descending"] button::after {{ content: " ↓"; }}
#areas thead th[data-key="lines"], #areas thead th[data-key="branches"] {{ text-align: left; }}
#areas tbody.area tr.head {{ cursor: pointer; }}
#areas tbody.area tr.head:hover {{ background: var(--raised); }}
#areas tbody.area tr.head th {{ font-weight: 600; }}
.caret {{ display: inline-block; width: 1em; color: var(--muted); }}
.caret::before {{ content: "▸"; }}
tbody.open .caret::before, tbody.found .caret::before {{ content: "▾"; }}
#areas tr.file {{ display: none; font-size: 17px; }}
#areas tbody.open tr.file, #areas tbody.found tr.file {{ display: table-row; }}
#areas tbody.area tr.file.miss {{ display: none; }}
#areas tr.file th {{ padding-left: 40px; font-weight: 400; }}
#areas tr.file th a {{ text-decoration: none; }}
#areas tr.file th a:hover {{ text-decoration: underline; }}
#areas tfoot th, #areas tfoot td {{ font-weight: 600; border-bottom: 0; }}
#areas tfoot tr:first-child > * {{ border-top: 2px solid var(--grid); }}
#areas tfoot tr:last-child > * {{ font-size: 21px; }}
td.m {{ text-align: left; }}
td.n {{ color: var(--text-2); }}
.meter {{ position: relative; display: inline-block; width: 110px; height: 12px;
  vertical-align: middle; border-radius: 6px; background: var(--track); }}
#areas tr.file .meter {{ height: 8px; }}
.meter b {{ position: absolute; inset: 0 auto 0 0; border-radius: 6px; }}
.meter.lines b {{ background: var(--lines); }}
.meter.branches b {{ background: var(--branches); }}
.meter.below b {{ background: var(--bad); }}
.meter.none {{ visibility: hidden; }}
.meter i {{ position: absolute; top: -4px; bottom: -4px; width: 2px; margin-left: -1px;
  background: var(--text); }}
.pct {{ display: inline-block; width: 3.9em; text-align: right; }}
.delta {{ display: inline-block; width: 3.2em; text-align: right; font-size: 16px;
  color: var(--text-2); }}

.legend {{ display: flex; gap: 16px; color: var(--text-2); margin: 8px 0 12px; }}
.key {{ display: inline-block; width: 14px; height: 2px; vertical-align: middle;
  margin-right: 6px; border-radius: 1px; }}
.key.lines {{ background: var(--lines); }}
.key.branches {{ background: var(--branches); }}
.charts {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 16px; }}
figure {{ position: relative; margin: 0; padding: 10px 12px 4px; border: 1px solid var(--border);
  border-radius: 8px; }}
figcaption {{ font-size: 17px; }}
figcaption > span {{ display: block; color: var(--text-2); font-size: 16px;
  font-variant-numeric: tabular-nums; }}
svg {{ display: block; width: 100%; height: auto; overflow: visible; }}
.grid {{ stroke: var(--grid); stroke-width: 1; }}
.axis {{ fill: var(--muted); font-size: 13px; }}
.line {{ fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }}
.line.lines {{ stroke: var(--lines); }}
.line.branches {{ stroke: var(--branches); }}
.dot {{ stroke: var(--surface); stroke-width: 2; }}
.dot.lines {{ fill: var(--lines); }}
.dot.branches {{ fill: var(--branches); }}
.cross {{ stroke: var(--muted); stroke-width: 1; }}
.tip {{ position: absolute; pointer-events: none; padding: 6px 8px; border-radius: 6px;
  background: var(--surface); border: 1px solid var(--border); color: var(--text);
  font-size: 16px; white-space: nowrap; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12); }}
.tip div {{ color: var(--text-2); }}
details summary {{ cursor: pointer; font-weight: 600; margin: 32px 0 8px; }}
</style>
</head>
<body>
<h1>MoolaKata coverage</h1>
<p>As of <a href="{commit_url}">{commit}</a>{pr}, {date}: {subject}</p>
{banner}
<p>What the tests reach, measured by <code>web/check</code> on each merge to <code>main</code>.
Line by line: <a href="server/index.html">the server and the connector</a>,
<a href="browser/index.html">the browser app</a>. The history:
<a href="history.json">history.json</a> ({merges_count} merges); each file's counts:
<a href="files.json">files.json</a>.</p>

<h2>By area</h2>
<div class="tools"><input id="filter" type="search"
 placeholder="Filter files, e.g. ledger or share.js" aria-label="Filter files">
<span>Click an area for its files, a heading to sort.</span></div>
<div class="scroll"><table id="areas">
<thead><tr><th data-key="name"><button>Area</button></th>
<th data-key="lines"><button>Lines</button></th>
<th data-key="lc"><button>Lines reached</button></th>
<th data-key="branches"><button>Branches</button></th>
<th data-key="bc"><button>Branches taken</button></th><th>Files</th>
<th title="The floor: lines / branches">Floor</th></tr></thead>
{groups}
<tfoot>
{sums}
</tfoot>
</table></div>
<p>The change is since the merge before. The tick on a bar is the area's floor (its lines' /
branches' in the last column), and a bar below it is red. <i>Server</i> and <i>Browser</i> are
their areas together; <i>Overall</i> is every area, the connector's too. Sorting by a count
sorts by size.</p>

<h2>Over the merges</h2>
<div class="legend"><span><span class="key lines"></span>Lines</span>
<span><span class="key branches"></span>Branches</span></div>
<div class="charts">
{figures}
</div>

<details>
<summary>Every merge</summary>
<div class="scroll"><table>
<thead><tr><th>Date</th><th>PR</th><th>Commit</th><th>Server lines</th><th>Server branches</th>
<th>Browser lines</th><th>Browser branches</th><th>Subject</th></tr></thead>
<tbody>
{merges}
</tbody>
</table></div>
</details>

<script type="application/json" id="data">{data}</script>
<script>
(() => {{
  // By area: sorting by a heading, opening an area, and the filter.
  const table = document.getElementById("areas");
  const groups = [...table.tBodies];
  const sort = {{ key: "lines", dir: 1 }};
  const value = (tr) => {{
    const v = tr.dataset[sort.key];
    return sort.key === "name" ? v.toLowerCase() : v === "" ? null : Number(v);
  }};
  const byKey = (a, b) => {{
    const x = value(a), y = value(b);
    if (x === y) return a.dataset.name.localeCompare(b.dataset.name);
    if (x === null) return 1;
    if (y === null) return -1;
    return (x < y ? -1 : 1) * sort.dir;
  }};
  const order = () => {{
    groups.sort((g, h) => byKey(g.rows[0], h.rows[0]));
    for (const g of groups) {{
      table.insertBefore(g, table.tFoot);
      g.append(...[...g.rows].slice(1).sort(byKey));
    }}
    for (const th of table.tHead.querySelectorAll("th[data-key]")) {{
      if (th.dataset.key === sort.key) {{
        th.setAttribute("aria-sort", sort.dir > 0 ? "ascending" : "descending");
      }} else th.removeAttribute("aria-sort");
    }}
  }};
  for (const th of table.tHead.querySelectorAll("th[data-key]")) {{
    th.querySelector("button").addEventListener("click", () => {{
      sort.dir = sort.key === th.dataset.key ? -sort.dir : 1;
      sort.key = th.dataset.key;
      order();
    }});
  }}
  for (const g of groups) {{
    g.rows[0].addEventListener("click", () => g.classList.toggle("open"));
  }}
  const filter = document.getElementById("filter");
  filter.addEventListener("input", () => {{
    const q = filter.value.trim().toLowerCase();
    for (const g of groups) {{
      let found = false;
      for (const tr of [...g.rows].slice(1)) {{
        const hit = !q || tr.dataset.q.includes(q);
        tr.classList.toggle("miss", !hit);
        found ||= Boolean(q) && hit;
      }}
      g.classList.toggle("found", found);
      g.hidden = Boolean(q) && !found && !g.rows[0].dataset.q.includes(q);
    }}
  }});
  order();

  // The charts: each merge's figures on hover.
  const data = JSON.parse(document.getElementById("data").textContent);
  const {{ w, left, right }} = data.frame;
  const n = data.merges.length;
  const pct = (v) => (v == null ? "—" : v.toFixed(1) + "%");
  for (const fig of document.querySelectorAll("figure.chart")) {{
    const svg = fig.querySelector("svg");
    const cross = svg.querySelector(".cross");
    const tip = fig.querySelector(".tip");
    const series = data.series[fig.dataset.area];
    svg.addEventListener("pointermove", (e) => {{
      const box = svg.getBoundingClientRect();
      const x = ((e.clientX - box.left) / box.width) * w;
      const step = n > 1 ? (w - left - right) / (n - 1) : 0;
      const i = n > 1 ? Math.max(0, Math.min(n - 1, Math.round((x - left) / step))) : 0;
      const at = n > 1 ? left + i * step : left + (w - left - right) / 2;
      cross.setAttribute("x1", at);
      cross.setAttribute("x2", at);
      cross.setAttribute("visibility", "visible");
      const m = data.merges[i];
      tip.innerHTML = "";
      const head = document.createElement("b");
      head.textContent = m.label + " · " + m.date;
      tip.append(head);
      for (const [kind, name] of [["lines", "Lines"], ["branches", "Branches"]]) {{
        const row = document.createElement("div");
        const key = document.createElement("span");
        key.className = "key " + kind;
        row.append(key, name + " " + pct(series[kind][i]));
        tip.append(row);
      }}
      tip.hidden = false;
      const fbox = fig.getBoundingClientRect();
      const px = box.left - fbox.left + (at / w) * box.width;
      const room = fbox.width - tip.offsetWidth - 8;
      const left_ = px + 12 > room ? px - tip.offsetWidth - 12 : px + 12;
      tip.style.left = Math.max(8, Math.min(room, left_)) + "px";
      tip.style.top = box.top - fbox.top + 8 + "px";
    }});
    svg.addEventListener("pointerleave", () => {{
      cross.setAttribute("visibility", "hidden");
      tip.hidden = true;
    }});
  }}
}})();
</script>
<!-- built from {base} -->
</body>
</html>
"""


# ---------- building it ----------


def build() -> int:
    totals_file = coverage.OUT / "totals.json"
    if not totals_file.exists():
        print("nothing measured: run web/check or web/dev.sh coverage first")
        return 1
    areas = json.loads(totals_file.read_text())
    base = site_url()
    nonce = os.environ.get("GITHUB_RUN_ID") or str(os.getpid())
    try:
        history = fetch_history(base, nonce)
    except (OSError, ValueError) as e:
        if in_ci():
            raise
        print(f"{base}history.json couldn't be read ({e}); the preview starts without it")
        history = []
    history = add(history, entry(areas))
    shutil.rmtree(SITE, ignore_errors=True)
    SITE.mkdir(parents=True)
    for part in ("server", "browser"):
        if (coverage.OUT / "html" / part).is_dir():
            shutil.copytree(coverage.OUT / "html" / part, SITE / part)
    (SITE / "history.json").write_text(
        "[\n" + ",\n".join(json.dumps(h, sort_keys=True) for h in history) + "\n]\n"
    )
    files_file = coverage.OUT / "files.json"
    files = json.loads(files_file.read_text()) if files_file.exists() else []
    if files_file.exists():
        shutil.copy(files_file, SITE / "files.json")
    (SITE / "index.html").write_text(page(history, coverage.floors(), files, base, repo_url()))
    print(f"{SITE / 'index.html'}: {len(history)} merges" + ("" if in_ci() else ", a preview"))
    return 0
