"""No exact decimal is compared with `===` or `!==` (CR3-411).

The browser holds money and quantities as `Dec`, an exact decimal (S12.12). It refuses `<` and
`>`, but `===` and `!==` compare objects, and two equal amounts are two objects: the payoff tab
took every plan for changed. The generated types name every field that is a `Dec`; this lists
each `===` or `!==` beside one in the browser app, which wants `.eq()`.
"""

import re

from moolakata import paths

PROPERTY = re.compile(r"@property \{([^}]*)\} \[?(\w+)\]?")


def dec_fields() -> set[str]:
    """Fields that are a Dec wherever they are text, a number or a flag nowhere (a `value` or a
    `year` that is text in one type would be read wrong)."""
    dec, other = set(), set()
    for kind, name in PROPERTY.findall((paths.UI / "api" / "types.js").read_text()):
        if re.search(r"\.Dec\b", kind):
            dec.add(name)
        elif re.search(r"\b(string|number|boolean)\b", kind):
            other.add(name)  # a list or a record compared by identity is no number either
    return dec - other


def identity_compares(src: str, fields: set[str]) -> list[str]:
    names = "|".join(sorted(fields))
    # A field at the end of a reach (`gift.paid.transactionId` is no `paid`), against anything
    # but null, undefined or a string (a form's own choice named like a field), and never a
    # DOM event's `e.target`.
    beside = re.compile(
        rf"(?<!\be)\.({names})\s*[!=]==(?!\s*(null|undefined)\b|\s*['\"`])|"
        rf"(?<!['\"`])\s[!=]==\s*[\w.]*\.({names})\b(?![.\w(])"
    )
    out = []
    for n, line in enumerate(src.split("\n"), 1):
        if line.strip().startswith(("//", "*", "/*")):
            continue
        if beside.search(line):
            out.append(f"{n}: {line.strip()[:90]}")
    return out


def test_no_exact_decimal_is_compared_by_identity():
    fields = dec_fields()
    assert {"interest", "amount", "balance"} <= fields
    found = []
    for f in sorted(paths.UI.glob("**/*.js")):
        if any(part in f.parts for part in ("vendor", "mockup", "tests", "api")):
            continue
        found += [
            f"{f.relative_to(paths.UI)}:{x}" for x in identity_compares(f.read_text(), fields)
        ]
    assert not found, "an exact decimal compared with === or !== (use .eq()):\n" + "\n".join(found)


def test_the_check_finds_what_it_is_for():
    fields = {"interest", "amount"}
    assert identity_compares("const c = p.interest !== s.interest;", fields)
    assert identity_compares("if (a === b.amount) x();", fields)
    assert not identity_compares("if (p.interest == null) x();", fields)
    assert not identity_compares("if (p.interest === null) x();", fields)
    assert not identity_compares("const c = p.interest.eq(s.interest);", fields)
