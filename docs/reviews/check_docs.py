"""The mechanical checks a review starts with (docs/REVIEW.md, Phase 0).

    python3 docs/reviews/check_docs.py [--cites FILE] [--quiet]

Reads the requirements, the other documents under docs/ and the code's comments, and reports:

1. ids cited that name nothing: a requirement item (S9.8.7, R1.16) that no section numbers,
   or a gap, question or later item (G8, Q8, L8) that is not open;
2. the README's tables of sections, gaps, questions and later work against the files;
3. section files past 500 lines;
4. words and dates a statement doesn't carry (docs/requirements and docs/schema.md), for a
   reader to judge: some are fine in context;
5. the schema's prefix tables out of byte order, or a prefix used twice;
6. the next free G, Q and L numbers, counted over the files and the requirements' history (a
   floor: a question asked while building may have taken a number no file shows).

--cites writes, for every requirement item, the code files that cite it (tab separated), the
start of Phase 0's map. Exits 1 if any of 1, 2, 3 or 5 found something; 4 never fails.
--quiet prints only those problems: `web/check` runs it so (requirements S17.5).
"""

import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQ = ROOT / "docs" / "requirements"
SCHEMA = ROOT / "docs" / "schema.md"
MAX_LINES = 500

# Documents whose citations must resolve. Reviews and the handoff record history, so they may
# cite what has since gone.
DOCS = [p for p in sorted((ROOT / "docs").glob("*.md")) if p.name != "handoff.md"]
DOCS += [*sorted(REQ.glob("*.md")), ROOT / "README.md", ROOT / "docs/mockups/MoolaKata-mock.html"]
CODE_DIRS = ["web/server/src", "connector", "web/ui"]
CODE_SKIP = ("web/ui/vendor/",)

ITEM = re.compile(r"(?<![\w.])([SR]\d+(?:\.\d+)*)(?![\w])")
DOTTED = re.compile(r"(?<![\w.])([SR]\d+\.\d+(?:\.\d+)*)(?![\w])")
TRACKED = re.compile(r"(?<![\w-])([GQL])(\d+)(?![\w])")
RANGE = re.compile(r"(?<![\w-])([GQL])(\d+)\s*[–-]\s*\1?(\d+)(?![\w])")
# Not citations: examples (`G8`, "G1, G2, …") and where numbering stands ("after G24").
NOT_CITED = re.compile(r"`[GQL]\d+`|\b([GQL])1, \1?2, …|\bafter [GQL]\d+")
LIST_ITEM = re.compile(r"^( *)(\d+)\. ")
CHANGELOG = re.compile(
    r"\b(now|no longer|revised|proposed|approved|previously|formerly|used to|"
    r"(?:19|20)\d\d-\d\d-\d\d|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* "
    r"(?:\d{1,2}, )?(?:19|20)\d\d)\b",
    re.IGNORECASE,
)


def numbered_items(path: Path, top: str) -> set[str]:
    """Every id a file's numbered lists give, nested by indentation: S7.1, S7.1.2, …"""
    ids = {top}
    stack: list[tuple[int, int, int]] = []  # (indent, number, content indent)
    fenced = False
    for line in path.read_text().splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        m = LIST_ITEM.match(line)
        if fenced or not m:
            continue
        indent, number = len(m.group(1)), int(m.group(2))
        while stack and indent < stack[-1][2]:
            stack.pop()
        ids.add(".".join([top] + [str(s[1]) for s in stack] + [str(number)]))
        stack.append((indent, number, m.end()))
    return ids


def requirement_ids() -> set[str]:
    ids: set[str] = set()
    for path in REQ.glob("S*.md"):
        # A split item's own file keeps the item's number on it, so it numbers from the top too.
        ids |= numbered_items(path, re.match(r"S\d+", path.name).group(0))
    readme = (REQ / "README.md").read_text().split("\n# ")
    for part in readme[1:]:
        head = re.match(r"(R\d+)\.", part)
        if head:
            tmp = REQ / ".readme-part"
            tmp.write_text(part.split("\n", 1)[1])
            try:
                ids |= numbered_items(tmp, head.group(1))
            finally:
                tmp.unlink()
    return ids


def open_tracked() -> dict[str, set[int]]:
    found: dict[str, set[int]] = {}
    for letter, name in (("G", "gaps.md"), ("Q", "questions.md"), ("L", "later.md")):
        text = (REQ / name).read_text()
        found[letter] = {int(n) for n in re.findall(rf"^## {letter}(\d+):", text, re.M)}
    return found


