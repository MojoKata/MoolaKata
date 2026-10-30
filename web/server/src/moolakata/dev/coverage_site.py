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


def page(history: list[dict], floors: dict, base: str, repo: str) -> str:
    last = history[-1]
    before = history[-2] if len(history) > 1 else None
    areas = ["server", "browser", *last["areas"]]
    commit = html.escape(last["commit"][:7])
    pr = f' (<a href="{repo}/pull/{last["pr"]}">#{last["pr"]}</a>)' if last["pr"] else ""

    rows = []
    for area in areas:
        cells = [f"<th>{html.escape(area)}</th>"]
        for kind, _ in SERIES:
            now = figure(last, area, kind)
            was = figure(before, area, kind) if before else None
            cells.append(f"<td>{pct(now)}</td><td class='delta'>{change(now, was)}</td>")
        fl = floors.get(area)
        floor = f"{pct(fl.get('lines'))} / {pct(fl.get('branches'))}" if fl else ""
        cells.append(f"<td class='floor'>{floor}</td>")
        sum_ = " class=sum" if area in ("server", "browser") else ""
        rows.append(f"<tr{sum_}>{''.join(cells)}</tr>")

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
        rows="\n".join(rows),
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
  --surface: #fcfcfb; --text: #0b0b0b; --text-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --border: rgba(11, 11, 11, 0.10);
  --lines: #2a78d6; --branches: #eb6834;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    color-scheme: dark;
    --surface: #1a1a19; --text: #f0efec; --text-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --border: rgba(255, 255, 255, 0.10);
    --lines: #3987e5; --branches: #d95926;
  }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0 auto; max-width: 1180px; padding: 24px 16px 48px; background: var(--surface);
  color: var(--text); font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }}
a {{ color: inherit; }}
h1 {{ font-size: 22px; margin: 0 0 4px; }}
h2 {{ font-size: 16px; margin: 32px 0 8px; }}
p {{ margin: 4px 0; color: var(--text-2); }}
table {{ border-collapse: collapse; font-variant-numeric: tabular-nums; }}
th, td {{ padding: 4px 10px; border-bottom: 1px solid var(--border); text-align: right;
  white-space: nowrap; }}
th:first-child, td.subject {{ text-align: left; }}
thead th {{ color: var(--text-2); font-weight: 600; }}
tr.sum th, tr.sum td {{ font-weight: 600; }}
td.delta, td.floor {{ color: var(--text-2); }}
td.subject {{ white-space: normal; color: var(--text-2); }}
.scroll {{ overflow-x: auto; }}
.legend {{ display: flex; gap: 16px; color: var(--text-2); margin: 8px 0 12px; }}
.key {{ display: inline-block; width: 14px; height: 2px; vertical-align: middle;
  margin-right: 6px; border-radius: 1px; }}
.key.lines {{ background: var(--lines); }}
.key.branches {{ background: var(--branches); }}
.charts {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px; }}
figure {{ position: relative; margin: 0; padding: 10px 12px 4px; border: 1px solid var(--border);
  border-radius: 8px; }}
figcaption {{ font-size: 13px; }}
figcaption > span {{ display: block; color: var(--text-2); font-size: 12px;
  font-variant-numeric: tabular-nums; }}
svg {{ display: block; width: 100%; height: auto; overflow: visible; }}
.grid {{ stroke: var(--grid); stroke-width: 1; }}
.axis {{ fill: var(--muted); font-size: 10px; }}
.line {{ fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }}
.line.lines {{ stroke: var(--lines); }}
.line.branches {{ stroke: var(--branches); }}
.dot {{ stroke: var(--surface); stroke-width: 2; }}
.dot.lines {{ fill: var(--lines); }}
.dot.branches {{ fill: var(--branches); }}
.cross {{ stroke: var(--muted); stroke-width: 1; }}
.tip {{ position: absolute; pointer-events: none; padding: 6px 8px; border-radius: 6px;
  background: var(--surface); border: 1px solid var(--border); color: var(--text);
  font-size: 12px; white-space: nowrap; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12); }}
.tip div {{ color: var(--text-2); }}
details summary {{ cursor: pointer; font-weight: 600; margin: 32px 0 8px; }}
</style>
</head>
<body>
<h1>MoolaKata coverage</h1>
<p>As of <a href="{commit_url}">{commit}</a>{pr}, {date}: {subject}</p>
<p>What the tests reach, measured by <code>web/check</code> on each merge to <code>main</code>.
Line by line: <a href="server/index.html">the server and the connector</a>,
<a href="browser/index.html">the browser app</a>. The history:
<a href="history.json">history.json</a> ({merges_count} merges).</p>

<h2>By area</h2>
<div class="scroll"><table>
<thead><tr><th>Area</th><th>Lines</th><th></th><th>Branches</th><th></th>
<th>Floor (lines / branches)</th></tr></thead>
<tbody>
{rows}
</tbody>
</table></div>
<p>The change is since the merge before. <i>server</i> and <i>browser</i> are their areas as
one, weighted by lines.</p>

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
    (SITE / "index.html").write_text(page(history, coverage.floors(), base, repo_url()))
    print(f"{SITE / 'index.html'}: {len(history)} merges" + ("" if in_ci() else ", a preview"))
    return 0
