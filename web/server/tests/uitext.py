"""The browser app's words, read from its source: what Title Case is, and where the app writes
the words that take it (requirements R3.13).

Title Case (Chicago): every word capitalised but articles, coordinating conjunctions,
prepositions and "as", which are lowercase unless first or last, or first after a colon, a dot
(·) or a chevron (›); a preposition that belongs to a verb (Sign In, Pair Up) is a particle,
capitalised; each part of a hyphenated word follows the same rule; acronyms and numbers stay as
written.

The words read are the literal text a template writes in a button, a heading (h1 to h4), a
column header, a tab, a dialog's title and a dialog's Save; a value in it (`${name}`) is
data, read as no word, and splits the text around it.
"""

import re

from moolakata import paths

ARTICLES = {"a", "an", "the"}
CONJUNCTIONS = {"and", "but", "or", "nor", "for", "so", "yet"}
PREPOSITIONS = {
    "about", "above", "across", "after", "against", "along", "amid", "among", "around", "as",
    "at", "before", "behind", "below", "beneath", "beside", "between", "beyond", "by",
    "despite", "down", "during", "except", "for", "from", "in", "inside", "into", "like",
    "near", "of", "off", "on", "onto", "out", "outside", "over", "past", "per", "since",
    "than", "through", "till", "to", "toward", "towards", "under", "until", "up", "upon",
    "versus", "via", "vs", "with", "within", "without",
}  # fmt: skip
MINOR = ARTICLES | CONJUNCTIONS | PREPOSITIONS
# A verb and its particle: the particle is capitalised (Chicago 8.159).
PHRASAL = {
    ("sign", "in"), ("sign", "out"), ("sign", "up"), ("log", "in"), ("log", "out"),
    ("set", "up"), ("pair", "up"), ("look", "up"), ("tick", "off"), ("turn", "on"),
    ("turn", "off"), ("pay", "off"), ("pay", "back"), ("write", "off"), ("start", "over"),
    ("check", "in"), ("opt", "out"), ("roll", "over"), ("carry", "over"), ("leave", "out"),
    ("take", "out"), ("put", "back"), ("move", "in"), ("move", "out"), ("try", "out"),
    ("fill", "in"), ("break", "down"), ("open", "up"), ("sort", "out"), ("left", "out"),
    ("paid", "off"), ("ticked", "off"), ("come", "in"), ("go", "out"), ("mark", "off"),
    ("clean", "up"), ("back", "up"), ("give", "back"), ("work", "out"), ("worked", "out"),
}  # fmt: skip
# Words written as they are, whatever their place (units, a product's own spelling).
AS_WRITTEN = {"sats", "sat", "e.g", "i.e", "vs", "oz"}
STARTS = {":", "·", "›", "—", "–", "/"}
# A hyphenated prefix keeps the word after it lowercase (Re-baseline, Re-read; Chicago 8.161).
PREFIXES = {"re", "pre", "non", "anti", "co", "sub", "un", "multi", "semi", "post"}


def _cap(w: str) -> str:
    return w[:1].upper() + w[1:]


def _want(word: str, first: bool, last: bool, prev: str | None) -> str:
    """The word as Title Case writes it."""
    if not word[:1].isalpha() or word.lower() in AS_WRITTEN:
        return word
    if any(c.isupper() for c in word[1:]):
        return word  # an acronym or a name written its own way (MoolaKata, IRA, 1099-DIV)
    if "-" in word:
        parts = word.split("-")
        out = [_want(parts[0], first, last and len(parts) == 1, prev)]
        for i, p in enumerate(parts[1:], 1):
            if not p or (parts[0].lower() in PREFIXES and i == 1):
                out.append(p)
            else:
                out.append(_want(p, False, i == len(parts) - 1, parts[i - 1].lower()))
        return "-".join(out)
    low = word.lower()
    if low in MINOR and not first and not last and (prev, low) not in PHRASAL:
        return low
    return _cap(word)