def git(*args: str) -> str:
    return subprocess.run(  # noqa: S603 (fixed arguments)
        ["git", *args],  # noqa: S607 (git from PATH)
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def code_files() -> list[Path]:
    out = git("ls-files", *CODE_DIRS).split()
    return [ROOT / f for f in out if not f.startswith(CODE_SKIP) and (ROOT / f).is_file()]


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


def main(argv: list[str]) -> int:
    problems: list[str] = []
    warnings: list[str] = []
    items = requirement_ids()
    tracked = open_tracked()

    # 1. Citations that name nothing.
    def check_text(path: Path, text: str, pattern: re.Pattern) -> None:
        own = path.name in ("gaps.md", "questions.md", "later.md")
        for n, line in enumerate(text.splitlines(), 1):
            for m in pattern.finditer(line):
                ident = m.group(1)
                # A cited item resolves if it, or the item it is under, is numbered.
                if ident not in items and not ident.startswith(("S0", "R0")):
                    problems.append(f"{rel(path)}:{n}: {ident} is numbered by no section")
            if own and "answered" in line:
                continue
            if path.suffix != ".md":  # the mockup's Q1 is a quarter
                continue
            spans = [r.span() for r in RANGE.finditer(line)]
            spans += [r.span() for r in NOT_CITED.finditer(line)]
            for m in TRACKED.finditer(line):
                if any(a <= m.start() < b for a, b in spans):
                    continue
                letter, num = m.group(1), int(m.group(2))
                if num not in tracked[letter]:
                    problems.append(f"{rel(path)}:{n}: {letter}{num} is not open in its file")

    for path in DOCS:
        check_text(path, path.read_text(), ITEM)
    cites: dict[str, set[str]] = defaultdict(set)
    for path in code_files():
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for m in DOTTED.finditer(line):
                ident = m.group(1)
                cites[ident].add(rel(path))
                if ident not in items:
                    problems.append(f"{rel(path)}:{n}: {ident} is numbered by no section")

    # 2. The README's tables against the files.
    readme = (REQ / "README.md").read_text()
    listed = set(re.findall(r"^\| \*\*(S\d+)\*\* \| \[[^]]+\]\((S\d+-[\w-]+\.md)\)", readme, re.M))
    files = {
        (re.match(r"S\d+", p.name).group(0), p.name)
        for p in REQ.glob("S*.md")
        if not re.match(r"S\d+-[\w-]+?-\d+-", p.name)
    }
    for sid, name in sorted(files - listed):
        problems.append(f"docs/requirements/README.md: section {sid} ({name}) is not in its table")
    for sid, name in sorted(listed - files):
        problems.append(f"docs/requirements/README.md: {sid} links {name}, which is not there")
    for letter, ids in tracked.items():
        in_table = {int(n) for n in re.findall(rf"^\| \*\*{letter}(\d+)\*\* \|", readme, re.M)}
        for n in sorted(ids - in_table):
            problems.append(
                f"docs/requirements/README.md: {letter}{n} is open but not in its table"
            )
        for n in sorted(in_table - ids):
            problems.append(
                f"docs/requirements/README.md: {letter}{n} is in its table but not open"
            )

    # 3. Section files past the limit.
    for path in sorted(REQ.glob("S*.md")):
        lines = len(path.read_text().splitlines())
        if lines > MAX_LINES:
            problems.append(f"{rel(path)}: {lines} lines, past {MAX_LINES}: split it (README)")

    # 4. Words and dates a statement doesn't carry.
    for path in [*sorted(REQ.glob("*.md")), SCHEMA]:
        for n, line in enumerate(path.read_text().splitlines(), 1):
            # Labels, examples and code (*Lock now*, `2026-10-09`) are not the text's own words.
            prose = re.sub(r"`[^`]*`|\*\*[^*]*\*\*|\*[^*]*\*", " ", line)
            for m in CHANGELOG.finditer(prose):
                warnings.append(f'{rel(path)}:{n}: "{m.group(0)}": {line.strip()[:90]}')

    # 5. The schema's prefixes.
    seen: dict[str, str] = {}
    for block in re.split(r"^### ", SCHEMA.read_text(), flags=re.M)[1:]:
        title = block.split("\n", 1)[0]
        prefixes = re.findall(r"^\| ([A-Z][A-Za-z]{0,4}) +\|", block, re.M)
        prefixes = [p for p in prefixes if p != "Prefix"]
        if prefixes != sorted(prefixes):
            first = next(a for a, b in zip(prefixes, sorted(prefixes), strict=True) if a != b)
            problems.append(f"docs/schema.md: §{title}: prefixes out of byte order at {first}")
        for p in prefixes:
            if p in seen:
                problems.append(f"docs/schema.md: prefix {p} in both §{seen[p]} and §{title}")
            seen[p] = title

    # 6. The next free numbers: past every id ever used, in the files or the history.
    history = git("log", "-p", "--format=", "--", "docs/requirements")
    corpus = history + "".join(p.read_text() for p in REQ.glob("*.md"))
    nxt = {}
    for letter in "GQL":
        used = [int(n) for n in re.findall(rf"(?<![\w-]){letter}(\d+)(?![\w])", corpus)]
        nxt[letter] = max(used, default=0) + 1

    # The report. --quiet, as web/check runs it, prints only what fails.
    if "--quiet" in argv:
        if problems:
            print("\n".join(f"   {r}" for r in problems))
        return 1 if problems else 0
    for title, rows in (("Problems", problems), ("To read (words and dates)", warnings)):
        print(f"## {title}: {len(rows)}\n")
        print("\n".join(f"- {r}" for r in rows) or "- none")
        print()
    print("## Next free ids, at least\n")
    print(", ".join(f"{k}{v}" for k, v in nxt.items()))
    print("\nA question asked while building takes a Q number without reaching the files, so")
    print("take the higher of this and the last one the handoff or the commits name.")
    never = sorted(
        (i for i in items if i.count(".") == 1 and i.startswith("S") and i not in cites),
        key=lambda s: [int(x) for x in s[1:].split(".")],
    )
    print(f"\n## First-level items no code cites: {len(never)}\n")
    print(", ".join(never) or "none")

    if "--cites" in argv:
        out = Path(argv[argv.index("--cites") + 1])
        order = sorted(items, key=lambda s: (s[0], [int(x) for x in s[1:].split(".")]))
        out.write_text("".join(f"{i}\t{' '.join(sorted(cites.get(i, ())))}\n" for i in order))
        print(f"\nCitations by item written to {out}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
