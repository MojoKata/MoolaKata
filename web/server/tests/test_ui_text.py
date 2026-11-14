"""The app's words (requirements R3.12, R3.13, S12.7.4): buttons, headers, titles, tabs, the
navigation and menus in Title Case; no fixed words left on the screen to explain, which the
guide holds; and a guide's heading reading as what it names. Read from the browser app's
source by `uitext`; the browser suite checks the same headings against what a screen draws
(devapp's guide check)."""

import re

import pytest
import uitext

from moolakata import paths


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("New account", "New Account"),  # every word capitalised
        ("Record a payment", "Record a Payment"),  # an article lowercase
        ("Keys and addresses", "Keys and Addresses"),  # a conjunction
        ("Returns by period", "Returns by Period"),  # a preposition
        ("Accept as an adjustment…", "Accept as an Adjustment…"),  # as; an ellipsis kept
        ("Attached to", "Attached To"),  # last word capitalised, a preposition too
        ("The plan", "The Plan"),  # first word capitalised, an article too
        ("Sign in", "Sign In"),  # a particle
        ("Tick off against a statement", "Tick Off against a Statement"),  # mid-text particle
        ("Balance: the schedule against your plan", "Balance: The Schedule against Your Plan"),
        ("Projected value · today", "Projected Value · Today"),  # after a dot
        ("Two-step sign-in", "Two-Step Sign-In"),  # each part of a hyphenated word
        ("Re-encrypt now", "Re-encrypt Now"),  # but after a prefix
        ("Year-to-date return", "Year-to-Date Return"),  # minor parts stay lowercase
        ("Expected return %", "Expected Return %"),  # a sign is no word
        ("Email (SMTP)", "Email (SMTP)"),  # acronyms as written
        ("MoolaKata was updated", "MoolaKata Was Updated"),  # a name as written
        ("Capital gains (8949)", "Capital Gains (8949)"),  # a number as written
        ("Fine oz", "Fine oz"),  # a unit as written
        ("Save your changes?", "Save Your Changes?"),  # a question's mark kept
        ("Type today's balance", "Type Today's Balance"),  # an apostrophe inside a word
        ("Backup Now", "Backup Now"),  # already right: unchanged
    ],
)
def test_title_case(text, want):
    assert uitext.title_case([text]) == [want]


@pytest.mark.parametrize(
    ("frags", "want"),
    [
        # A value is a word: what stands next to it isn't the text's first or last.
        (["Shared from here with ", None], ["Shared from Here with ", None]),
        ([None, "'s key"], [None, "'s Key"]),
        (["Prune ", None, " files"], ["Prune ", None, " Files"]),
        ([None, ": what happened?"], [None, ": What Happened?"]),
        (["Make “", None, "” active?"], ["Make “", None, "” Active?"]),
    ],
)
def test_title_case_around_values(frags, want):
    assert uitext.title_case(frags) == want


def test_wrong_words_names_each_word_and_its_fix():
    assert uitext.wrong_words(["Record a payment"]) == ["payment→Payment"]
    assert uitext.wrong_words(["Record a Payment"]) == []


def test_the_texts_read_cover_each_place_title_case_goes():
    src = """
        const TABS = [['a', 'Cash flow'], ['b', 'Holdings']];
        const SECTIONS = [['general', 'Key storage']];
        export const NAV = [{ href: '/', label: 'Linked servers' }];
        openMenu(e, [{ label: 'Sign out', onSelect }]);
        useTitle('Not found', [['Users and Groups', '/ui/users']]);
        confirmAction({ title: 'Delete this gift?' });
        html`<h3>Saved plans <span class="dim">a note</span></h3>
          <button class="btn"><${Icon} name="plus" /> New budget</button>
          <button class="link-btn">min</button>
          <th>Cost basis</th><div class="label">Net worth</div>
          <${Action} why=${w}>Make active</${Action}>
          <${DraftDialog} title="New rule" label="Add the rule" />
          <${Dialog} title=${`Prune ${n} files`} />`;
    """
    got = {
        (what, "".join(f or "${…}" for f in frags).strip()) for _, what, frags in uitext.texts(src)
    }
    assert got == {
        ("tab", "Cash flow"),
        ("tab", "Holdings"),
        ("settings section", "Key storage"),
        ("nav", "Linked servers"),
        ("menu item", "Sign out"),
        ("page title", "Not found"),
        ("page title", "Users and Groups"),
        ("dialog title", "Delete this gift?"),
        ("h3", "Saved plans"),  # its sub-caption is no part of it
        ("button", "New budget"),  # the icon draws no word
        ("th", "Cost basis"),
        ("card label", "Net worth"),
        ("Action", "Make active"),
        ("dialog title", "New rule"),
        ("save button", "Add the rule"),
        ("dialog title", "Prune ${…} files"),
    }, got


