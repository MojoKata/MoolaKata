"""Every stylesheet the app serves writes in a cascade layer (requirements S17.3.10, S12.18.15):
a rule outside any layer would outrank every layer, the note's realm (`note`, the last) among
them, and reach inside a note. A vendored stylesheet comes in only through an `@import` into a
layer. The layers' order is named once, in tokens.css, before any is used."""

import re

from moolakata import paths

UI = paths.WEB / "ui"
SHEETS = [*sorted((UI / "styles").glob("*.css")), *sorted((UI / "kit" / "theme").glob("*.css"))]


def top_level(css: str) -> list[str]:
    """The heads of a stylesheet's top-level statements and blocks, comments left out."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    heads, depth, buf = [], 0, ""
    for ch in css:
        if ch == "{":
            if depth == 0:
                heads.append(buf.strip())
            depth += 1
            buf = ""
        elif ch == "}":
            depth -= 1
            buf = ""
        elif ch == ";" and depth == 0:
            heads.append(buf.strip() + ";")
            buf = ""
        else:
            buf += ch
    return [h for h in heads if h]


def test_every_rule_sits_in_a_layer():
    for sheet in SHEETS:
        loose = [
            h
            for h in top_level(sheet.read_text())
            if not (h.startswith("@layer") or re.match(r"@import url\('[^']+'\) layer\(", h))
        ]
        assert not loose, f"{sheet.name}: outside any layer: {loose[:3]}"


def test_the_layers_are_named_once_in_order_and_the_note_last():
    order = re.search(r"@layer ([\w, .-]+);", (UI / "kit" / "theme" / "tokens.css").read_text())
    assert order and [n.strip() for n in order.group(1).split(",")] == [
        "tokens",
        "base",
        "kit",
        "components",
        "note",
    ]
    # The note's own sublayers named before its import gives the engine its place.
    note = top_level((UI / "kit" / "theme" / "note.css").read_text())
    assert note[0] == "@layer note.reset, note.look, note.engine;"
    assert note[1].startswith("@import url(") and note[1].endswith("layer(note.engine);")


def test_the_page_links_tokens_first():
    page = (UI / "index.html").read_text()
    sheets = re.findall(
        r'<link rel="stylesheet" href="[^"]*/([\w-]+/[\w-]+\.css|[\w-]+\.css)"', page
    )
    assert sheets[0].endswith("tokens.css"), sheets


def test_nothing_is_important_but_reduced_motion():
    """An `!important` in any layer outranks the note's own look; only the reduced-motion rules,
    which a note should follow too, take it."""
    for sheet in SHEETS:
        css = re.sub(r"/\*.*?\*/", "", sheet.read_text(), flags=re.S)
        for decl in re.findall(r"([\w-]+)\s*:[^;{}]*!important", css):
            assert decl in ("transition", "animation"), f"{sheet.name}: {decl} !important"
