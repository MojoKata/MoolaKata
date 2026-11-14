"""The page's state shown briefly (requirements S12.19.2–4), driven in headless Chromium: a
scenario budget's notice with its actions, a month reviewed as a pill whose tooltip says by
whom and when, and a reviewed month changed since as a notice of what changed."""

import re

import pytest
from browser import made, months_back, signed_in, wait
from edits import make, remove

pytestmark = pytest.mark.browser


def test_a_scenario_says_so_in_one_line_with_its_actions(browser, household):
    h = household
    r = h.c.post(f"/ui/api/budgets/{h.budget['id']}/copy",
                 json={"name": "State scenario", "method": "tracking"})  # fmt: skip
    assert r.status_code == 201, r.text
    copy = r.json()
    try:
        page, problems = signed_in(
            browser, h, f"/ui/budgets/{copy['id']}/month", ".notice.attention"
        )
        notice = page.locator(".notice.attention").first
        assert notice.locator(".grow").inner_text() == "Scenario · tracking"
        names = notice.locator(".attention-actions > *").all_inner_texts()
        assert [n.strip() for n in names] == ["Make Active", "Compare"]
        assert problems == []
        page.close()
    finally:
        made(remove(h.c, "Bdgt", h.c.get(f"/ui/api/budgets/{copy['id']}").json()))


def test_a_reviewed_month_is_a_pill_saying_by_whom(browser, household):
    h = household
    month = f"{months_back(1)}-01"
    r = h.c.post(f"/ui/api/budgets/{h.budget['id']}/review", json={"month": month})
    assert r.status_code == 200, r.text
    page, problems = signed_in(
        browser, h, f"/ui/budgets/{h.budget['id']}/review", "#f-month-reviewed"
    )
    page.select_option("#f-month-reviewed", months_back(1))
    pill = page.locator(".pill.ok:has-text('Reviewed')")
    wait(page, ".pill.ok:has-text('Reviewed')", problems)
    assert pill.get_attribute("tabindex") == "0"
    assert pill.get_attribute("data-tip").startswith("Reviewed ")
    assert pill.get_attribute("data-tip").endswith(" by Admin")
    assert problems == []
    page.close()


def test_uncategorised_transactions_are_a_pill_that_opens_them(browser, household):
    """S12.19.3: the month's uncategorised count is a pill, what it means its tooltip, and it
    opens Transactions filtered to them."""
    h = household
    txn = made(make(h.c, "Txn", accountId=h.checking["id"], date=f"{months_back(0)}-02",
                    amount="-12.34", payee="Pill Corner"))  # fmt: skip
    try:
        page, problems = signed_in(
            browser, h, f"/ui/budgets/{h.budget['id']}/month", "a.pill:has-text('uncategorised')"
        )
        pill = page.locator("a.pill:has-text('uncategorised')")
        assert pill.get_attribute("href") == "/ui/transactions?category=none"
        assert pill.get_attribute("data-tip").startswith("Transactions without a category")
        assert re.fullmatch(r"\d+ uncategorised", pill.inner_text().strip())
        assert problems == []
        page.close()
    finally:
        made(remove(h.c, "Txn", txn))
