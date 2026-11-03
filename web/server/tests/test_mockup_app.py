"""The generated mockup (requirements S12.9) in headless Chromium, opened from disk: every
screen, tab and Settings section for each sample user, and the MOCK pill's dialogs, open with
no page or console error, and nothing is requested from anywhere but the page and the files
beside it."""

import pytest
from devapp import api_items

from moolakata import paths

pytestmark = pytest.mark.browser

PAGE = paths.ROOT / "docs" / "mockups" / "MoolaKata-app.html"
LOCAL = ("file:", "blob:", "data:")


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def open_as(browser, user: str):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    # The first visit only: the MOCK pill's switch of user reloads the page.
    key = "'mk-mockup-user'"
    ctx.add_init_script(f"localStorage.getItem({key}) || localStorage.setItem({key}, {user!r})")
    page = ctx.new_page()
    page.problems = []
    page.on("pageerror", lambda e: page.problems.append(f"page error on {page.url}: {e}"))
    page.on(
        "console",
        lambda m: m.type == "error" and page.problems.append(f"console on {page.url}: {m.text}"),
    )
    page.on(
        "request",
        lambda r: not r.url.startswith(LOCAL) and page.problems.append(f"sent {r.url}"),
    )
    # A file that is missing; not an image a reload cut short.
    page.on(
        "requestfailed",
        lambda r: r.failure != "net::ERR_ABORTED" and page.problems.append(f"failed {r.url}"),
    )
    page.goto(PAGE.as_uri() + "#/ui/")
    page.wait_for_selector(".side")
    return ctx, page


def show(page, path: str) -> None:
    page.goto(PAGE.as_uri() + "#" + path)
    page.wait_for_selector(".content > *")
    page.wait_for_timeout(300)
    assert not page.is_visible("text=was not recorded"), f"{path} asked for an unrecorded answer"


@pytest.mark.parametrize("user", ["alice", "bob", "admin"])
def test_every_screen_opens(browser, user):
    assert PAGE.exists(), "run web/dev.sh mockup"
    ctx, page = open_as(browser, user)
    nav = page.eval_on_selector_all(".side nav a", "(as) => as.map((a) => a.getAttribute('href'))")
    accounts = api_items(page, "/ui/api/accounts")
    ports = api_items(page, "/ui/api/portfolios")
    for path in [*nav, "/ui/profile"]:
        show(page, path)
    for a in accounts:
        show(page, f"/ui/accounts/{a['id']}")
        tabs = page.eval_on_selector_all(
            ".content .tabs a", "(as) => as.map((a) => a.getAttribute('href'))"
        )
        for t in tabs:
            show(page, t)
    for p in ports:
        for tab in ("performance", "holdings"):
            show(page, f"/ui/portfolios/{p['id']}/{tab}")
    if "/ui/settings" in nav:
        for s in ("general", "sessions", "passwords", "prices", "imports", "backups", "keys"):
            show(page, f"/ui/settings/{s}")
    ctx.close()
    assert page.problems == []


def test_the_mock_pill_opens_dialogs_and_switches_users(browser):
    ctx, page = open_as(browser, "alice")
    for label in ("New account", "Import", "Add a transaction", "New portfolio", "New user"):
        page.click(".pill-mock")
        page.get_by_role("menuitem", name=label).click()
        # Focus in the dialog: it listens for Escape from then on.
        page.wait_for_selector(".dialog :focus")
        page.keyboard.press("Escape")
        page.wait_for_selector(".dialog", state="detached")
    page.click(".pill-mock")
    page.get_by_role("menuitem", name="Bob Griffin").click()
    page.wait_for_selector(".user-text >> text=bob")
    page.click(".pill-mock")
    page.get_by_role("menuitem", name="Prices stale").click()
    page.wait_for_selector(".price-status .dot.stale")
    url = page.url
    ctx.close()
    assert page.problems == []
    # The address alone brings them back: Chromium can reload a page opened from disk with its
    # storage empty.
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.goto(url)
    page.wait_for_selector(".user-text >> text=bob")
    page.wait_for_selector(".price-status .dot.stale")
    ctx.close()
