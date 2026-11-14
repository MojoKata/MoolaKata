"""Warnings that show by their field only while they apply (requirements R3.12), in headless
Chromium: a donation's acknowledgement from $250 (S8.9), the line under lots moved in while
one has no cost (S2.2), and a gift plan's birth year for a different person by the name of one
already here (S10.10.3). Each dialog is left unsaved. Each condition's every data point is in
the unit tests (`web/ui/tests/warnings.test.js`); these see each warning come and go."""

import pytest
from browser import signed_in, wait

pytestmark = pytest.mark.browser


def discard(page, problems: list) -> None:
    """Close the dialog, letting what was typed go."""
    page.click(".dialog-x")
    page.click('.dialog-ask-buttons button:has-text("Discard")')
    wait(page, ".dialog", problems, state="detached")


def typed(page, selector: str, value: str, problems: list) -> None:
    """A value put in a field and the field left, once the page has settled on it."""
    page.fill(selector, value)
    page.locator(selector).blur()
    wait(page, selector, problems)


def test_a_donations_acknowledgement_is_asked_for_from_250(browser, household):
    """S8.9: Acknowledgement received says one is needed at $250, not at $249.99."""
    page, problems = signed_in(
        browser, household, "/ui/giving/donations", 'button:has-text("Record a Donation")'
    )
    page.click('button:has-text("Record a Donation")')
    amount = ".dialog #f-amount"
    hint = '.dialog .list-item:has-text("Acknowledgement received") .small.dim'
    wait(page, amount, problems)
    assert page.locator(hint).count() == 0, "nothing typed, nothing needed"
    typed(page, amount, "249.99", problems)
    assert page.input_value(amount) == "249.99"
    assert page.locator(hint).count() == 0
    typed(page, amount, "250", problems)
    assert page.input_value(amount) == "250.00"
    wait(page, f'{hint}:text-is("A written acknowledgement is needed.")', problems)
    typed(page, amount, "249.99", problems)
    wait(page, hint, problems, state="detached")
    discard(page, problems)
    assert problems == []
    page.close()


def test_lots_moved_in_say_a_cost_is_missing_until_it_is_typed(browser, household):
    """S2.2: none typed, the line says they arrive as one lot; a lot added without a cost is
    marked basis missing; its cost typed, the line goes."""
    h = household
    row = 'tr:has-text("transfer-in VTI") .row-tool'
    page, problems = signed_in(
        browser, h, f"/ui/accounts/{h.extra['brokerage']['id']}/transactions", row
    )
    page.click(row)
    line = ".dialog #f-transfer-lots .toolbar .small.dim"
    wait(page, f'{line}:has-text("None typed")', problems)
    assert page.inner_text(line) == (
        "None typed: one lot whose day bought is missing, its term unknown until you add it."
    )
    page.click('.dialog button:has-text("Add a Lot")')
    wait(page, f'{line}:text-is("Marked basis missing until you add it.")', problems)
    cost = '.dialog input[aria-label="Lot 1: cost basis"]'
    typed(page, cost, "2400.00", problems)
    wait(page, f'{line}:has-text("missing")', problems, state="detached")
    assert page.inner_text(line) == ""
    typed(page, cost, "", problems)
    wait(page, f'{line}:text-is("Marked basis missing until you add it.")', problems)
    discard(page, problems)
    assert problems == []
    page.close()


def test_a_different_person_by_a_name_already_here_needs_a_birth_year(browser, household):
    """S10.10.3: a new plan by the name of one already here shows them; A Different Person
    warns by Birthday that the birth year must differ from theirs; using them instead, the
    warning goes."""
    page, problems = signed_in(
        browser, household, "/ui/gifts/people", 'button:has-text("Add a Gift Plan")'
    )
    page.click('button:has-text("Add a Gift Plan")')
    wait(page, ".dialog #f-name", problems)
    hint = ".dialog .field:has(#f-birthday) .hint"
    page.fill(".dialog #f-name", "Emma Griffin")
    page.select_option(".dialog #f-sex", "female")
    page.click(".dialog footer button.primary")
    wait(page, '.dialog .notice:has-text("Emma Griffin is already here")', problems)
    assert page.locator(hint).count() == 0, "not yet marked a different person"
    page.click('.dialog button:has-text("A Different Person")')
    wait(page, f'{hint}:text-is("A birth year that differs from theirs.")', problems)
    page.click('.dialog button:has-text("Use Emma Griffin")')
    wait(page, hint, problems, state="detached")
    discard(page, problems)
    # The save refused for the name already here is the answer the test brought about.
    assert [p for p in problems if "/ui/api/save" not in p] == []
    page.close()
