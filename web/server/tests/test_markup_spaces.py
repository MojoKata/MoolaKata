"""No word loses its space where a template breaks a line (CR3-409, CR3-410).

The browser's templates (htm) drop whitespace that holds a line break, where a page would show
one space: `of\\n  <b>${name}</b>` reads "ofSpread", `${date}\\n  <span>paid</span>` "Sep 1,
2026paid". This reads every `html` template in the browser app, its text apart from its tags and
values, and lists each line break between two things that sit in a line of text (words, a value,
an inline element or a component): each wants its space written (`${' '}`) or the line joined.
"""

import re

from moolakata import paths

INLINE = {"a", "b", "i", "em", "strong", "code", "span", "small", "abbr", "kbd", "sup", "sub"}
# Components that draw inside a line of text; the rest draw blocks (a field, a dialog, a route).
INLINE_COMPONENTS = {"Amt", "Icon", "Pct", "StatusPill"}


def templates(src: str):
    """Each html`` template: a list of parts, str for its text and ("expr", source) for each
    `${…}`. A template inside another's value is read on its own too."""
    i = 0
    while True:
        i = src.find("html`", i)
        if i < 0:
            return
        parts, _ = _template(src, i + len("html`"))
        yield parts, src.count("\n", 0, i) + 1
        i += len("html`")


def _template(src: str, i: int):
    parts, buf = [], []
    while i < len(src):
        ch = src[i]
        if ch == "\\":
            buf.append(src[i : i + 2])
            i += 2
        elif ch == "`":
            parts.append("".join(buf))
            return parts, i + 1
        elif src.startswith("${", i):
            parts.append("".join(buf))
            buf = []
            end = _expression(src, i + 2)
            parts.append(("expr", src[i + 2 : end - 1].strip()))
            i = end
        else:
            buf.append(ch)
            i += 1
    parts.append("".join(buf))
    return parts, i


def _expression(src: str, i: int) -> int:
    """The index past a `${…}`'s closing brace: strings, comments and templates in it skipped."""
    depth = 1
    while i < len(src) and depth:
        ch = src[i]
        if ch in "'\"":
            j = i + 1
            while j < len(src) and src[j] != ch:
                j += 2 if src[j] == "\\" else 1
            i = j + 1
        elif ch == "`":
            _, i = _template(src, i + 1)
        elif src.startswith("//", i):
            i = src.find("\n", i)
        elif src.startswith("/*", i):
            i = src.find("*/", i) + 2
        else:
            depth += ch == "{"
            depth -= ch == "}"
            i += 1
    return i


def _tokens(parts):
    """The template as a run of tokens: ('text', s), ('value',), ('open'|'close'|'self', name),
    ('space', has_newline). A tag's inside (attributes, values in it) is read only for its
    name; a component, `<${Amt} ...>`, is named "${"."""
    out, in_tag, quote, raw = [], False, None, ""
    for part in parts:
        if isinstance(part, tuple):
            if in_tag:
                pass
            elif re.fullmatch(r"(['\"`]) \1", part[1]):
                out.append(("written",))  # ${' '}: a space written out
            elif re.fullmatch(r"(['\"`])\1", part[1]):
                out.append(("written",))  # ${''}: joined on purpose, where a line can't be
            else:
                out.append(("value", part[1]))
            if in_tag and not raw.strip():
                raw += "${" + part[1]
            continue
        k = 0
        while k < len(part):
            ch = part[k]
            if in_tag:
                if quote:
                    quote = None if ch == quote else quote
                elif ch in "'\"":
                    quote = ch
                elif ch == ">":
                    in_tag = False
                    body = raw.strip()
                    name = body.lstrip("/").split()[0] if body.lstrip("/") else ""
                    kind = (
                        "close"
                        if body.startswith("/")
                        else "self"
                        if body.endswith("/")
                        else "open"
                    )
                    out.append((kind, name.rstrip("/")))
                else:
                    raw += ch
                k += 1
            elif ch == "<":
                in_tag, raw = True, ""
                k += 1
            elif ch.isspace():
                j = k
                while j < len(part) and part[j].isspace():
                    j += 1
                out.append(("space", "\n" in part[k:j]))
                k = j
            else:
                j = k
                while j < len(part) and not part[j].isspace() and part[j] != "<":
                    j += 1
                out.append(("text", part[k:j]))
                k = j
    return out


def _inline(tok, side: str) -> bool:
    kind = tok[0]
    if kind == "written":
        return False
    if kind == "value" and re.search(r"""['"`] """, tok[1]):
        return False  # its text brings its own space (" · …")
    if kind in ("text", "value"):
        return True
    inline = tok[1] in INLINE or tok[1].removeprefix("${") in INLINE_COMPONENTS
    # Words run into an inline element's start after them, or its end before them; a
    # self-closing component either way.
    return inline and (kind == "self" or kind == ("open" if side == "after" else "close"))


