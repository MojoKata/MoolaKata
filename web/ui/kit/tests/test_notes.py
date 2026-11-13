"""The note (requirements S12.18.15) in Chromium: the editor loaded only to edit; its toolbar,
keys and list shortcuts; links typed, pasted, made from the popover and refused; pasted markup
kept only as a note allows; the note read, a page out of reach greyed; the limit; Home and End."""

import json

from conftest import open_page
from playwright.sync_api import expect


def editor(page, demo: str):
    return page.locator(f"[data-demo='{demo}'] .ProseMirror")


def kept(page, demo: str):
    """The document the demo last reported, or None."""
    pre = page.locator(f"[data-report='{demo}'] details pre").first
    return json.loads(pre.text_content()) if pre.count() else None


def blocks(page, demo: str) -> list[str]:
    doc = kept(page, demo)
    return [b["type"] for b in doc["content"]] if doc else []


def paste(page, demo: str, data: dict[str, str]):
    """A paste into the editor, with what the clipboard holds by type."""
    editor(page, demo).evaluate(
        """(el, data) => {
          const dt = new DataTransfer();
          for (const [k, v] of Object.entries(data)) dt.setData(k, v);
          el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true,
            cancelable: true }));
        }""",
        data,
    )


def test_the_editor_loads_only_when_a_note_is_edited(page, kit):
    loaded = (
        "() => performance.getEntriesByType('resource')"
        ".some(r => /note-editor\\.js|prosemirror-view\\/dist/.test(r.name))"
    )
    open_page(page, kit, "fields")
    assert not page.evaluate(loaded)
    open_page(page, kit, "notes")
    expect(editor(page, "note")).to_be_visible()
    assert page.evaluate(loaded)


def test_marks_from_the_keys_and_the_toolbar_and_the_toolbar_says_which_are_on(page, kit):
    open_page(page, kit, "notes")
    ed = editor(page, "note-empty")
    ed.click()
    page.keyboard.type("plain ")
    page.keyboard.press("Control+b")
    page.keyboard.type("bold")
    bold = page.locator("[data-demo='note-empty'] button[aria-label='Bold']")
    expect(bold).to_have_attribute("aria-pressed", "true")
    page.keyboard.press("Control+b")
    page.locator("[data-demo='note-empty'] button[aria-label='Highlight']").click()
    page.keyboard.type(" marked")
    expect(ed).to_be_focused()
    texts = kept(page, "note-empty")["content"][0]["content"]
    assert texts == [
        {"type": "text", "text": "plain "},
        {"type": "text", "text": "bold", "marks": [{"type": "bold"}]},
        {"type": "text", "text": " marked", "marks": [{"type": "highlight"}]},
    ]
    expect(bold).to_have_attribute("aria-pressed", "false")


def test_the_block_menu_makes_headings_pre_formatted_text_and_quotes(page, kit):
    open_page(page, kit, "notes")
    ed = editor(page, "note-empty")
    ed.click()
    page.keyboard.type("Plan")
    menu = page.locator("[data-demo='note-empty'] .note-block")
    for pick, kind in (("Heading 2", "heading"), ("Pre-formatted", "pre"), ("Quote", "quote")):
        menu.click()
        page.get_by_role("menuitem", name=pick, exact=True).click()
        expect(ed).to_be_focused()
        expect(menu).to_contain_text(pick)
        assert blocks(page, "note-empty") == [kind], pick
        if kind == "heading":
            assert kept(page, "note-empty")["content"][0]["attrs"] == {"level": 2}
            # Drawn in the editor as its own level.
            assert ed.locator("h2").count() == 1
        if kind == "pre":
            # No marks in pre-formatted text: the buttons say so.
            b = page.locator("[data-demo='note-empty'] button[aria-label='Bold']")
            expect(b).to_have_attribute("aria-disabled", "true")
            expect(b).to_have_attribute("data-tip", "Bold: not in pre-formatted text")
        if kind == "quote":
            menu.click()
            page.get_by_role("menuitem", name="Paragraph", exact=True).click()
    assert blocks(page, "note-empty") == ["paragraph"]
    page.keyboard.press("Control+Alt+3")
    assert kept(page, "note-empty")["content"][0] == {
        "type": "heading",
        "attrs": {"level": 3},
        "content": [{"type": "text", "text": "Plan"}],
    }


