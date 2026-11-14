"""A list's rows and a page's pills, read from the browser app's source (requirements
S12.19.3): a row's name is drawn in the kit's one row style (`row-name`, its details
`row-more`), never bold, so no row reads as a heading against its card's; a pill's name is one
word where its row or card makes the meaning clear, two at most beside any value it counts, and
the rest is its tooltip."""

import re

import uitext

# A row's name in bold: the first thing in a row's `grow`, or in a link that is.
BOLD_NAME = re.compile(r'class="grow[^"]*">\s*(?:<a [^>]*>\s*)?<(?:b|strong)>')
# A plain pill of fixed words only, its text running straight to its end.
PLAIN_PILL = re.compile(r"""<span class=(?:"pill[^"]*"|\$\{'pill[^}]*\})>([^<$`{}]+)</span>""")
MOST = 2  # words


def _line(src: str, at: int) -> int:
    return src.count("\n", 0, at) + 1


def pill_names(src: str):
    """Each StatePill's fixed words, its values left out: (line, words)."""
    i = 0
    while (i := src.find("html`", i)) >= 0:
        i += len("html`")
        words: list[str] | None = None
        at = 0
        for tok in uitext._tokens(src, i):
            if tok[0] == "tag" and tok[2] == "${StatePill}":
                if tok[1] == "open":
                    words, at = [], tok[3]
                elif tok[1] == "close" and words is not None:
                    yield _line(src, at), " ".join(words)
                    words = None
            elif words is not None and tok[0] == "text":
                words.extend(re.findall(r"[A-Za-z][\w'’-]*", src[tok[1] : tok[2]]))


def test_a_long_pill_name_and_a_bold_row_name_are_found():
    src = """html`<div class="list-item"><div class="grow"><b>${r.name}</b></div>
      <${StatePill} why="It means this.">already in the account</${StatePill}>
      <${StatePill} why=${w}>${n} stale</${StatePill}>
      <span class="pill warn">time to rotate</span><span class="pill ok">${x} new</span>`"""
    assert [_line(src, m.start()) for m in BOLD_NAME.finditer(src)] == [1]
    assert list(pill_names(src)) == [(2, "already in the account"), (3, "stale")]
    assert PLAIN_PILL.findall(src) == ["time to rotate"]


def test_no_row_name_is_bold():
    bold = [
        f"{name}:{_line(src, m.start())}"
        for name, src in uitext.sources()
        for m in BOLD_NAME.finditer(src)
    ]
    assert not bold, 'a row\'s name is <span class="row-name">, not bold'


def test_a_pills_name_is_two_words_at_most():
    long = [
        f"{name}:{line}: {words}"
        for name, src in uitext.sources()
        for line, words in pill_names(src)
        if len(words.split()) > MOST
    ]
    long += [
        f"{name}:{_line(src, m.start())}: {m.group(1).strip()}"
        for name, src in uitext.sources()
        for m in PLAIN_PILL.finditer(src)
        if len(m.group(1).split()) > MOST
    ]
    assert not long, "the rest of a pill's name goes into its tooltip"
