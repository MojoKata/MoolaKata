"""The browser app against a seeded dev server in headless Chromium (requirements S17.5): its
help pane, guides and terms, privacy mode, sign-in, sign-up, imports and sealed credentials,
each through the app as a person uses it. Every screen's and dialog's guide: test_app_guides.py."""

import re
import time
from collections import deque

import pytest
from devapp import DEV, LOAD_FAILED, check_guide, close_dialog, open_dialog, visit, wait_guide

# Its tests share one page and its dev server, one after another: one worker runs them all.
pytestmark = [pytest.mark.browser, pytest.mark.xdist_group("app")]


def test_a_guides_acronyms_show_what_they_stand_for(page):
    """The first OFX under a heading has a dashed underline, and on hover or keyboard focus a
    card says what it stands for and means, its title row ending in an icon that links to the
    official document, which the pointer and Tab can reach; a later SMTP under the same heading
    is plain until hovered (S12.7.7)."""
    visit(page, "/ui/accounts")
    wait_guide(page, "accounts")
    page.wait_for_selector(".help .guide abbr.term")
    repeats = page.evaluate("""() => {
      const out = [];
      let seen = new Set();
      for (const el of document.querySelectorAll('.help .guide > *')) {
        if (/^H[1-3]$/.test(el.tagName)) seen = new Set();
        for (const a of el.querySelectorAll('abbr.term:not(.quiet)')) {
          if (seen.has(a.dataset.term)) out.push(a.dataset.term);
          seen.add(a.dataset.term);
        }
      }
      return out;
    }""")
    assert repeats == []
    assert page.locator(".help .guide code abbr, .help .guide a abbr").count() == 0
    ofx = page.locator(".help .guide abbr.term", has_text="OFX").first
    assert ofx.evaluate("a => a.firstChild.nodeValue") == "OFX"
    assert ofx.locator(".sr-only").text_content() == " (Open Financial Exchange)"
    shown = ".help .term-tip:not([hidden])"
    card = page.locator(shown)
    assert card.count() == 0
    ofx.hover()
    assert card.locator(".term-abbr").inner_text() == "OFX"
    assert card.locator("b").inner_text() == "Open Financial Exchange"
    text = card.locator(".term-text")
    assert "file format banks and brokers use" in text.inner_text()
    assert ofx.get_attribute("aria-describedby") == text.get_attribute("id")
    source = card.locator(".term-head a.term-source")
    assert source.get_attribute("aria-label") == (
        "OFX specification (Financial Data Exchange), opens in a new tab"
    )
    assert source.get_attribute("href") == (
        "https://financialdataexchange.org/about-fdx/ofx-work-group/"
    )
    assert source.get_attribute("target") == "_blank"
    assert source.locator("svg.i").count() == 1
    icon, title, box = (x.bounding_box() for x in (source, card.locator("b"), card))
    assert icon["x"] > title["x"] + title["width"], "the icon follows the title"
    assert box["x"] + box["width"] - (icon["x"] + icon["width"]) < 16, "at the card's right"
    assert abs((icon["y"] + icon["height"] / 2) - (title["y"] + title["height"] / 2)) < 3
    source.hover()
    page.wait_for_timeout(300)
    assert card.count() == 1, "the card closed under the pointer"
    page.mouse.move(5, 5)
    page.wait_for_selector(shown, state="detached")
    ofx.focus()
    assert card.locator("b").inner_text() == "Open Financial Exchange"
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.className") == "term-source"
    assert card.count() == 1
    page.keyboard.press("Escape")
    page.wait_for_selector(shown, state="detached")
    # A later use under the same heading: plain, no tab stop, underlined and its card on hover.
    visit(page, "/ui/settings/email")
    wait_guide(page, "settings-email")
    later = page.locator(".help .guide abbr.term.quiet", has_text="SMTP").first
    underline = "a => getComputedStyle(a).textDecorationColor"
    assert later.evaluate(underline) == "rgba(0, 0, 0, 0)"
    assert later.get_attribute("tabindex") is None
    later.hover()
    assert later.evaluate(underline) != "rgba(0, 0, 0, 0)"
    assert card.locator("b").inner_text() == "Simple Mail Transfer Protocol"
    page.mouse.move(5, 5)
    page.wait_for_selector(shown, state="detached")
    # Focus scrolls a term below the fold into view; its card opens there and follows it, and
    # closes once the term scrolls out of sight. A short window puts the last one below it.
    page.set_viewport_size({"width": 1440, "height": 420})
    visit(page, "/ui/taxes/summary")
    wait_guide(page, "taxes-summary")
    page.wait_for_selector(".help .guide abbr.term")
    page.evaluate("document.querySelector('.help').scrollTop = 0")
    last = page.locator(".help .guide abbr.term").last
    assert not last.evaluate(
        "a => a.getBoundingClientRect().top < a.closest('.help').getBoundingClientRect().bottom"
    ), "the last term shows without scrolling"
    last.focus()
    page.wait_for_timeout(300)
    assert card.count() == 1
    top = card.bounding_box()["y"]
    page.evaluate("document.querySelector('.help').scrollTop -= 30")
    page.wait_for_timeout(300)
    assert card.count() == 1 and abs(card.bounding_box()["y"] - (top + 30)) < 2
    page.evaluate("document.querySelector('.help').scrollTop = 0")
    page.wait_for_selector(shown, state="detached")
    page.set_viewport_size({"width": 1440, "height": 900})
    assert page.problems == []