def test_the_list_shortcuts_and_backspace_undoing_one(page, kit):
    open_page(page, kit, "notes")
    ed = editor(page, "note-empty")
    ed.click()
    page.keyboard.type("- a")
    assert blocks(page, "note-empty") == ["bullets"]
    # Tab indents, three deep at most; where it can't, it does nothing and the focus stays.
    for item in ("b", "c", "d"):
        page.keyboard.press("Enter")
        page.keyboard.type(item)
        page.keyboard.press("Tab")
    page.keyboard.press("Tab")
    expect(ed).to_be_focused()
    assert ed.locator("ul ul ul li").count() == 2 and ed.locator("ul ul ul ul").count() == 0
    expect(page.locator("[data-demo='note-empty'] button[aria-label='Indent']")).to_have_attribute(
        "aria-disabled", "true"
    )
    for _ in range(4):
        page.keyboard.press("Enter")
    # Out of the lists, a paragraph again; then 1. makes a numbered list.
    page.keyboard.type("1. first")
    assert blocks(page, "note-empty") == ["bullets", "numbers"]
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    # Backspace right after a shortcut puts the text back.
    page.keyboard.type("* ")
    page.keyboard.press("Backspace")
    assert blocks(page, "note-empty") == ["bullets", "numbers", "paragraph"]
    assert kept(page, "note-empty")["content"][2]["content"] == [{"type": "text", "text": "* "}]
    # Out of a list, Tab goes on to the next field.
    page.keyboard.press("Tab")
    expect(ed).not_to_be_focused()


def test_an_address_typed_becomes_a_link_and_the_popover_makes_changes_and_refuses(page, kit):
    open_page(page, kit, "notes")
    d = "[data-demo='note-empty']"
    ed = editor(page, "note-empty")
    ed.click()
    page.keyboard.type("see www.example.com/a. then")
    link = ed.locator("a")
    expect(link).to_have_text("www.example.com/a")
    expect(link).to_have_attribute("href", "https://www.example.com/a")
    # The words "then" selected, Ctrl+K: the popover; a script's address refused at its field.
    ed.evaluate(
        """el => { const t = el.querySelector('p').lastChild; const r = document.createRange();
          r.setStart(t, t.length - 4); r.setEnd(t, t.length); const s = getSelection();
          s.removeAllRanges(); s.addRange(r); }"""
    )
    page.wait_for_timeout(100)
    page.keyboard.press("Control+k")
    field = page.locator(f"{d} .note-pop input")
    expect(field).to_be_focused()
    field.fill("javascript:alert(1)")
    page.keyboard.press("Enter")
    expect(page.locator(f"{d} .note-pop")).to_contain_text("Only http and https addresses.")
    # This server's address: kept as the page alone.
    field.fill("https://moolakata.loco/ui/budgets/Bud_3K9")
    page.keyboard.press("Enter")
    expect(page.locator(f"{d} .note-pop.edit")).to_have_count(0)
    expect(ed).to_be_focused()
    texts = kept(page, "note-empty")["content"][0]["content"]
    assert texts[-1] == {
        "type": "text",
        "text": "then",
        "marks": [{"type": "link", "attrs": {"page": "budgets/Bud_3K9"}}],
    }
    assert texts[1]["marks"] == [{"type": "link", "attrs": {"href": "https://www.example.com/a"}}]
    # The caret in it: its page by name, and Remove takes the link off, the focus kept.
    page.keyboard.press("ArrowLeft")
    caret = page.locator(f"{d} .note-pop.caret")
    expect(caret).to_contain_text("Budgets › Groceries")
    caret.get_by_role("button", name="remove").click()
    expect(ed).to_be_focused()
    assert kept(page, "note-empty")["content"][0]["content"][-1] == {
        "type": "text",
        "text": ". then",
    }


def test_an_address_pasted_over_words_links_them_and_alone_comes_in_as_a_link(page, kit):
    open_page(page, kit, "notes")
    ed = editor(page, "note-empty")
    ed.click()
    page.keyboard.type("the guide")
    page.keyboard.press("Shift+Home")
    # The editor takes the new selection when the browser says it changed.
    page.wait_for_timeout(100)
    paste(page, "note-empty", {"text/plain": "https://example.com/guide"})
    page.keyboard.press("End")
    page.keyboard.type(" ")
    paste(page, "note-empty", {"text/plain": "https://moolakata.loco/ui/accounts/Acct_7Q2"})
    texts = kept(page, "note-empty")["content"][0]["content"]
    assert texts == [
        {
            "type": "text",
            "text": "the guide",
            "marks": [{"type": "link", "attrs": {"href": "https://example.com/guide"}}],
        },
        {"type": "text", "text": " "},
        {
            "type": "text",
            "text": "https://moolakata.loco/ui/accounts/Acct_7Q2",
            "marks": [{"type": "link", "attrs": {"page": "accounts/Acct_7Q2"}}],
        },
    ]


