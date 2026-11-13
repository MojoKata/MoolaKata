"""The ui-kit's classes are its own (requirements S17.3.10): a class its markup draws is never
also styled on its own by the app's stylesheet, which would change the kit's look inside the app
alone (the kit's pages don't load it). The app may style a kit class where it sits in the app's
own markup (`.card .btn`), or as a variant of its own (`.menu a.hh-item`)."""

import re

from moolakata import paths

UI = paths.WEB / "ui"


def kit_classes() -> set[str]:
    """Every class name written in the kit's markup."""
    out: set[str] = set()
    for f in (UI / "kit").glob("*.js"):
        src = f.read_text()
        for m in re.finditer(r"""class=(?:"([^"$]+)"|\$\{['`]([^'`$]+)['`])""", src):
            out.update((m.group(1) or m.group(2)).split())
        for m in re.finditer(r"""['`]([a-z][\w-]*(?: [a-z][\w-]*)*)['`] \+""", src):
            out.update(m.group(1).split())
    return out


def app_bare_rules() -> set[str]:
    """The classes the app's stylesheet styles on their own, alone or with a state: `.dot {`,
    `.btn:hover {`; a variant with a class of the app's (`.dot.stale`) is the app's own."""
    css = re.sub(r"/\*.*?\*/", "", (UI / "styles" / "components.css").read_text(), flags=re.S)
    out: set[str] = set()
    for sel in re.findall(r"([^{}]+)\{", css):
        for part in sel.split(","):
            part = part.strip()
            m = re.fullmatch(r"\.([\w-]+)((?::[\w-]+(?:\([^)]*\))?)*)", part)
            if m:
                out.add(m.group(1))
    return out


def test_the_app_never_restyles_a_kit_class_on_its_own():
    clash = sorted(kit_classes() & app_bare_rules())
    assert clash == []