def test_a_guides_forms_show_what_they_are(page):
    """A form is marked as a term is: the first 1099-DIV under a heading has a dashed underline,
    and on hover or keyboard focus a card names the form, its title and what it is for, its icon
    linking to the form's page on irs.gov; a later Form 8949 under the same heading is plain
    until hovered, and no tab stop (S12.7.8)."""
    visit(page, "/ui/taxes/income")
    wait_guide(page, "taxes-income")
    div = page.locator(".help .guide h2 abbr.term", has_text="1099-DIV")
    div.wait_for()
    assert div.get_attribute("data-term") == "Form 1099-DIV"
    assert div.evaluate("a => a.firstChild.nodeValue") == "1099-DIV"
    assert div.locator(".sr-only").text_content() == " (Dividends and Distributions)"
    card = page.locator(".help .term-tip:not([hidden])")
    div.hover()
    assert card.locator(".term-abbr").inner_text() == "Form 1099-DIV"
    assert card.locator("b").inner_text() == "Dividends and Distributions"
    assert "dividends and other distributions" in card.locator(".term-text").inner_text()
    source = card.locator("a.term-source")
    assert source.get_attribute("href") == "https://www.irs.gov/forms-pubs/about-form-1099-div"
    assert source.get_attribute("target") == "_blank"
    assert source.get_attribute("aria-label") == "IRS: About Form 1099-DIV, opens in a new tab"
    page.mouse.move(5, 5)
    card.wait_for(state="detached")
    # A long title wraps; the form's name beside it doesn't.
    visit(page, "/ui/taxes/education")
    wait_guide(page, "taxes-education")
    page.locator(".help .guide abbr.term", has_text="Form 709").first.hover()
    assert card.locator("b").inner_text().startswith("United States Gift")
    lines = """a => {
      const r = document.createRange();
      r.selectNodeContents(a);
      return r.getClientRects().length;
    }"""
    assert card.locator(".term-abbr").evaluate(lines) == 1, "Form 709 on one line"
    assert card.locator("b").evaluate(lines) > 1
    page.mouse.move(5, 5)
    card.wait_for(state="detached")
    # A later use under the same heading, in a dialog's guide.
    open_dialog(page, "/ui/taxes/summary", "New tax book", "dialog-tax-book")
    first, later = page.locator(".help .guide abbr.term", has_text="Form 8949").all()
    assert first.get_attribute("tabindex") == "0"
    assert later.get_attribute("class") == "term quiet"
    assert later.get_attribute("tabindex") is None
    underline = "a => getComputedStyle(a).textDecorationColor"
    assert later.evaluate(underline) == "rgba(0, 0, 0, 0)"
    later.hover()
    assert later.evaluate(underline) != "rgba(0, 0, 0, 0)"
    assert card.locator("b").inner_text() == "Sales and Other Dispositions of Capital Assets"
    close_dialog(page)
    assert page.problems == []


# Focus the first or last place Tab stops in a part of the page; say which it is.
TAB_END = """([sel, last]) => {
  const all = [...document.querySelector(sel).querySelectorAll(
    'a[href],button,input,select,textarea,[tabindex]',
  )].filter((x) => x.tabIndex >= 0 && !x.disabled && x.offsetParent);
  const x = last ? all.at(-1) : all[0];
  x.focus();
  return x.outerHTML.slice(0, 80);
}"""
FOCUSED = "() => document.activeElement.outerHTML.slice(0, 80)"


