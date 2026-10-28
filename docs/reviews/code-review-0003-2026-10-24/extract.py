"""Collect review 3's claims from the work pad: ids, table fields and bodies, in section order."""

import json
import re
import sys
from collections import Counter
from pathlib import Path

PAD = Path(sys.argv[1])
FILES = [
    "docs-1-money.md",
    "docs-2-platform.md",
    "docs-3-protocols.md",
    "docs-compare.md",
    *sorted(p.name for p in PAD.glob("unit-[01][0-9]-*.md")),
]
WID = r"(?:DC|D\d|U\d\d)-\d+"
HEAD = re.compile(rf"^(#{{3,4}}) ({WID}):\s*(.*)$")
STRIP = re.compile(r"\s*\*\*(?:Severity|Sev|Conf|Confirmations|Status):\*\*\s*[^*\n]*?\.(?=\s|$)")


def table(lines):
    """The last table whose first column is Id and that has a Sev column."""
    best = None
    for i, line in enumerate(lines):
        if re.match(r"^\| *Id *\|", line) and "Sev" in line:
            cols = [c.strip() for c in line.strip().strip("|").split("|")]
            rows = {}
            for r in lines[i + 2 :]:
                if not r.startswith("|"):
                    break
                cells = [c.strip() for c in r.strip().strip("|").split("|")]
                d = dict(zip(cols, cells, strict=False))
                rid = re.sub(r"[\[\]`*]|\(.*?\)", "", d.get("Id", "")).strip()
                if re.fullmatch(WID, rid):
                    rows[rid] = d
            best = (cols, rows)
    return best[1] if best else {}


def bodies(lines):
    out, cur, in_claims = {}, None, False
    for line in lines:
        if line.startswith("## "):
            in_claims = line.strip() == "## Claims"
            cur = None
            continue
        if not in_claims:
            continue
        m = HEAD.match(line)
        if m:
            cur = m.group(2)
            out[cur] = {"title": m.group(3).strip(), "body": []}
            continue
        if re.match(r"^#{2,4} ", line):
            cur = None
            continue
        if cur:
            out[cur]["body"].append(line)
    for v in out.values():
        text = "\n".join(v["body"]).strip("\n")
        v["body"] = STRIP.sub("", text)
    return out


claims, joined = [], set()
for name in FILES:
    lines = (PAD / name).read_text().splitlines()
    rows, bods = table(lines), bodies(lines)
    for wid, b in bods.items():
        r = rows.get(wid, {})
        sev = next((r[k] for k in r if k.startswith("Sev")), "")
        req = r.get("Req", r.get("Ids compared", ""))
        kind = r.get("Kind", "")
        line = next((r[k] for k in ("Description", "One line", "In one line") if k in r), "")
        withheld = b["title"].lower().startswith("withheld") or "withheld.md" in b["body"][:400]
        if name == "docs-compare.md" and "join" in (line + b["title"]).lower():
            joined.update(re.findall(r"\bD\d-\d+\b", b["title"] + " " + req))
        claims.append(
            {
                "wid": wid,
                "file": name,
                "title": b["title"],
                "sev": sev.replace("*", ""),
                "req": req,
                "kind": kind,
                "line": line,
                "withheld": withheld,
                "body": b["body"],
            }
        )
    missing = set(rows) - set(bods)
    if missing:
        print(f"{name}: in the table but no body: {sorted(missing)}", file=sys.stderr)
for c in claims:
    c["joined_into"] = None
    if c["wid"] in joined:
        c["joined_into"] = next(
            d["wid"]
            for d in claims
            if d["file"] == "docs-compare.md"
            and re.search(rf"\b{c['wid']}\b", d["title"] + " " + d["req"])
        )
n = 0
for c in claims:
    if c["joined_into"]:
        continue
    n += 1
    c["cr"] = f"CR3-{n}"
for c in claims:
    if c["joined_into"]:
        c["cr"] = next(d["cr"] for d in claims if d["wid"] == c["joined_into"])
Path(sys.argv[2]).write_text(json.dumps(claims, indent=1))
print(len(claims), "claims;", n, "ids;", "joined:", sorted(joined))
print(Counter((c["sev"] or "?") for c in claims if not c["joined_into"]))
print("no sev:", [c["wid"] for c in claims if not c["sev"]][:20])
print("withheld:", [c["wid"] for c in claims if c["withheld"]])
