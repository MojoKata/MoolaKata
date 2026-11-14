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


def test_a_paragraph_around_a_value_is_found():
    src = """html`<p class="small">Use it with the endpoint <code>${url}</code>, as a bearer.</p>
      <p class="small dim">MCP: <code>${url}</code></p>
      <span class="small dim">${n} payments</span>
      <div class="list-item"><span class="grow dim">Encrypted under it</span>${a} and more</div>
      <${Attention}>Nothing is backed up first for ${name}, so it is lost.</${Attention}>
      <div class="label">The value of the house today, at ${when}</div>`"""
    assert [w for _, w in uitext.mixed_paragraphs(src)] == [
        "Use it with the endpoint … , as a bearer."
    ]


# Fixed words around a value that stay (S12.19.7, R3.12): the answer to an action just taken, a
# question, a security prompt carrying a value to compare, a warning of a consequence beside its
# action, a result the screen works out, a state line, a tour's step. Each by its file and words
# in it, so a new one is a choice made here.
AROUND_VALUES = {
    ("components/draft-form.js", "changed since you opened it"),  # a save refused: it moved on
    ("components/draft-form.js", "isn't saved. Save it, or discard"),  # Save Your Changes?
    ("components/edu.js", "five-year election"),  # a year's figure worked out from an election
    ("components/links.js", "Its certificate changed to"),  # a security prompt: its fingerprint
    ("components/loan.js", "already holds this payment"),  # the save's consequence: paired
    ("components/receipt.js", "Also kept with"),  # a state: what else holds it, unseen
    ("components/share.js", "left out of the portfolio's figures"),  # a share's consequence
    ("components/taxpanels.js", "at the end of last year ÷"),  # an RMD worked out
    ("components/taxpanels.js", "Last year's total tax:"),  # figures worked out, each labelled
    ("components/tour.js", "uses you can see"),  # a tour's step (S12.17)
    ("components/tour.js", "more you can't see"),  # a tour's step
    ("components/tour.js", "Nothing uses it:"),  # a tour's step
    ("screens/account.js", "one transfer?"),  # a question, its answers as buttons
    ("screens/budgets.js", "paid for a reserve"),  # the money to move, worked out
    ("screens/gifts.js", "who is already here"),  # the answer to choosing a person here
    ("screens/import.js", "below the rows"),  # what the mapping read: lines left out
    ("screens/import.js", "read from its text layer"),  # a statement's state: how it was read
    ("screens/import.js", "don't add up to the summary's"),  # a check worked out, before Save
    ("screens/linked.js", "locks after"),  # a state: who unlocked it, when it locks
    ("screens/linked.js", "as of their last sync"),  # a count's state
    ("screens/linked.js", "by a newer MoolaKata"),  # a state: items this one can't show
    ("screens/projections.js", "when school starts in"),  # an education answer worked out
    ("screens/settings.js", "the database ("),  # what the key encrypts, counted
    ("screens/signin.js", "has an account here"),  # the answer to Send
    ("screens/signin.js", "can ask for an account"),  # the answer to Ask for an Account
    ("screens/users.js", "This turns off two-step sign-in"),  # Turn It Off's consequence
}


def test_no_paragraph_explains_around_a_value():
    """A value keeps a short label on the screen (Label: value); the words that explain it are
    in the guide (R3.12)."""
    found = [
        f"{name}:{line} {words[:90]!r}"
        for name, src in uitext.sources()
        for line, words in uitext.mixed_paragraphs(src)
        if not any(n == name and w in words for n, w in AROUND_VALUES)
    ]
    assert not found, "explanations around a value (to the guide):\n" + "\n".join(found)


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


def test_each_kept_around_a_value_is_still_there():
    """Each paragraph around a value named above is still drawn, so the list can't go stale."""
    for name, words in AROUND_VALUES:
        src = (paths.UI / name).read_text()
        assert any(words in w for _, w in uitext.mixed_paragraphs(src)), (name, words)


# The subtitles of the cards outside the frame that keep their words (R3.12, S12.19.7): each an
# answer, a state or a consequence, by its file and its words' start.
SUBTITLES = {
    ("screens/reset.js", "Every session was signed out"),  # the answer to a password changed
    ("screens/confirm-email.js", "Your new address is in use"),  # the answer to a link opened
    ("screens/confirm-email.js", "Ask for a new one in Profile"),  # an expired link's remedy
    ("screens/signup-confirm.js", "Ask for an account again"),  # an expired link's remedy
    ("screens/welcome.js", "Ask an admin to send a new one"),  # an expired invitation's remedy
    ("screens/new-server.js", "They're shown here once"),  # the consequence of going on
    ("screens/signin.js", "An admin switched it off"),  # the account's state
    ("screens/signin.js", "Your session ended"),  # the answer to a session that expired
}


def test_a_fixed_subtitle_is_found():
    src = """html`<${AuthCard} title="A" sub="This server is new, and two steps make it yours." />
      <${AuthCard} title="B" sub=${x ? 'Short' : 'An invitation works once, for 7 days.'} />
      <${AuthCard} title="C" sub=${`You are invited to ${who}'s server here.`} />`"""
    assert [w for _, w in uitext.auth_subtitles(src)] == [
        "This server is new, and two steps make it yours.",
        "An invitation works once, for 7 days.",
    ]


def test_no_card_outside_the_frame_explains_in_its_subtitle():
    """A card outside the frame keeps an answer, a state or a consequence as its subtitle; what
    the screen is for is in its guide (R3.12)."""
    found = [
        f"{name}:{line} {words!r}"
        for name, src in uitext.sources()
        for line, words in uitext.auth_subtitles(src)
        if not any(n == name and words.startswith(w) for n, w in SUBTITLES)
    ]
    assert not found, "fixed subtitles (to the guide):\n" + "\n".join(found)


def test_each_subtitle_kept_is_still_there():
    for name, words in SUBTITLES:
        src = (paths.UI / name).read_text()
        assert any(w.startswith(words) for _, w in uitext.auth_subtitles(src)), (name, words)