def test_pasted_markup_keeps_only_what_a_note_holds(page, kit):
    open_page(page, kit, "notes")
    ed = editor(page, "note-empty")
    ed.click()
    paste(
        page,
        "note-empty",
        {
            "text/html": (
                "<h1>Title</h1><h5 data-note-level='2'>Copied</h5>"
                "<p style='color:red'>a<b>b</b><script>window.pwned=1</script>"
                "<img src=x onerror='window.pwned=2'><a href='javascript:window.pwned=3'>bad</a>"
                "<a href='https://example.com/'>good</a><span style='font-weight:700'>w</span></p>"
                "<b style='font-weight:normal' id='docs-internal-guid-1'><span"
                " style='font-weight:700'>G</span><span style='font-style:italic;"
                "text-decoration-line:underline line-through'>x</span></b>"
                "<table><tr><td>c1</td><td>c2</td></tr></table><iframe src='https://example.com'></iframe>"
            ),
            "text/plain": "Title a b bad good w c1 c2",
        },
    )
    page.wait_for_timeout(200)
    assert page.evaluate("window.pwned") is None
    doc = kept(page, "note-empty")
    assert [b["type"] for b in doc["content"]] == [
        "heading",
        "heading",
        "paragraph",
        "paragraph",
        "paragraph",
        "paragraph",
    ]
    # A pasted h1 is a note's first level; a heading copied from a note read keeps its own.
    assert doc["content"][0]["attrs"] == {"level": 1}
    assert doc["content"][1]["attrs"] == {"level": 2}
    doc["content"].pop(1)
    para = doc["content"][1]["content"]
    assert "".join(t["text"] for t in para) == "abbadgoodw"
    marks = {t["text"]: t.get("marks") for t in para}
    assert marks["b"] == [{"type": "bold"}] and marks["w"] == [{"type": "bold"}]
    assert marks["bad"] is None
    assert marks["good"] == [{"type": "link", "attrs": {"href": "https://example.com/"}}]
    # A word processor's style-only formatting (Google Docs): its bold, italic, underline and
    # strikethrough kept; its wrapper, bold drawn normal, unwrapped.
    assert doc["content"][2]["content"] == [
        {"type": "text", "text": "G", "marks": [{"type": "bold"}]},
        {
            "type": "text",
            "text": "x",
            "marks": [{"type": "italic"}, {"type": "underline"}, {"type": "strike"}],
        },
    ]
    assert [b["content"][0]["text"] for b in doc["content"][3:]] == ["c1", "c2"]
    assert ed.locator("script, img, iframe, [style*='color']").count() == 0


def test_a_note_read_opens_its_links_and_greys_a_page_out_of_reach(page, kit):
    open_page(page, kit, "notes")
    d = "[data-demo='note-read']"
    out = page.locator(f"{d} a", has_text="closing cost guide")
    expect(out).to_have_attribute("target", "_blank")
    expect(out).to_have_attribute("rel", "noopener noreferrer nofollow")
    expect(out).to_have_attribute("data-tip", "https://www.consumerfinance.gov/owning-a-home/")
    inside = page.locator(f"{d} a", has_text="Everyday Checking")
    expect(inside).to_have_attribute("data-tip", "Accounts › Everyday Checking")
    inside.click()
    expect(page.locator("[data-report='note-read']")).to_contain_text("opened accounts/Acct_7Q2")
    off = page.locator(f"{d} .note-link.off")
    expect(off).to_have_text("Backups")
    expect(off).to_have_attribute("data-tip", "Settings › Backups · Not shared with you")
    # Its headings at the levels this card claims (h4 to h6), each keeping the note's own.
    heads = page.locator(f"{d} h4, {d} h5, {d} h6")
    assert heads.evaluate_all("els => els.map(e => [e.tagName, e.dataset.noteLevel])") == [
        ["H4", "1"],
        ["H5", "2"],
        ["H6", "3"],
    ]
    # Read, the note has no editor.
    assert page.locator(f"{d} .ProseMirror, {d} .note-bar").count() == 0


