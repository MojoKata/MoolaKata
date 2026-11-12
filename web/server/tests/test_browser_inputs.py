"""Typed inputs driven in headless Chromium (requirements S12.18, R3.11): a key outside a
field's kind refused and marked; text put in whole cleaned; a value checked when the field is
left, never while typed, and any change clearing the mark; Transactions' amount bounds taken
when left, At most under At least marked with the list as it was; a merger's cash asked of
every merger, Min filling in $0.00; a gift's link a web address."""

import pytest
from browser import made, months_back, signed_in, wait
from edits import create, make, saved

pytestmark = pytest.mark.browser

LIST = "table tbody tr"


def amounts(page) -> list[str]:
    return sorted(page.locator(f"{LIST} td.num").all_inner_texts())


def test_the_filters_amount_bounds_are_taken_when_left(browser, household):
    h = household
    acct = made(make(h.c, "Acct", name="Bounded", type="checking"))
    for amount in ("-3.00", "-7.00", "-50.00"):
        saved(create(h.c, "Txn", accountId=acct["id"], date=f"{months_back(1)}-03",
                     amount=amount, payee="Bound test"))  # fmt: skip
    page, problems = signed_in(browser, h, "/ui/transactions", "#f-search")
    page.fill("#f-search", "Bound test")
    wait(page, f'{LIST}:has-text("Bound test")', problems)
    page.click("summary:has-text('More filters')")
    least, most = page.locator("#f-min"), page.locator("#f-max")
    assert [least.get_attribute("placeholder"), most.get_attribute("placeholder")] == [
        "any",
        "any",
    ], "a blank bound is any (R3.11)"
    # A minus is no size's character: refused as typed, and marked with what it takes.
    least.press_sequentially("-")
    assert least.input_value() == ""
    assert least.get_attribute("data-tip") == "Digits and . only."
    # Typed, nothing changes until the field is left; then the list is bounded.
    with page.expect_response(lambda r: "/transactions?" in r.url and "min=5" in r.url):
        least.press_sequentially("5")
        assert least.get_attribute("data-tip") is None, "a change clears the mark"
        least.press("Tab")
    wait(page, f"{LIST}:not(:has-text('$3.00'))", problems)
    # At most under At least is marked when left, and the list stays as it was.
    most.fill("4")
    most.press("Enter")
    assert most.get_attribute("data-tip") == "Below At least."
    assert "max=4" not in page.evaluate("location.href")
    most.fill("10")
    assert most.get_attribute("data-tip") is None
    with page.expect_response(lambda r: "max=10" in r.url):
        most.press("Enter")
    wait(page, f'{LIST}:has-text("Bound test")', problems)
    assert page.locator(f'{LIST}:has-text("Bound test")').count() == 1, "only the $7.00 one"
    # A value that doesn't read is marked when left, and not taken.
    least.fill("1.2.3")
    least.press("Tab")
    assert least.get_attribute("data-tip") == "Type an amount, such as 1234.50."
    assert page.locator(f'{LIST}:has-text("Bound test")').count() == 1
    # Clearing the filters empties the bounds, their marks gone with what they held.
    with page.expect_response(lambda r: "/transactions?" in r.url and "max=" not in r.url):
        page.get_by_role("button", name="Clear the filters").click()
    assert [least.input_value(), most.input_value()] == ["", ""]
    assert least.get_attribute("data-tip") is None
    assert problems == []
    page.close()


def test_a_mergers_cash_is_asked_and_min_fills_in_none(browser, household):
    # S2.4.5, R3.11: blank is refused at Save, never read as no cash; Min fills in $0.00.
    h = household
    acct = made(make(h.c, "Acct", name="Merged", type="brokerage"))
    saved(create(h.c, "Txn", accountId=acct["id"], date=f"{months_back(2)}-03", kind="buy",
                 symbol="TARGCO", quantity="10", price="10", amount="-100.00"))  # fmt: skip
    page, problems = signed_in(
        browser, h, "/ui/positions/open", 'button:has-text("Corporate action")'
    )
    page.click('button:has-text("Corporate action")')
    wait(page, "#f-holding", problems)
    page.select_option("#f-holding", label="TARGCO in Merged")
    page.select_option("#f-action", "merger")
    wait(page, "#f-cash-for-each-share-held", problems)
    cash = page.locator("#f-cash-for-each-share-held")
    assert cash.get_attribute("placeholder") in (None, ""), "no value a blank seems to get"
    page.fill("#f-new-symbol", "ACQCO")
    page.fill("#f-new-shares-for-each-held", "0.5")
    page.click(".dialog footer button.primary")
    wait(page, "#f-cash-for-each-share-held-err", problems)
    said = page.locator("#f-cash-for-each-share-held-err").inner_text()
    assert said == "The cash for each share held: 0 for a merger paid all in shares."
    page.get_by_role("button", name="Min: $0.00").click()
    assert cash.input_value() == "0.00"
    assert page.get_by_role("button", name="Min: $0.00").is_disabled()
    assert page.locator("#f-a-new-shares-price-that-day").count() == 0, "no cash, no price"
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    held = h.c.get(f"/ui/api/accounts/{acct['id']}/holdings").json()["holdings"]
    assert [x["symbol"] for x in held] == ["ACQCO"]
    assert [x for x in problems if not x.startswith("422")] == []
    page.close()


def test_a_gifts_link_is_marked_when_left_and_refused_at_save(browser, household):
    # S7.8.1: a web address; one with a space can't be typed, one without a scheme is marked
    # when the field is left, and refused at Save under the field.
    h = household
    page, problems = signed_in(browser, h, "/ui/gifts/list", 'button:has-text("Add a gift")')
    page.click('button:has-text("Add a gift")')
    wait(page, ".dialog #f-link", problems)
    link = page.locator("#f-link")
    assert link.get_attribute("placeholder") == "ex: https://example.com/item"
    link.press_sequentially("shop example")
    assert link.input_value() == "shopexample", "a space isn't a web address's"
    link.fill("shop.example.com/item")
    assert link.get_attribute("data-tip") is None, "not while typed"
    link.press("Tab")
    assert link.get_attribute("data-tip") == "A web address starting with https:// or http://."
    link.fill("https://shop.example.com/item")
    link.press("Tab")
    assert link.get_attribute("data-tip") is None
    assert problems == []
    page.close()