def title_case(fragments: list[str | None]) -> list[str | None]:
    """The text's literal fragments in Title Case; None stands for a value, which splits them
    (a fragment that starts after a value doesn't start the text)."""
    out: list[str | None] = []
    for i, frag in enumerate(fragments):
        if frag is None:
            out.append(None)
            continue
        # A word's own apostrophe ('s after a value) is no word.
        toks = list(re.finditer(r"(?<!['’])[A-Za-z0-9][\w'’.\-]*|[:·›—–/]", frag))
        words = [t for t in toks if t.group() not in STARTS]
        # A value before or after this fragment is a word: the fragment's edge isn't the text's.
        at_start = all(f is not None and not f.strip() for f in fragments[:i])
        at_end = all(f is not None and not f.strip() for f in fragments[i + 1 :])
        res, pos, prev, fresh = [], 0, None, at_start
        for t in toks:
            res.append(frag[pos : t.start()])
            pos = t.end()
            g = t.group()
            if g in STARTS:
                res.append(g)
                fresh, prev = True, None
                continue
            core = g.rstrip(".")
            is_last = at_end and t is (words[-1] if words else None)
            # A word that ends a phrase before a colon or a dot is last in that phrase.
            rest = frag[t.end() :].lstrip()
            ends_phrase = rest[:1] in {":", "·", "›", "—", "–"}
            fixed = _want(core, fresh, is_last or ends_phrase, prev)
            res.append(fixed + g[len(core) :])
            prev, fresh = core.lower(), False
        res.append(frag[pos:])
        out.append("".join(res))
    return out


def wrong_words(fragments: list[str | None]) -> list[str]:
    """The words not in Title Case."""
    want = title_case(fragments)
    bad = []
    for got, w in zip(fragments, want, strict=True):
        if got is None or got == w:
            continue
        for a, b in zip(re.findall(r"\S+", got), re.findall(r"\S+", w), strict=False):
            if a != b:
                bad.append(f"{a}→{b}")
    return bad


# --- reading the source -------------------------------------------------------------------


class Lit(str):
    """Literal text read from the source, whitespace runs as one space; `at` is where its raw
    text starts in the file and `raw` that text, so a fix lands exactly where it was read."""

    at: int
    raw: str

    def __new__(cls, raw: str, at: int):
        self = super().__new__(cls, re.sub(r"\s+", " ", raw))
        self.at, self.raw = at, raw
        return self


ELEMENTS = {"button", "th", "h1", "h2", "h3", "h4"}
COMPONENTS = {"Action", "SaveButton"}  # drawn as a button; their text is their children
TITLED = re.compile(r"^\$\{(\w*Dialog|DraftForm|AuthCard|Confirm\w*)\}$")
INLINE = {"b", "i", "em", "strong", "code", "abbr", "kbd", "sup", "sub", "u"}
# Buttons that read as links: the small lowercase ones under a field (R3.10) and links inside a
# sentence, which take its case.
LINKLIKE = re.compile(r'class="[^"]*\b(?:link-btn|linklike)\b')
# A stat's label: the header of its card.
CARD_LABEL = re.compile(r'class="label"')
DECORATION = re.compile(r"\bIcon\b|\bSpinner\b|html`|^' '$|^''$")
STRING = r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"|`[^`]*`"


def _expression(src: str, i: int) -> int:
    """The index past a `${…}` whose inside starts at i: strings, comments and templates in it
    skipped."""
    depth = 1
    while i < len(src) and depth:
        ch = src[i]
        if ch in "'\"":
            j = i + 1
            while j < len(src) and src[j] != ch:
                j += 2 if src[j] == "\\" else 1
            i = j + 1
        elif ch == "`":
            i = _template_end(src, i + 1)
        elif src.startswith("//", i):
            i = src.find("\n", i)
        elif src.startswith("/*", i):
            i = src.find("*/", i) + 2
        else:
            depth += ch == "{"
            depth -= ch == "}"
            i += 1
    return i


def _template_end(src: str, i: int) -> int:
    """The index past the backtick that closes a template whose inside starts at i."""
    while i < len(src):
        if src[i] == "\\":
            i += 2
        elif src[i] == "`":
            return i + 1
        elif src.startswith("${", i):
            i = _expression(src, i + 2)
        else:
            i += 1
    return i