def test_past_its_limit_the_count_shows_and_the_note_is_marked_when_left(page, kit):
    open_page(page, kit, "notes")
    d = "[data-demo='note-long']"
    count = page.locator(f"{d} .note-count")
    expect(count).to_have_text("20,085 of 20,000")
    expect(count).to_have_class("note-count small over")
    editor(page, "note-long").click()
    expect(page.locator(f"{d} .note.bad")).to_have_count(0)
    page.keyboard.press("Control+End")
    page.keyboard.press("Tab")
    expect(page.locator(f"{d} .note")).to_have_class("note bad")
    expect(page.locator(f"{d} .note")).to_have_attribute(
        "data-tip", "At most 20,000 characters (this has 20,085)."
    )
    # Any change clears the mark.
    editor(page, "note-long").click()
    page.wait_for_timeout(100)
    page.keyboard.press("Backspace")
    expect(page.locator(f"{d} .note.bad")).to_have_count(0)


def test_the_toolbar_is_one_stop_reached_by_alt_f10_and_left_by_escape(page, kit):
    open_page(page, kit, "notes")
    d = "[data-demo='note']"
    ed = editor(page, "note")
    ed.click()
    page.keyboard.press("Alt+F10")
    expect(page.locator(f"{d} .note-block")).to_be_focused()
    page.keyboard.press("ArrowRight")
    expect(page.locator(f"{d} button[aria-label='Bold']")).to_be_focused()
    page.keyboard.press("End")
    expect(page.locator(f"{d} button[aria-label='Indent']")).to_be_focused()
    page.keyboard.press("ArrowRight")
    expect(page.locator(f"{d} .note-block")).to_be_focused()
    page.keyboard.press("Escape")
    expect(ed).to_be_focused()
    assert page.locator(f"{d} .note-bar [tabindex='0']").count() == 1


def test_home_and_end_go_to_the_drawn_lines_ends_in_a_note(page, kit):
    open_page(page, kit, "notes")
    ed = editor(page, "note-long")
    ed.click()
    # Somewhere on a line drawn after the first.
    ed.evaluate(
        """el => { const t = el.querySelector('p').firstChild; const r = document.createRange();
          r.setStart(t, 300); r.collapse(true); const s = getSelection(); s.removeAllRanges();
          s.addRange(r); }"""
    )
    at = "() => getSelection().anchorOffset"
    page.keyboard.press("Home")
    home = page.evaluate(at)
    text = ed.locator("p").first.text_content()
    assert 0 < home < 300 and text[home - 1] == " ", "the drawn line's start"
    page.keyboard.press("End")
    assert 300 < page.evaluate(at) < len(text)
    page.keyboard.press("Control+Home")
    assert page.evaluate(at) == 0


def test_an_off_note_is_shown_and_takes_nothing(page, kit):
    open_page(page, kit, "notes")
    d = "[data-demo='note-off']"
    expect(editor(page, "note-off")).to_have_attribute("contenteditable", "false")
    for name in ("Bold", "Link", "Bulleted list"):
        expect(page.locator(f"{d} button[aria-label='{name}']")).to_have_attribute(
            "aria-disabled", "true"
        )


def test_the_list_buttons_make_switch_indent_and_end_a_list(page, kit):
    open_page(page, kit, "notes")
    d = "[data-demo='note-empty']"
    ed = editor(page, "note-empty")
    ed.click()
    page.keyboard.type("a")
    button = lambda name: page.locator(f"{d} button[aria-label='{name}']")  # noqa: E731
    expect(button("Outdent")).to_have_attribute("data-tip", "Outdent: in a list only")
    button("Bulleted list").click()
    assert blocks(page, "note-empty") == ["bullets"]
    expect(button("Bulleted list")).to_have_attribute("aria-pressed", "true")
    button("Numbered list").click()
    assert blocks(page, "note-empty") == ["numbers"]
    page.keyboard.press("Enter")
    page.keyboard.type("b")
    button("Indent").click()
    assert ed.locator("ol ol li").count() == 1
    button("Outdent").click()
    assert ed.locator("ol ol").count() == 0 and ed.locator("ol > li").count() == 2
    button("Numbered list").click()
    assert blocks(page, "note-empty") == ["numbers", "paragraph"]
    expect(ed).to_be_focused()