def test_buttons_headers_titles_and_tabs_are_in_title_case():
    wrong = []
    for name, src in uitext.sources():
        for line, what, frags in uitext.texts(src):
            if bad := uitext.wrong_words(frags):
                wrong.append(f"{name}:{line} [{what}] {', '.join(bad)}")
    assert not wrong, "not in Title Case (R3.13):\n" + "\n".join(wrong)


def test_a_fixed_hint_is_found():
    src = """html`<${Field} label="A" hint="Fixed words." />
      <${Field} label="B" hint=${'Fixed too.'} />
      <${Field} label="C" hint=${`Kept until ${date}.`} />
      <${Field} label="D" hint=${big ? 'Needed at $250.' : null} />`"""
    assert [w for _, w in uitext.fixed_hints(src)] == ["Fixed words.", "Fixed too."]


def test_no_field_hint_is_fixed_words():
    """A hint is a live value or a warning while it applies, never fixed words (R3.12): those
    go to the field's heading in the guide; a blank's meaning is the placeholder."""
    found = [
        f"{name}:{line} {words!r}"
        for name, src in uitext.sources()
        for line, words in uitext.fixed_hints(src)
    ]
    assert not found, "fixed hints (to the guide, or the placeholder):\n" + "\n".join(found)


def test_a_fixed_paragraph_is_found():
    src = """html`<p class="small dim">What this dialog is for, in a sentence.</p>
      <p class="small dim">Kept until ${date} by the retention.</p>
      <${Empty}>No saved plans yet, so far</${Empty}>
      <${Attention}>No backup is made first here.</${Attention}>
      <label>I have saved the twelve words</label>
      <div class="label">Net capital gain or loss</div>
      <span class="dim">Short</span>
      <div class="delta"><${Amt} v=${a} /> today · <${Amt} v=${b} /> this month</div>`"""
    assert [w for _, w in uitext.fixed_paragraphs(src)] == [
        "What this dialog is for, in a sentence."
    ]


# What S12.19.7 leaves as it is: the answer to an action just taken, beside what took it, and a
# tour's steps. Each by its file and its words' start, so a new one is a choice made here.
ANSWERS = {
    ("kit/dialog.js", "What you changed in this dialog"),  # Save Your Changes?, on leaving
    ("components/draft-form.js", "This needs your password again"),  # a save refused for it
    ("components/reauth.js", "This needs your password"),  # an action refused for it
    ("components/share.js", "Shared at Read when you save"),  # Share These Accounts Too, pressed
    ("screens/signin.js", "If that is a disabled account here"),  # a request to be made active
    ("components/tour.js", "The category is gone"),  # a tour's step (S12.17)
}


def test_no_paragraph_is_fixed_words():
    """What a dialog, a card or a section is for is in its guide, not on the screen (R3.12);
    the page's state draws with its own components (S12.19)."""
    found = [
        f"{name}:{line} {words[:90]!r}"
        for name, src in uitext.sources()
        for line, words in uitext.fixed_paragraphs(src)
        if not any(n == name and words.startswith(w) for n, w in ANSWERS)
    ]
    assert not found, "fixed paragraphs (to the guide, or a state):\n" + "\n".join(found)


def field_labels() -> set[str]:
    out = set()
    for _, src in uitext.sources():
        out |= {m.group(1).lower() for m in re.finditer(r'\blabel="([^"$]+)"', src)}
        # A label chosen by the record (label=${t === 'real-estate' ? 'Purchase price' : …}).
        for m in re.finditer(r"\blabel=\$\{([^}]*)\}", src):
            out |= {w.lower() for w in re.findall(r"'([^']+)'", m.group(1))}
    return out


def test_a_guide_heading_reads_as_the_button_tab_or_header_it_names():
    """A heading naming a button, a tab or a header is written as the screen writes it
    (S12.7.4). Words that are also a field's label are left to the browser suite, which sees
    which one the screen draws."""
    titled: dict[str, str] = {}
    for _, src in uitext.sources():
        for _, _, frags in uitext.texts(src):
            if len(frags) == 1 and frags[0] is not None:
                t = frags[0].strip().rstrip("…").strip()
                titled.setdefault(t.lower(), t)
    labels = field_labels()
    wrong = []
    for g in sorted((paths.UI / "guides").glob("*.md")):
        for n, line in enumerate(g.read_text().splitlines(), 1):
            m = re.match(r"##+ (.*?)(?:\s*\{#[\w-]+\})?$", line)
            if not m:
                continue
            h = m.group(1)
            want = titled.get(h.lower())
            if want and want != h and h.lower() not in labels:
                wrong.append(f"{g.name}:{n} {h!r} → {want!r}")
    assert not wrong, "guide headings in another case than their element:\n" + "\n".join(wrong)


def test_each_answer_kept_is_still_there():
    """Each answer named above is still drawn, so the list can't go stale."""
    for name, words in ANSWERS:
        src = (paths.UI / name).read_text()
        assert any(w.startswith(words) for _, w in uitext.fixed_paragraphs(src)), (name, words)
