"""A tour in the browser (requirements S12.17), in headless Chromium: a category in use counts its
uses in its dialog, and Find them starts the Find uses tour (S12.2.6, S12.17.6), a pane beside
the page whose links move around the app while it stays; a step ticks itself as its uses clear;
it lasts through a reload, its width drags, and ✕ closes it."""

import pytest
from browser import made, months_back, signed_in, wait
from edits import change, make, remove, saved
from test_budgets import save_plan

pytestmark = pytest.mark.browser

TAB = "/ui/budgets/none/categories"
TOUR = "aside.tour"


def until(page, expr: str) -> None:
    """Poll an expression from outside the page (the app's CSP refuses a string evaluated
    inside it), for up to 30 s."""
    for _ in range(600):
        if page.evaluate(expr):
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"never true: {expr}")


def step(page, title: str):
    return page.locator(f"{TOUR} .tour-step", has_text=title)


def test_find_them_starts_a_tour_that_stays_while_its_links_move_around(browser, household):
    h = household
    cat = made(make(h.c, "Cat", name="Browser toys", kind="expense"))
    day = f"{months_back(1)}-12"
    made(make(h.c, "Txn", accountId=h.checking["id"], date=day, amount="-9.00",
              payee="Browser toy shop", categoryId=cat["id"]))  # fmt: skip
    rule = made(make(h.c, "Rule", payeeMatch="browser toy shop", categoryId=cat["id"]))
    b = made(make(h.c, "Bdgt", name="Browser toys budget", accountIds=[h.checking["id"]]))
    start = f"{months_back(2)}-01"
    made(save_plan(h.c, b, start, [{"categoryId": cat["id"], "amount": "20.00"}]))
    page, problems = signed_in(browser, h, TAB, 'button[aria-label="Edit Browser toys"]')

    # The dialog counts the uses, and Find them closes it and starts the tour.
    page.click('button[aria-label="Edit Browser toys"]')
    wait(page, ".dialog .in-use", problems)
    until(page, "document.querySelector('.dialog .in-use').textContent.includes('3 uses')")
    assert "In use: 3 uses you can see." in " ".join(page.inner_text(".dialog .in-use").split())
    page.click('.dialog button:has-text("Find them")')
    wait(page, ".dialog", problems, state="detached")
    wait(page, f"{TOUR} .tour-step", problems)
    assert page.inner_text(f"{TOUR} h2") == "Find uses of Browser toys"
    assert "3 of the 3 uses you can see are left" in " ".join(page.inner_text(TOUR).split())
    titles = page.locator(f"{TOUR} .tour-step h3").all_inner_texts()
    assert [t.split("\n")[0].strip("✓ ") for t in titles] == [
        "Transactions and their parts",
        "Rules",
        "Plan lines",
    ]

    # Its links go to each use, and the tour stays as it was, the link to here marked.
    page.click(f"{TOUR} a:has-text('1 transaction filed under it')")
    page.wait_for_url(f"**/ui/transactions?category={cat['id']}")
    wait(page, 'tr:has-text("Browser toy shop") .row-tool', problems)
    assert page.locator(f"{TOUR} a.here").inner_text() == "1 transaction filed under it"
    page.click(f"{TOUR} a:has-text('Browser toys budget')")
    page.wait_for_url(f"**/ui/budgets/{b['id']}/month?month={start[:7]}")
    until(page, f"document.querySelector('#f-month')?.value === {start[:7]!r}")
    page.click(f"{TOUR} a:has-text('“browser toy shop”')")
    page.wait_for_url(f"**/ui/transactions/rules/{rule['id']}")
    wait(page, ".rule-pane #f-payee-contains", problems)

    # A use cleared ticks its step, and the count falls.
    page.select_option(".rule-pane #f-category", h.cats["Food › Groceries"])
    page.click(".rule-pane .toolbar button.primary")
    wait(page, f"{TOUR} .tour-step.done:has-text('Rules')", problems)
    assert "2 of the 3 uses you can see are left" in " ".join(page.inner_text(TOUR).split())

    # Through a reload, as it was; its edge drags it wider; ✕ closes it, for good.
    page.reload()
    wait(page, f"{TOUR} .tour-step.done:has-text('Rules')", problems)
    before = page.locator(TOUR).bounding_box()["width"]
    edge = page.locator(f"{TOUR} .resizer").bounding_box()
    page.mouse.move(edge["x"] + edge["width"] / 2, edge["y"] + 200)
    page.mouse.down()
    page.mouse.move(edge["x"] - 80, edge["y"] + 200, steps=4)
    page.mouse.up()
    assert page.locator(TOUR).bounding_box()["width"] > before
    page.click(f"{TOUR} button[aria-label='Close the tour']")
    wait(page, TOUR, problems, state="detached")
    page.reload()
    wait(page, ".rule-pane #f-payee-contains", problems)
    assert page.locator(TOUR).count() == 0

    saved(remove(h.c, "Rule", next(x for x in h.c.get("/ui/api/rules").json()["items"]
                                    if x["id"] == rule["id"])))  # fmt: skip
    assert problems == []
    page.close()


def test_a_tour_says_when_nothing_is_left(browser, household):
    """S12.17.6: with nothing the reader can see left, it says so, and offers the category's
    dialog to delete it."""
    h = household
    cat = made(make(h.c, "Cat", name="Browser kites", kind="expense"))
    t = made(make(h.c, "Txn", accountId=h.checking["id"], date=f"{months_back(1)}-13",
                  amount="-4.00", payee="Browser kite shop", categoryId=cat["id"]))  # fmt: skip
    page, problems = signed_in(browser, h, TAB, 'button[aria-label="Edit Browser kites"]')
    page.click('button[aria-label="Edit Browser kites"]')
    wait(page, '.dialog button:has-text("Find them")', problems)
    page.click('.dialog button:has-text("Find them")')
    wait(page, f"{TOUR} .tour-step", problems)
    saved(change(h.c, "Txn", h.c.get(f"/ui/api/transactions/{t['id']}").json(), categoryId=None))
    wait(page, f"{TOUR} .tour-step.done", problems)
    assert "Nothing you can see uses Browser kites now." in page.inner_text(TOUR)
    page.click(f"{TOUR} button:has-text('open Browser kites')")
    wait(page, '.dialog button:has-text("Delete")', problems)
    page.click('.dialog button:has-text("Delete")')
    page.click('.dialog-ask-box button:has-text("Yes, delete")')
    wait(page, ".dialog", problems, state="detached")
    wait(page, f"{TOUR}:has-text('The category is gone')", problems)
    page.click(f"{TOUR} button[aria-label='Close the tour']")
    assert problems == []
    page.close()