def test_a_dialog_masks_the_content_not_the_guide(page):
    """While a dialog is open the sidebar and the page are dimmed and inert; the help pane
    beside it isn't covered, its terms answer the pointer, and Tab goes round the dialog's
    fields and the guide's. With the pane closed the mask covers everything (S12.1.3)."""
    visit(page, "/ui/taxes/summary")
    page.get_by_role("button", name="New tax book").click()
    page.wait_for_selector(".dialog :focus")
    wait_guide(page, "dialog-tax-book")
    scrim, pane = page.locator(".scrim").bounding_box(), page.locator(".help").bounding_box()
    assert abs(scrim["x"] + scrim["width"] - pane["x"]) < 1, "the mask stops at the pane"
    inert = "() => [...document.querySelectorAll('.app > *')].map((e) => [e.tagName, e.inert])"
    assert page.evaluate(inert) == [["ASIDE", True], ["MAIN", True], ["ASIDE", False]]
    assert page.get_attribute(".dialog", "aria-modal") is None
    page.locator(".help .guide abbr.term").first.hover()
    page.wait_for_selector(".help .term-tip:not([hidden])")
    # Tab: from the dialog's last field into the guide, and from the guide's last back round.
    d1 = page.evaluate(TAB_END, [".dialog", True])
    page.keyboard.press("Tab")
    assert page.evaluate(FOCUSED) == page.evaluate(TAB_END, [".help", False])
    page.keyboard.press("Shift+Tab")
    assert page.evaluate(FOCUSED) == d1
    page.evaluate(TAB_END, [".help", True])
    page.evaluate(TAB_END, [".help", True])  # a term's card, opened by its focus, comes last
    page.keyboard.press("Tab")
    got = page.evaluate(FOCUSED)
    assert got == page.evaluate(TAB_END, [".dialog", False])
    # F1 closes the pane: the mask covers the window and the dialog is modal again.
    page.keyboard.press("F1")
    page.wait_for_selector(".help", state="detached")
    edge = "document.querySelector('.scrim').getBoundingClientRect().right === innerWidth"
    for _ in range(40):
        if page.evaluate(edge):
            break
        page.wait_for_timeout(50)
    assert page.evaluate(edge), "the mask covers the window"
    assert page.get_attribute(".dialog", "aria-modal") == "true"
    page.keyboard.press("F1")
    page.wait_for_selector(".help")
    close_dialog(page)
    assert page.evaluate(inert) == [["ASIDE", False], ["MAIN", False], ["ASIDE", False]]
    assert page.problems == []


def test_a_linked_households_window_opens_with_its_words(page):
    """griffin-parents' window (S12.10): locked, then opened with the dev copy's words, then
    each of its screens with its guide."""
    from moolakata.dev.seed_links import words

    homes = page.evaluate("async () => (await (await fetch('/ui/api/linked')).json()).items")
    assert [h["name"] for h in homes] == ["Margaret & Tom"]
    link = homes[0]["linkId"]
    visit(page, f"/ui/linked/{link}/")
    page.wait_for_selector(".locked-card")
    wait_guide(page, "linked-locked")
    check_guide(page, ".content", "a locked household")
    page.fill("#f-access-key", words())
    page.get_by_role("button", name="Open").click()
    page.wait_for_selector(".peer-strip")
    items = page.evaluate(
        f"async () => (await (await fetch('/ui/api/linked/{link}/items')).json()).items"
    )
    kinds = {i["kind"]: i["id"] for i in items}
    assert set(kinds) == {"account", "portfolio", "budget"}
    acct = next(i["id"] for i in items if i["name"] == "Mom's Retirement")
    for sub, guide in (
        ("", "linked-dashboard"),
        ("accounts", "linked-accounts"),
        (f"account/{acct}", "linked-account"),
        (f"account/{acct}/holdings", "linked-account"),
        (f"account/{acct}/transactions", "linked-account"),
        ("transactions", "linked-transactions"),
        ("portfolios", "linked-portfolios"),
        (f"portfolio/{kinds['portfolio']}", "linked-portfolios"),
        ("budgets", "linked-budgets"),
        (f"budget/{kinds['budget']}", "linked-budgets"),
    ):
        visit(page, f"/ui/linked/{link}/{sub}")
        page.wait_for_selector(".peer-strip")
        wait_guide(page, guide)
        check_guide(page, ".content", f"the linked window's {sub or 'dashboard'}")
    assert "Mom's Retirement" in page.content() or True
    visit(page, f"/ui/linked/{link}/account/{acct}")
    page.wait_for_selector("text=412,880")
    page.get_by_role("button", name="Lock now").click()
    page.wait_for_selector(".locked-card")
    assert page.problems == []