def _tokens(src: str, i: int):
    """An html`` template's tokens from i: ('text', start, end), ('value', start, end) for a
    `${…}`'s inside, ('tag', kind, name, start, end) for a tag (its source span)."""
    out, text_at = [], i
    while i < len(src):
        ch = src[i]
        if ch == "`" or src.startswith("${", i) or ch == "<":
            if i > text_at:
                out.append(("text", text_at, i))
            if ch == "`":
                return out
            if ch == "<":
                j, quote = i + 1, None
                while j < len(src):
                    c = src[j]
                    if quote:
                        quote = None if c == quote else quote
                        j += 1
                    elif src.startswith("${", j):
                        j = _expression(src, j + 2)
                    elif c in "'\"":
                        quote = c
                        j += 1
                    elif c == ">":
                        break
                    else:
                        j += 1
                body = src[i + 1 : j].strip()
                kind = "close" if body.startswith("/") else "self" if body.endswith("/") else "open"
                name = body.lstrip("/").rstrip("/").strip().split(None, 1)
                out.append(("tag", kind, name[0] if name else "", i, j + 1))
                i = text_at = j + 1
            else:
                end = _expression(src, i + 2)
                out.append(("value", i + 2, end - 1))
                i = text_at = end
        elif ch == "\\":
            i += 2
        else:
            i += 1
    return out