def test_a_link_at_the_caret_is_followed_changed_and_made_from_the_toolbar(page, kit):
    open_page(page, kit, "notes")
    d = "[data-demo='note']"
    ed = editor(page, "note")
    ed.locator("a", has_text="Everyday Checking").click()
    caret = page.locator(f"{d} .note-pop.caret")
    expect(caret).to_contain_text("Accounts › Everyday Checking")
    page.keyboard.press("Control+Enter")
    expect(page.locator("[data-report='note']")).to_contain_text("opened accounts/Acct_7Q2")
    caret.get_by_role("button", name="edit").click()
    field = page.locator(f"{d} .note-pop input")
    expect(field).to_have_value("https://moolakata.loco/ui/accounts/Acct_7Q2")
    field.fill("https://example.com/x")
    page.locator(f"{d} .note-pop").get_by_role("button", name="Apply").click()
    expect(ed.locator("a", has_text="Everyday Checking")).to_have_attribute(
        "href", "https://example.com/x"
    )
    # An address opens in a new tab.
    ed.locator("a", has_text="Everyday Checking").click()
    with page.context.expect_page() as tab:
        page.locator(f"{d} .note-pop.caret").get_by_role("button", name="open").click()
    # (Where it lands is the network's business; a tab of its own is the point.)
    tab.value.close()
    # With nothing selected, Link puts the address in as its own words; Escape leaves it be.
    ed.click()
    page.wait_for_timeout(100)
    page.keyboard.press("Control+End")
    page.keyboard.press("Enter")
    page.locator(f"{d} button[aria-label='Link']").click()
    page.locator(f"{d} .note-pop input").fill("https://example.com/new")
    page.keyboard.press("Escape")
    expect(page.locator(f"{d} .note-pop.edit")).to_have_count(0)
    expect(ed).to_be_focused()
    page.locator(f"{d} button[aria-label='Link']").click()
    page.locator(f"{d} .note-pop input").fill("https://example.com/new")
    page.keyboard.press("Enter")
    expect(ed.locator("a", has_text="https://example.com/new")).to_have_attribute(
        "href", "https://example.com/new"
    )


def test_the_apps_styles_never_reach_inside_a_note(page, kit):
    """A note is a realm of its own: rules in every layer the app writes in, aimed at its
    elements, change nothing in it, written or read; only the theme's tokens reach it."""
    open_page(page, kit, "notes")
    editor(page, "note").wait_for()
    probe = """() => [...document.querySelectorAll(
        "[data-demo='note'] .note-text :is(h1, h2, h3, p, li, a, strong, mark, pre, blockquote)," +
        "[data-demo='note-read'] .note-text :is(h4, h5, h6, p, li, a, pre)")]
      .map(e => { const s = getComputedStyle(e); return [e.tagName, s.color, s.fontSize,
        s.fontFamily, s.margin, s.letterSpacing, s.textTransform, s.backgroundColor]
        .join('|'); })"""
    before = page.evaluate(probe)
    page.evaluate(
        """() => {
          const sheet = new CSSStyleSheet();
          const rules = `.demo *, h1, h2, h3, h4, h5, h6, p, li, a, strong, mark, pre, blockquote,
            .kit-page .demo .note-text p { color: red; font-size: 40px; font-family: serif;
            margin: 50px; letter-spacing: 6px; text-transform: uppercase; background: lime; }`;
          sheet.replaceSync(['tokens', 'base', 'kit', 'components']
            .map((l) => `@layer ${l} { ${rules} }`).join('\\n'));
          document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
        }"""
    )
    # The hostile rules took hold outside the note, so they would have inside.
    spacing = "e => getComputedStyle(e).letterSpacing"
    assert page.locator(".kit-page > .about").evaluate(spacing) == "6px"
    assert page.evaluate(probe) == before


def test_a_screen_claims_the_heading_levels_a_note_takes_when_read(page, kit):
    """Each level drawn from the claim's top; a level past the levels claimed takes the last; none
    past h6. The note's own level rides along whatever the tag."""
    open_page(page, kit, "notes")
    drawn = page.evaluate(
        """async () => {
          const { render } = await import('preact');
          const { html } = await import('../html.js');
          const { NoteView } = await import('../note-view.js');
          const h = (level) => ({ type: 'heading', attrs: { level },
            content: [{ type: 'text', text: 'x' }] });
          const doc = { type: 'doc', content: [h(1), h(2), h(3)] };
          const out = {};
          const claims = [['default', undefined], ['top 5, two', { top: 5, count: 2 }],
            ['top 6', { top: 6, count: 3 }], ['one', { top: 3, count: 1 }]];
          for (const [name, heading] of claims) {
            const el = document.createElement('div');
            render(html`<${NoteView} doc=${doc} heading=${heading} />`, el);
            out[name] = [...el.querySelectorAll('h1, h2, h3, h4, h5, h6')]
              .map((e) => `${e.tagName}:${e.dataset.noteLevel}`);
          }
          return out;
        }"""
    )
    assert drawn == {
        "default": ["H2:1", "H3:2", "H4:3"],
        "top 5, two": ["H5:1", "H6:2", "H6:3"],
        "top 6": ["H6:1", "H6:2", "H6:3"],
        "one": ["H3:1", "H3:2", "H3:3"],
    }