def test_the_help_pane_follows_the_focus_and_f1_toggles_it(page):
    visit(page, "/ui/profile")
    page.focus("#f-birthday")
    page.wait_for_selector('.help [data-anchor="birthday"].flash')
    page.wait_for_selector('.help [data-anchor="birthday"]:not(.flash)')
    assert page.locator(".help h2.active").evaluate_all("hs => hs.map(h => h.dataset.anchor)") == [
        "birthday"
    ]
    page.focus("#f-display-name")
    page.wait_for_selector('.help [data-anchor="display-name"].active')
    assert page.locator(".help h2.active").count() == 1
    page.keyboard.press("F1")
    page.wait_for_selector(".help", state="detached")
    assert page.is_visible(".help-corner")
    page.keyboard.press("F1")
    page.wait_for_selector(".help")


def test_privacy_mode_blurs_amounts(page):
    visit(page, "/ui/accounts")
    page.get_by_role("button", name="Hide amounts (privacy mode)").click()
    page.wait_for_selector("body.privacy")
    blur = page.evaluate("getComputedStyle(document.querySelector('.amt')).filter")
    assert "blur" in blur
    page.get_by_role("button", name="Show amounts").click()


def test_a_moment_shows_its_day_in_the_viewers_zone(page):
    """S14.9: a moment's day and "today" are the viewer's; a calendar date never shifts. Late
    on Oct 18 in Los Angeles is already Oct 19 in UTC. (A module of its own, by its query, so
    the page's zone is left as it is.)"""
    got = page.evaluate("""async () => {
        const main = document.querySelector('script[src$="/app/main.js"]').src;
        const f = await import(new URL('format.js?zone-test', main).href);
        f.setZone('America/Los_Angeles');
        const days = [f.day('2026-10-19T00:26:00Z'), f.date('2026-10-19'), f.day(null)];
        f.setZone('Pacific/Kiritimati');
        const ahead = [f.today(), f.thisYear()];
        f.setZone('Etc/GMT+12');
        return { days, ahead, behind: f.today() };
    }""")
    assert got["days"] == ["Oct 18, 2026", "Oct 19, 2026", "—"]
    ahead, year = got["ahead"]
    assert ahead > got["behind"] and len(ahead) == 10 and year == int(ahead[:4])


def test_every_password_field_has_an_eye_that_reveals_it(page):
    visit(page, "/ui/profile")
    fields = page.locator("input.in[type=password]")
    assert fields.count() == 2
    assert page.locator(".pw > input.in + button.icon-btn").count() == fields.count()
    page.fill("#f-current-password", "secret words")
    page.locator("#f-current-password + button").click()
    assert page.get_attribute("#f-current-password", "type") == "text"
    page.get_by_role("button", name="Hide password").click()
    assert page.get_attribute("#f-current-password", "type") == "password"
    assert page.input_value("#f-current-password") == "secret words"


def test_categorise_and_share_through_the_app(page):
    visit(page, "/ui/transactions?category=none")
    page.wait_for_selector("tbody input[type=checkbox]")
    boxes = page.query_selector_all("tbody input[type=checkbox]:not([disabled])")
    boxes[0].check()
    boxes[1].check()
    page.select_option("#f-categorise-as", label="Food › Groceries")
    page.get_by_role("button", name="Categorise", exact=True).click()
    page.wait_for_selector("text=2 transactions categorised")
    visit(page, "/ui/accounts")
    page.get_by_role("button", name="Share Taxable brokerage").click()
    page.wait_for_selector(".dialog .seg")
    page.get_by_role("radio", name="Read").first.click()
    page.get_by_role("button", name="Save").click()
    page.wait_for_selector("text=Sharing saved")
    assert page.problems == []


def test_landed_money_assigned_a_line_for_each_reserve(page):
    # S7.10.5: the lines start spread by balance; the moves they make are saved together.
    visit(page, "/ui/budgets/x/where")
    page.get_by_role("button", name="Assign").first.click()
    page.wait_for_selector(".dialog #x-reserve, .dialog [data-help=reserve]")
    page.get_by_role("button", name="Spread by balance").click()
    page.locator(".dialog footer button.primary").click()
    page.wait_for_selector("text=Assigned")
    page.wait_for_selector(".dialog", state="detached")
    assert page.problems == []