def _string(src: str, a: int, b: int) -> list | None:
    """The source a..b if it is only a string, as fragments (None for each value in a template
    string); None when it is anything else."""
    e = src[a:b]
    lead = len(e) - len(e.lstrip())
    e = e.strip()
    a += lead
    if re.fullmatch(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", e):
        return [Lit(e[1:-1], a + 1)]
    m = re.fullmatch(r"`([^`]*)`", e, re.S)
    if m:
        out: list = []
        pos = a + 1
        for piece in re.split(r"(\$\{[^}]*\})", m.group(1)):
            out.append(None if piece.startswith("${") else Lit(piece, pos))
            pos += len(piece)
        return [f for f in out if f is None or f.raw]
    return None


RESULT = re.compile(r"(?:^|[?:]|\|\||\?\?)\s*('(?:[^'\\]|\\.)*'|`[^`$]*`)(?=\s*(?:$|:))")


def _choices(src: str, a: int, b: int) -> list | None:
    """The words a value chooses between when it is a choice of strings (`x ? 'A' : 'B'`,
    `x || 'A'`): each string it can give, or None when it gives anything else too."""
    e = src[a:b]
    if "?" not in e and "||" not in e and "??" not in e:
        return None
    hits = list(RESULT.finditer(e))
    # A choice of endings ('' or 's') is part of the word before it, no word of its own.
    if not hits or all(len(m.group(1)) <= 4 for m in hits):
        return None
    return [Lit(m.group(1)[1:-1], a + m.start(1) + 1) for m in hits]


class Alt(list):
    """A value in a text that chooses between strings: each is read in its place."""


def _attr(src: str, a: int, b: int, name: str) -> list | None:
    """A tag's attribute (the tag spans a..b) as literal fragments: `name="…"` or
    `name=${'…'}`."""
    tag = src[a:b]
    m = re.search(rf'\s{name}="([^"]*)"', tag)
    if m:
        return [Lit(m.group(1), a + m.start(1))]
    m = re.search(rf"\s{name}=\$\{{", tag)
    if not m:
        return None
    start, end = a + m.end(), _expression(src, a + m.end()) - 1
    lit = _string(src, start, end)
    if lit is None and (alt := _choices(src, start, end)):
        return [Alt(alt)]
    return lit


def expand(frags: list):
    """Each text the fragments can make: a choice of strings read one string at a time, the
    others as values."""
    alts = [i for i, f in enumerate(frags) if isinstance(f, Alt)]
    if not alts:
        yield frags
        return
    for i in alts:
        for lit in frags[i]:
            yield [
                lit if j == i else None if isinstance(f, Alt) else f for j, f in enumerate(frags)
            ]


def headed_texts(src: str):
    """Each text a template writes that takes Title Case: (line, what, fragments)."""
    i = 0
    while (i := src.find("html`", i)) >= 0:
        i += len("html`")
        # Open elements: (name, words or None when not read, what to call it).
        stack: list[tuple] = []
        for tok in _tokens(src, i):
            if tok[0] == "tag":
                kind, name, a, b = tok[1:]
                comp = name.removeprefix("${").removesuffix("}")
                attrs = src[a:b]
                if kind == "open":
                    if name in INLINE and stack:
                        stack.append((name, stack[-1][1], name))  # its words are its parent's
                    elif (name in ELEMENTS or comp in COMPONENTS) and not LINKLIKE.search(attrs):
                        stack.append((name, [], comp))
                    elif CARD_LABEL.search(attrs):
                        stack.append((name, [], "card label"))
                    else:
                        stack.append((name, None, name))
                elif kind == "close":
                    # Up to the element it closes (a component closes with </${X}> or <//>).
                    while stack:
                        tag, frags, what = stack.pop()
                        if tag == name or name in ("", "/"):
                            break
                    else:
                        continue
                    if frags is not None and tag not in INLINE:
                        for each in expand(frags):
                            if cleaned := _clean(each):
                                yield src.count("\n", 0, a) + 1, what, cleaned
                if kind in ("open", "self"):
                    line = src.count("\n", 0, a) + 1
                    if TITLED.match(name):
                        for t in expand(_attr(src, a, b, "title") or []):
                            yield line, "dialog title", t
                    if comp in {"DraftDialog", "DraftForm", "SaveButton"}:
                        for lab in expand(_attr(src, a, b, "label") or []):
                            yield line, "save button", lab
                drawn = stack and stack[-1][1] is not None and not DECORATION.search(name)
                if kind == "self" and name.startswith("${") and drawn:
                    stack[-1][1].append(None)  # a component that draws a value (an amount)
                continue
            if stack and stack[-1][1] is not None:
                _, a, b = tok
                if tok[0] == "text":
                    stack[-1][1].append(Lit(src[a:b], a))
                elif not DECORATION.search(src[a:b].strip()):
                    lit = _string(src, a, b)
                    if lit is None and (alt := _choices(src, a, b)):
                        lit = [Alt(alt)]
                    stack[-1][1].extend(lit if lit is not None else [None])


def _clean(frags: list) -> list:
    """The fragments without blank ones at either end; none when no words are left."""
    out = list(frags)
    while out and out[0] is not None and not out[0].strip():
        out.pop(0)
    while out and out[-1] is not None and not out[-1].strip():
        out.pop()
    if all(f is None or not f.strip() for f in out):
        return []
    return out


LISTS = re.compile(
    r"(?:const|let)\s+(TABS|tabs|PANEL_TABS|SECTIONS)\b[^=]*=(.*?);\n"
    r"|\b(TABS)\.(?:splice|unshift|push)\((.*?)\);",
    re.S,
)
PAIR = re.compile(r"\[\s*'[\w-]+'\s*,\s*'((?:[^'\\]|\\.)*)'")
LABEL = re.compile(r"\blabel:\s*'((?:[^'\\]|\\.)*)'")
TITLE = re.compile(r"\buseTitle\((.*?)\);", re.S)
CONFIRM = re.compile(r"confirmAction\(\{\s*title:\s*(" + STRING + ")")


def listed_texts(src: str):
    """Tabs, Settings sections, the navigation, menu items, page titles and their crumbs and
    the titles of questions, which the source writes as lists or arguments."""

    def at(i: int) -> int:
        return src.count("\n", 0, i) + 1

    for m in LISTS.finditer(src):
        g = 2 if m.group(2) is not None else 4
        what = "settings section" if m.group(1) == "SECTIONS" else "tab"
        for p in PAIR.finditer(src, m.start(g), m.end(g)):
            yield at(p.start()), what, [Lit(p.group(1), p.start(1))]
    for m in re.finditer(r"\b(?:NAV|ADMIN_NAV)\s*=\s*\[(.*?)\];", src, re.S):
        for p in LABEL.finditer(src, m.start(1), m.end(1)):
            yield at(p.start()), "nav", [Lit(p.group(1), p.start(1))]
    for m in re.finditer(r"\bopenMenu\(", src):
        for p in LABEL.finditer(src, m.end(), src.find(");", m.end())):
            yield at(p.start()), "menu item", [Lit(p.group(1), p.start(1))]
    for m in CONFIRM.finditer(src):
        frags = _string(src, m.start(1), m.end(1))
        if frags:
            yield at(m.start()), "dialog title", frags
    for m in TITLE.finditer(src):
        for p in re.finditer(r"'((?:[^'\\]|\\.)*)'", src[m.start(1) : m.end(1)]):
            if not p.group(1).startswith("/"):
                yield at(m.start()), "page title", [Lit(p.group(1), m.start(1) + p.start(1))]


def texts(src: str):
    yield from headed_texts(src)
    yield from listed_texts(src)


def sources():
    for sub in ("kit", "components", "screens", "app"):
        for f in sorted((paths.UI / sub).glob("*.js")):
            yield f.relative_to(paths.UI).as_posix(), f.read_text()


# --- fixed words on the screen (R3.12) ----------------------------------------------------

PARAGRAPHS = {"p", "div", "span", "small", "li"}
# Where fixed words belong: the page's state and warnings (S12.19), a label, a button, a
# header, a table's cell, a list's choice.
STATE = {"Empty", "Attention", "StatePill", "Action", "SaveButton", "Tip"}
HOLDERS = {"label", "button", "th", "td", "option", "h1", "h2", "h3", "h4", "a", "legend"}
FEWEST = 4  # words: fewer is a label or a state's word, not an explanation
# A label of a value: a stat's (label), a row's name (grow), a key of a key and value list (k).
LABELLED = re.compile(r'class="(?:[^"]*\s)?(?:label|grow|k)(?:\s[^"]*)?"')


def fixed_paragraphs(src: str):
    """Each paragraph a template writes that is only fixed words (FEWEST or more), outside the
    page's state and the elements that hold words of their own: (line, words)."""
    i = 0
    while (i := src.find("html`", i)) >= 0:
        i += len("html`")
        stack: list[list] = []  # [name, parts, start, a label]
        for tok in _tokens(src, i):
            if tok[0] == "tag":
                kind, name, a, b = tok[1:]
                if kind == "open":
                    stack.append([name, [], a, bool(LABELLED.search(src[a:b]))])
                elif kind == "self" and name.startswith("${") and stack:
                    if not DECORATION.search(name):
                        stack[-1][1].append(None)
                elif kind == "close":
                    while stack:
                        e = stack.pop()
                        if e[0] == name or name in ("", "/"):
                            break
                    else:
                        continue
                    held = e[3] or any(s[0] in HOLDERS or s[0].strip("${}") in STATE for s in stack)
                    if e[0] in PARAGRAPHS and not held and None not in e[1]:
                        words = re.sub(r"\s+", " ", "".join(e[1])).strip()
                        if len(words.split()) >= FEWEST:
                            yield src.count("\n", 0, e[2]) + 1, words
                    if stack:
                        stack[-1][1].extend(e[1] if e[0] in INLINE else [None])
                continue
            if stack:
                _, a, b = tok
                if tok[0] == "text":
                    stack[-1][1].append(src[a:b])
                elif not DECORATION.search(src[a:b].strip()):
                    lit = _string(src, a, b)
                    whole = lit and None not in lit
                    stack[-1][1].extend([str(x) for x in lit] if whole else [None])


def fixed_hints(src: str):
    """Each field's hint written as fixed words: `hint="…"` or `hint=${'…'}` (R3.12)."""
    i = 0
    while (i := src.find("html`", i)) >= 0:
        i += len("html`")
        for tok in _tokens(src, i):
            if tok[0] != "tag" or tok[1] == "close":
                continue
            a, b = tok[3], tok[4]
            lit = _attr(src, a, b, "hint")
            if lit and all(isinstance(f, Lit) for f in lit) and "".join(lit).strip():
                yield src.count("\n", 0, a) + 1, "".join(lit)
