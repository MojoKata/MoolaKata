"""Render review 3's file from claims.json: the table and one section per unit, with markers the
assembly session fills (header, summary, checked and sound, decisions, where things stand)."""

import json
import re
import sys
from pathlib import Path

claims = json.loads(Path(sys.argv[1]).read_text())
out_path = Path(sys.argv[2])
PADNAME = "code-review-0003-2026-10-24"
UNIT_TITLES = {}
for line in Path(f"docs/reviews/{PADNAME}/map.md").read_text().splitlines():
    m = re.match(r"^\| (\d\d) ([\w-]+) \| (.*?) \|", line)
    if m:
        UNIT_TITLES[m.group(1)] = (m.group(2), m.group(3))
BLOCKS = {
    "docs-1-money.md": "Block docs-1-money: the README (R1–R3) and S1–S9",
    "docs-2-platform.md": "Block docs-2-platform: the README and S10–S18",
    "docs-3-protocols.md": "Block docs-3-protocols: the schema, protocols and runbooks",
    "docs-compare.md": "The digests compared: conflicts between blocks",
}


def one_line(s):
    s = re.sub(r"\s+", " ", s).strip()
    return s.replace("|", "\\|")


o = []
w = o.append
w("# Code review 3: the requirements and documents against the code, read whole\n")
w("<!-- HEADER: filled at assembly (REVIEW.md §10.1) -->\n")
w("## Summary\n")
w("<!-- VERDICT AND WHAT MATTERS MOST: filled at assembly (§10.2) -->\n")
w("| Id | Req | Sev | Conf | Status | Description |")
w("|---|---|---|---|---|---|")
seen = set()
for c in claims:
    if c["joined_into"] or c["cr"] in seen:
        continue
    seen.add(c["cr"])
    req = one_line(c["req"]).split(",")[0].split(" + ")[0].strip() or "—"
    if c["file"] == "docs-compare.md":
        req = one_line(re.sub(r"\s*\(join\)", "", c["req"]))
    line = re.sub(r"\s*\(join\)$", "", c["line"] or c["title"])
    desc = "Withheld until fixed" if c["withheld"] else one_line(line)
    num = c["cr"].split("-")[1]
    w(f"| [{c['cr']}](#cr3-{num}) | {req} | {c['sev']} | 0 | open | {desc} |")
w("")
section = None
for c in claims:
    if c["joined_into"]:
        continue
    f = c["file"]
    if f != section:
        section = f
        if f.startswith("docs-"):
            if f == "docs-1-money.md":
                w("## 1. The documents (Phase 1)\n")
                w("<!-- DOCUMENTS OPENER: filled at assembly (§10.3) -->\n")
            w(f"### {BLOCKS[f]}\n")
            w(f"Work pad: [`{f}`]({PADNAME}/{f}).\n")
        else:
            nn = f[5:7]
            name, secs = UNIT_TITLES.get(nn, (f[8:-3], ""))
            w(f"## {int(nn) + 1}. Unit {nn}: {name}\n")
            w(f"**Sections:** {secs}.\n")
            w(f"<!-- UNIT {nn} OPENER: filled at assembly (§10.3) -->\n")
            w(
                f"Work pad: [`{f}`]({PADNAME}/{f}): the brief, the earlier findings re-checked, "
                "and working notes.\n"
            )
    num = c["cr"].split("-")[1]
    h = "####" if f.startswith("docs-") else "###"
    title = "withheld until fixed" if c["withheld"] else c["title"]
    w(f'<a id="cr3-{num}"></a>\n')
    w(f"{h} {c['cr']}: {title}\n")
    extra = ""
    joins = [d["wid"] for d in claims if d["joined_into"] == c["wid"]]
    if joins:
        extra = f"; it joins {', '.join(joins)}, whose texts are in their blocks' files"
    w(f"*Work pad: {c['wid']} in [`{f}`]({PADNAME}/{f}){extra}.*\n")
    w("Withheld until fixed.\n" if c["withheld"] else c["body"].strip() + "\n")
nunits = len({c["file"] for c in claims if c["file"].startswith("unit-")})
w(f"## {nunits + 2}. Checked and sound\n")
w("<!-- CHECKED AND SOUND: filled at assembly (§10.4) -->\n")
w(f"## {nunits + 3}. Decisions\n")
w("None yet: the claims are walked through with the user in a later session (§11.2).\n")
w(f"## {nunits + 4}. Where things stand\n")
w("<!-- WHERE THINGS STAND: filled at assembly (§10.6) -->\n")
w("## Work-pad ids\n")
w("Each claim's work-pad id, for retracing it in the work pad:\n")
w("| Work pad | Id | Work pad | Id | Work pad | Id | Work pad | Id |")
w("|---|---|---|---|---|---|---|---|")
pairs = [(c["wid"], c["cr"]) for c in claims]
for i in range(0, len(pairs), 4):
    row = pairs[i : i + 4] + [("", "")] * (4 - len(pairs[i : i + 4]))
    w("| " + " | ".join(f"{a} | {b}" for a, b in row) + " |")
out_path.write_text("\n".join(o) + "\n")
print(out_path, len(o), "lines")