def _show(tok) -> str:
    if tok[0] == "text":
        return tok[1]
    if tok[0] == "value":
        return "${…}"
    return f"<{'/' if tok[0] == 'close' else ''}{tok[1]}>"


def _edges(expr: str):
    """The first and last tokens of each template inside a value's source, when a line break
    stands at that edge (htm drops it): (first, last), either None without one."""
    for parts, _ in templates(expr):
        toks = _tokens(parts)
        if len(toks) < 2:
            continue
        first = toks[1] if toks[0] == ("space", True) else None
        last = toks[-2] if toks[-1] == ("space", True) else None
        # An inline element whose text starts with a space carries it.
        if first and first[0] == "open" and len(toks) > 2 and toks[2] == ("space", False):
            first = None
        yield first, last


def _meets(left, left_side: str, right, right_side: str) -> bool:
    """Two tokens that meet across a template's edge, both in a line of text (a value beside a
    value is a list)."""
    if not left or not right or "space" in (left[0], right[0]):
        return False
    if left[0] == "value" and right[0] == "value":
        return False
    return _inline(left, left_side) and _inline(right, right_side)


def lost_spaces(src: str) -> list[str]:
    out = []
    for parts, line in templates(src):
        toks = _tokens(parts)
        for n, tok in enumerate(toks):
            before = toks[n - 1] if n else None
            after = toks[n + 1] if n + 1 < len(toks) else None
            if tok == ("space", True) and before and after:
                # An inline element whose text starts with a space carries it.
                if after[0] == "open" and n + 2 < len(toks) and toks[n + 2] == ("space", False):
                    continue
                if any(x[0] == "value" and "html`" in x[1] for x in (before, after)):
                    continue  # a value holding a template: read by that template's edges, below
                # Words on either side of a line break are one text, which keeps the space; two
                # values side by side are mostly lists of elements.
                if {before[0], after[0]} in ({"text"}, {"value"}):
                    continue
                if _inline(before, "before") and _inline(after, "after"):
                    out.append(f"{line}: {_show(before)} ⏎ {_show(after)}")
            elif tok[0] == "value" and "html`" in tok[1]:
                # A template in a value loses its own edge's line break against the words
                # beside the value.
                # What stands before it: the token beside it, and past any values (they may be
                # empty) the words before them.
                behind, back = [], n - 1
                while back >= 0:
                    if toks[back][0] != "space":
                        behind.append(toks[back])
                        if toks[back][0] != "value":
                            break
                    back -= 1
                for first, last in _edges(tok[1]):
                    hit = next((b for b in behind if _meets(b, "before", first, "after")), None)
                    if hit:
                        out.append(f"{line}: {_show(hit)} ⏎ {_show(first)} (in a value)")
                    if _meets(last, "before", after, "after"):
                        out.append(f"{line}: {_show(last)} ⏎ {_show(after)} (in a value)")
    return out


def test_no_word_loses_its_space_at_a_line_break():
    found = []
    for f in sorted(paths.UI.glob("**/*.js")):
        if any(part in f.parts for part in ("vendor", "mockup", "tests")):
            continue
        found += [f"{f.relative_to(paths.UI)}:{x}" for x in lost_spaces(f.read_text())]
    assert not found, "a space lost where a template breaks a line:\n" + "\n".join(found)


def test_the_check_finds_the_shapes_it_is_for():
    bad = "html`<p>a leg of\n  <b>${name}</b> on ${u}</p><td>${d}\n  <span>paid</span></td>`"
    assert len(lost_spaces(bad)) == 2
    good = "html`<div>\n  <p>one</p>\n  <p>two</p>\n</div><p>a leg of${' '}<b>x</b></p>`"
    assert lost_spaces(good) == []
    assert len(lost_spaces("html`<p>Total\n  <${Amt} v=${x} /></p>`")) == 1
    assert lost_spaces("html`<div>by\n  the way</div>\n<${Field} x=${1} />`") == []
    assert lost_spaces("html`<p>a leg of${' '}\n  <b>x</b></p>`") == []
    days = "html`<p>days old\n  ${a}\n  ${b ? html`\n  time to go` : null}</p>`"
    assert len(lost_spaces(days)) == 2  # old ⏎ ${a}, and old ⏎ time when a is empty
    nested = "html`<td>${d}${p ? html`\n  <span>paid</span>\n` : null}</td>`"
    assert len(lost_spaces(nested)) == 1  # its start meets ${d}; its end meets </td>