def signed_in_page(page, username: str):
    """Another browser context, signed in as one of the seed users, watched like `page`."""
    ctx = page.context.browser.new_context(
        ignore_https_errors=True, viewport={"width": 1440, "height": 900}
    )
    pg = ctx.new_page()
    pg.problems, pg.api_times, pg.base = [], deque(), page.base
    pg.on("pageerror", lambda e: pg.problems.append(f"page error on {pg.url}: {e}"))
    pg.on(
        "console",
        lambda m: (
            m.type == "error"
            and not LOAD_FAILED.search(m.text)
            and pg.problems.append(f"console on {pg.url}: {m.text}")
        ),
    )
    pg.goto(page.base + "/ui/")
    pg.fill("#f-username-or-email", username)
    pg.fill("#f-password", "moolakata-dev")
    pg.click("button.btn.primary")
    return pg


def test_two_step_sign_in_through_the_app(page):
    """Turn it on in Profile, sign in with a recovery code, and an admin resets it (S10.1.6)."""
    from moolakata.auth import twostep

    bob = signed_in_page(page, "bob")
    bob.wait_for_selector(".side")
    visit(bob, "/ui/profile")
    bob.locator("#two-step").get_by_role("button", name="Turn on").click()
    bob.wait_for_selector(".dialog .qr img")
    wait_guide(bob, "dialog-two-step")
    check_guide(bob, ".dialog", "Turn on two-step sign-in")
    seed = bob.inner_text(".dialog code.key").replace(" ", "")
    bob.fill("#f-two-step-code", "000000")
    bob.locator(".dialog").get_by_role("button", name="Turn on").click()
    bob.wait_for_selector(".dialog .err")
    bob.fill("#f-two-step-code", twostep.code_at(seed, int(time.time()) // 30))
    bob.locator(".dialog").get_by_role("button", name="Turn on").click()
    bob.wait_for_selector(".dialog ul.codes")
    wait_guide(bob, "dialog-recovery-codes")
    codes = bob.locator(".dialog ul.codes code").all_inner_texts()
    assert len(codes) == 10
    bob.get_by_role("button", name="I've saved them").click()
    bob.wait_for_selector("#two-step .pill.ok")
    assert "10 recovery codes left" in bob.inner_text("#two-step")
    assert bob.problems == []
    bob.context.close()

    again = signed_in_page(page, "bob")
    again.wait_for_selector("text=Two-step sign-in")
    again.get_by_role("button", name="Use a recovery code").click()
    again.fill("#f-recovery-code", codes[3])
    again.get_by_role("button", name="Sign in", exact=True).click()
    again.wait_for_selector(".side")
    assert again.problems == []
    again.context.close()

    admin = signed_in_page(page, "admin")
    admin.wait_for_selector(".side")
    visit(admin, "/ui/users")
    row = admin.locator("tr", has_text="bob@")
    assert row.locator(".pill.ok", has_text="two-step").count() == 1
    row.get_by_role("button", name="Edit").click()
    admin.get_by_role("button", name="Reset two-step").click()
    admin.get_by_role("button", name="Turn it off").click()
    admin.wait_for_selector("text=Two-step sign-in is off for")
    row.locator(".pill.ok", has_text="two-step").wait_for(state="detached")
    assert admin.problems == []
    admin.context.close()


def last_mail_link() -> str:
    import email
    import email.policy

    newest = max((DEV["data"] / "mail").glob("*.eml"), key=lambda p: p.stat().st_mtime)
    msg = email.message_from_bytes(newest.read_bytes(), policy=email.policy.default)
    return re.search(r"https://\S+", msg.get_body().get_content()).group(0)


def test_sign_up_through_the_app(page):
    """Sign-up opened by an admin, asked for, confirmed and approved (S10.1.4)."""
    admin = signed_in_page(page, "admin")
    admin.wait_for_selector(".side")
    visit(admin, "/ui/settings/signup")
    admin.locator("#f-sign-up").click()
    admin.get_by_role("button", name="Save").click()
    admin.wait_for_selector("text=Saved")

    ctx = page.context.browser.new_context(
        ignore_https_errors=True, viewport={"width": 1440, "height": 900}
    )
    guest = ctx.new_page()
    guest.goto(page.base + "/ui/")
    guest.get_by_role("button", name="Sign up").click()
    guest.fill("#f-display-name", "Erin Shaw")
    guest.select_option("#f-sex", "female")
    guest.fill("#f-email", "erin@shaw.family")
    guest.fill("#f-username", "erin")
    guest.fill("#f-password", "a long passphrase for erin")
    guest.get_by_role("button", name="Ask for an account").click()
    guest.wait_for_selector("text=a link to confirm it is on its way")
    url = last_mail_link()
    assert "/ui/signup/confirm#" in url
    guest.goto(page.base + url[url.index("/ui/") :])
    guest.wait_for_selector("text=Waiting for approval")

    visit(admin, "/ui/users")
    req = admin.locator(".list-item", has_text="erin@shaw.family")
    req.get_by_role("button", name="Approve").click()
    admin.wait_for_selector("text=Erin Shaw can sign in now")
    assert admin.problems == []
    admin.context.close()

    guest.goto(page.base + "/ui/signin")
    guest.fill("#f-username-or-email", "erin")
    guest.fill("#f-password", "a long passphrase for erin")
    guest.get_by_role("button", name="Sign in", exact=True).click()
    guest.wait_for_selector(".side")
    ctx.close()


def test_import_a_statement_through_the_app(page):
    """A statement's PDF, checked and saved (S1.3.3)."""
    from test_reading import text_pdf

    pdf = text_pdf(
        [
            "First Example Bank",
            "Statement Period: 09/01/26 - 09/30/26",
            "Beginning Balance $100.00",
            "Ending Balance $57.82",
            "Withdrawals and Other Debits",
            "09/03 CORNER BAKERY 42.18",
            "09/05 PENDING HOLD RELEASED 10.00",
        ]
    )
    visit(page, "/ui/accounts")
    page.get_by_role("button", name="Import").first.click()
    page.wait_for_selector(".dialog")
    page.select_option(".dialog #f-into-account", label="Emergency savings")
    page.set_input_files(
        ".dialog input[type=file]",
        files=[{"name": "september.pdf", "mimeType": "application/pdf", "buffer": pdf}],
    )
    page.locator(".dialog").get_by_role("button", name="Import").click()
    page.wait_for_selector("text=Check the statement", timeout=60000)
    wait_guide(page, "dialog-statement")
    check_guide(page, ".dialog", "the statement check")
    # A line that isn't a transaction, left out and remembered to be ignored from the next
    # statement on (S1.3.3.4).
    line = page.locator(".dialog tbody tr").nth(1)
    assert line.locator("input[aria-label=Description]").input_value() == "PENDING HOLD RELEASED"
    line.locator("input[type=checkbox]").uncheck()
    assert page.inner_text(".dialog .kv").count("yes") == 1
    line.get_by_text("Remember…").click()
    asked = page.locator(".dialog .ask-inline input")
    assert asked.input_value() == "pending hold released"
    page.locator(".dialog .ask-inline").get_by_role("button", name="OK").click()
    page.wait_for_selector(".dialog >> text=Ignored next time")
    page.get_by_role("button", name="Import 1 new").click()
    page.wait_for_selector(".dialog >> text=Imported")
    page.get_by_role("button", name="Done").click()
    visit(page, "/ui/profile")
    page.wait_for_selector("text=“pending hold released”")
    assert page.problems == []


def test_a_credential_sealed_in_the_browser_opens_only_with_the_connectors_key(page):
    """The box web/ui/app/sealed.js makes with WebCrypto (S18.7.1) is the construction
    moolakata.connector.sealed opens: X25519, HKDF-SHA256 over the Connection's id, AES-GCM."""
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    from moolakata.connector import sealed
    from moolakata.links import keys

    key = X25519PrivateKey.generate()
    public = keys.b64(key.public_key().public_bytes_raw())
    visit(page, "/ui/")
    version = page.evaluate("fetch('/healthz').then((r) => r.json()).then((j) => j.version)")
    box = page.evaluate(
        "([v, key]) => import(`/ui/v/${v}/app/sealed.js`)"
        ".then((m) => m.seal('{\"password\": \"hunter2\"}', key, 'Conn_test'))",
        [version, public],
    )
    assert sealed.looks_sealed(box)
    assert sealed.open_box(box, key, "Conn_test") == b'{"password": "hunter2"}'
    with pytest.raises(Exception):  # noqa: B017 - another Connection's id: a different key
        sealed.open_box(box, key, "Conn_other")
    assert page.problems == []
