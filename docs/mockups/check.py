"""Open every screen, tab, Settings section and dialog of the mockup and fail on any error.

    python docs/mockups/check.py shots/

Needs Playwright for Python and its Chromium (`pip install playwright`, then
`playwright install chromium`). The screens, dialogs and Settings sections come from the
mockup itself (`window.MOCK_INDEX`), so nothing here needs updating when one is added.
Screenshots of each go to the directory given. The mockup draws at `zoom: 2`, so the
viewport is 2880x1800, which shows what a 1440x900 window does.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

MOCKUP = Path(__file__).resolve().parent / "MoolaKata-mock.html"
VIEWPORT = {"width": 2880, "height": 1800}


def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    url = MOCKUP.as_uri()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT)
        page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
        page.on(
            "console",
            lambda m: m.type == "error" and errors.append(f"console: {m.text}"),
        )
        page.goto(url + "#/dashboard")
        page.wait_for_timeout(200)
        index = page.evaluate("window.MOCK_INDEX")
        shots = 0

        def shot(name: str) -> None:
            nonlocal shots
            page.screenshot(path=str(out / f"{name}.png"))
            shots += 1

        def missing_help(where: str, scope: str) -> None:
            missing = page.evaluate(
                f"[...document.querySelectorAll('{scope} [id^=f-]')].map(e => e.id.slice(2))"
                ".filter(i => !document.getElementById('h-' + i))"
            )
            if missing:
                errors.append(f"{where}: fields without a help heading: {missing}")

        for locked in (False, True):
            page.evaluate(f"state.locked = {str(locked).lower()}")
            for screen in index["screens"]:
                if locked and not screen.startswith("linked"):
                    continue
                tag = screen.replace("/", "_") + ("-locked" if locked else "")
                page.evaluate(f"state.signedOut = false; location.hash = '#/{screen}'")
                page.wait_for_timeout(120)
                shot(tag)
                missing_help(screen, "main")
                for tab in page.query_selector_all(".tab"):
                    key, value = (
                        tab.get_attribute("data-k"),
                        tab.get_attribute("data-v"),
                    )
                    page.evaluate(f"state.tabs[{key!r}] = {value!r}; render()")
                    page.wait_for_timeout(60)
                    shot(f"{tag}-{value.split(' ')[0].lower()}")
                    missing_help(f"{screen} › {value}", "main")

        # A tour (S12.17): beside the page, kept while its links move around the app; ✕ closes it.
        page.evaluate(
            "state.locked = false; state.tour = 'uses'; location.hash = '#/budgets'"
        )
        page.wait_for_timeout(120)
        shot("tour-uses")
        page.click(".tour a[data-v='transactions']")
        page.wait_for_timeout(120)
        if (
            page.locator(".tour").count() != 1
            or page.evaluate("location.hash") != "#/transactions"
        ):
            errors.append("tour: following its link lost the tour or went elsewhere")
        shot("tour-uses-followed")
        split = page.locator(".tour-split").bounding_box()
        before = page.locator(".tour").bounding_box()["width"]
        page.mouse.move(split["x"] + split["width"] / 2, split["y"] + 200)
        page.mouse.down()
        page.mouse.move(split["x"] - 120, split["y"] + 200, steps=4)
        page.mouse.up()
        if page.locator(".tour").bounding_box()["width"] <= before:
            errors.append("tour: dragging its edge left didn't widen it")
        page.evaluate("state.tourDone = true; render()")
        page.wait_for_timeout(60)
        shot("tour-uses-done")
        page.click(".tour [data-act=tourclose]")
        page.wait_for_timeout(60)
        if page.locator(".tour").count():
            errors.append("tour: its ✕ left it open")
        page.evaluate("state.tourDone = false")

        # Typed inputs (S12.18): a key outside a field's kind is refused and marked; a value that
        # doesn't read is marked when the field is left, never while typed; a change clears it.
        page.evaluate("state.locked = false; location.hash = '#/transactions'")
        page.wait_for_timeout(120)
        page.click("summary:has-text('More filters')")
        least = page.locator("#f-at-least")

        def mark() -> str:
            return (
                least.get_attribute("title")
                if "bad" in least.get_attribute("class")
                else ""
            )

        least.press_sequentially("a")
        if least.input_value() != "" or mark() != "Digits and . only.":
            errors.append(
                "typed input: a letter in an amount wasn't refused and marked"
            )
        least.press_sequentially("1.2.3")
        if mark():
            errors.append(
                "typed input: a change didn't clear the mark, or it was checked as typed"
            )
        page.keyboard.press("Tab")
        if mark() != "Type an amount, such as 1234.50.":
            errors.append(
                "typed input: what doesn't read wasn't marked when the field was left"
            )
        shot("typed-input-marked")
        least.fill("5")
        if mark():
            errors.append("typed input: a change left the mark")
        page.evaluate("state.txFilters = 'below'; render()")
        page.wait_for_timeout(80)
        shot("transactions-at-most-below")
        if page.locator("#f-at-most.bad").count() != 1:
            errors.append("transactions: At most under At least isn't marked")
        page.evaluate("state.txFilters = null")

        # An action not open to the reader (S12.19.1): shown off, its reason its tooltip.
        page.evaluate("state.user = 'bob'; location.hash = '#/accounts'; render()")
        page.wait_for_timeout(120)
        off = page.locator(
            "table button[aria-disabled='true'][title='Only its owner shares it']"
        )
        if not off.count():
            errors.append(
                "accounts: Share on an account shared with the reader isn't shown off"
            )
        shot("accounts-share-off")
        page.evaluate("state.user = 'alice'; render()")

        page.evaluate("state.locked = true; location.hash = '#/settings'")
        page.wait_for_timeout(120)
        for section in index["settings"]:
            page.evaluate(f"state.settings = {section!r}; render()")
            page.wait_for_timeout(60)
            shot(f"settings-{section}")
            missing_help(f"settings › {section}", "main")

        page.evaluate("location.hash = '#/dashboard'")
        page.wait_for_timeout(120)
        for dialog in index["dialogs"]:
            page.evaluate(f"showDialog({dialog!r}, {{}})")
            page.wait_for_timeout(80)
            shot(f"dialog-{dialog}")
            missing_help(f"dialog {dialog}", ".dialog")
            page.evaluate("closeDialog()")

        # The MOCK pane (S12.9): beside the app, every screen and dialog in it as an address, a
        # dialog opened by its address and dropped from it when closed, a user and states set.
        page.evaluate("state.pane = false; location.hash = '#/budgets'")
        page.wait_for_timeout(120)
        page.click(".app .pill-mock")
        page.wait_for_timeout(120)
        hrefs = page.eval_on_selector_all(
            "#mock-pane a", "e => e.map(a => a.getAttribute('href'))"
        )
        for screen in index["screens"]:
            if f"#/{screen}" not in hrefs:
                errors.append(f"mock pane: no address for the screen {screen}")
        for dialog in index["dialogs"]:
            if not any(h.endswith(f"dialog={dialog}") for h in hrefs):
                errors.append(f"mock pane: no address for the dialog {dialog}")
        if page.locator("#root").bounding_box()["x"] <= 0:
            errors.append("mock pane: the app isn't moved over beside it")
        shot("mock-pane")
        page.evaluate(
            "location.hash = '#/settings/keys?as=bob&on=stale&dialog=verifyKey'"
        )
        page.wait_for_timeout(150)
        if (
            page.evaluate("[state.settings, state.user, state.stale].join()")
            != "keys,bob,true"
        ):
            errors.append(
                "mock pane: the address's section, user or state wasn't applied"
            )
        if page.locator(".dialog").count() != 1:
            errors.append("mock pane: dialog=verifyKey in the address opened no dialog")
        shot("mock-pane-address")
        page.evaluate("closeDialog()")
        if "dialog=" in page.evaluate("location.hash"):
            errors.append("mock pane: a dialog closed but stayed in the address")
        page.evaluate(
            "state.user = 'alice'; state.stale = false; state.pane = false; renderPane()"
        )
        # A guide's acronyms (S12.7.7): the first under a heading underlined, a later one plain
        # until hovered; hovering either opens its card, whose icon links to the document.
        page.evaluate("state.help = true; location.hash = '#/transactions'; render()")
        page.wait_for_timeout(120)
        card = page.locator(".help .term-tip:not([hidden])")
        for kind, selector in (
            ("first", "abbr.term:not(.quiet)"),
            ("later", "abbr.term.quiet"),
        ):
            term = page.locator(f".help {selector}").first
            if not term.count():
                errors.append(
                    f"term card: the Transactions guide has no {kind} use of a term"
                )
                continue
            name = term.get_attribute("data-term")
            term.hover()
            page.wait_for_timeout(100)
            link = card.locator("a.term-source[href^='https://'][target='_blank'] svg")
            if card.count() != 1:
                errors.append(f"term card: hovering the {kind} {name} opened no card")
            elif page.evaluate(f"!!TERMS[{name!r}][3]") and link.count() != 1:
                errors.append(f"term card: {name}'s card has no link to its document")
            shot(f"term-card-{kind}")
            page.mouse.move(5, 5)
            page.wait_for_timeout(250)
            if card.count():
                errors.append(
                    f"term card: {name}'s card stayed open after the pointer left"
                )

        # A guide's forms (S12.7.8), marked as its terms are: the Taxes guide's first form
        # opens a card whose icon links to the form's page on irs.gov.
        page.evaluate("location.hash = '#/taxes'; render()")
        page.wait_for_timeout(120)
        form = page.locator(".help abbr.term[data-term^='Form ']").first
        if not form.count():
            errors.append("forms: the Taxes guide marks no form")
        else:
            name = form.get_attribute("data-term")
            form.hover()
            page.wait_for_timeout(100)
            irs = "a.term-source[href^='https://www.irs.gov/forms-pubs/'][target='_blank'] svg"
            if card.count() != 1 or card.locator(irs).count() != 1:
                errors.append(
                    f"forms: hovering {name} opened no card linking to its page"
                )
            shot("form-card")
            page.mouse.move(5, 5)

        page.evaluate("state.theme = 'light'; location.hash = '#/dashboard'; render()")
        page.wait_for_timeout(120)
        shot("dashboard-light")
        browser.close()

    print(f"{shots} screenshots in {out}")
    if errors:
        print("\n".join(errors))
        return 1
    print("NO ERRORS")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1])))
