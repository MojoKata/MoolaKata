"""The screens built on an account's parts (the values, taxes and options walk, 4.3): a
portfolio's Holdings shows a loan and an item on rows of their own and totals the portfolio's
value; a projection names what it leaves out; a loan's screen offers to pair a bank debit with
a payment already recorded, and its payment dialog finds the bank's half already there. The
records made are taken away again, so the shared household's other figures stay as they were.
"""

import datetime as dt
import json
import re
from decimal import Decimal

import pytest
from browser import made, signed_in, wait
from edits import change, loan_payment, make, remove, saved, terms

pytestmark = pytest.mark.browser


def _money(text: str) -> Decimal:
    t = text.replace("−", "-").replace(",", "").replace("$", "").strip()
    m = re.search(r"-?\d+(\.\d+)?", t)
    assert m, text
    return Decimal(m.group(0))


def _drop(c, kind: str, path: str) -> None:
    made(remove(c, kind, c.get("/ui/api" + path).json(), confirm=True))


def test_holdings_and_a_projection_show_loans_and_items(browser, household):
    h = household
    bank = made(make(h.c, "Acct", name="Figures checking", type="checking", mask="7101"))
    made(make(h.c, "Txn", accountId=bank["id"], date="2026-01-05", amount="5000.00",
              kind="deposit"))  # fmt: skip
    loan = made(make(h.c, "Acct", name="Figures mortgage", type="mortgage", mask="7102"))
    saved(terms(h.c, loan["id"], principal="200000", startDate="2026-01-01", termMonths=360,
                rate="6"))  # fmt: skip
    homes = made(make(h.c, "Acct", name="Figures home", type="real-estate"))
    made(make(h.c, "Item", accountId=homes["id"], name="27 Oak Ln", acquiredOn="2024-01-10",
              costBasis="400000", valuation="valuations"))  # fmt: skip
    ids = [bank["id"], loan["id"], homes["id"]]
    p = made(make(h.c, "Portf", name="Figures", accountIds=ids))
    pr = made(make(h.c, "Prjct", name="Figures grow", goal="savings",
                   builtOn={"kind": "portfolio", "id": p["id"]},
                   inputs={"target": 50000, "targetDate": "2030-01-01"}))  # fmt: skip
    try:
        # Read exactly: a float parse of $207,036.40 is 207036.3999… (money is a JSON number).
        api = json.loads(
            h.c.get(f"/ui/api/portfolios/{p['id']}/holdings").text, parse_float=Decimal
        )
        page, problems = signed_in(browser, h, f"/ui/portfolios/{p['id']}/holdings", "table.t")
        table = page.locator("table.t")
        text = table.inner_text()
        assert "Owed on the loan" in text and "Figures mortgage" in text
        assert "27 Oak Ln" in text and "Item" in text
        total = table.locator('tfoot tr:has-text("Total") td.num').first.inner_text()
        assert _money(total) == Decimal(api["total"])
        page.goto(h.base + f"/ui/projections/{pr['id']}")
        wait(page, 'p:has-text("Left out:")', problems)
        left = page.locator('p:has-text("Left out:")').inner_text()
        assert "Figures mortgage" in left and "27 Oak Ln" in left
        assert problems == []
        page.close()
    finally:
        _drop(h.c, "Prjct", f"/projections/{pr['id']}")
        _drop(h.c, "Portf", f"/portfolios/{p['id']}")
        for a in ids:
            _drop(h.c, "Acct", f"/accounts/{a}")


def test_a_loans_screen_pairs_and_its_dialog_finds_the_bank_half(browser, household):
    h = household
    bank = made(make(h.c, "Acct", name="Pairing checking", type="checking", mask="7201"))
    made(make(h.c, "Txn", accountId=bank["id"], date="2026-01-05", amount="9000.00",
              kind="deposit"))  # fmt: skip
    loan = made(make(h.c, "Acct", name="Pairing mortgage", type="mortgage", mask="7202"))
    saved(terms(h.c, loan["id"], principal="200000", startDate="2026-01-01", termMonths=360,
                rate="6"))  # fmt: skip
    try:
        # A payment recorded on the loan alone, its debit in the bank unpaired from it.
        today = dt.date.today()
        paid, seen = today - dt.timedelta(days=12), today - dt.timedelta(days=11)
        assert loan_payment(h.c, loan["id"], paid.isoformat(), "1199.10").status_code == 200
        debit = made(make(h.c, "Txn", accountId=bank["id"], date=seen.isoformat(),
                          amount="-1199.10", payee="ROCKET MORTGAGE"))  # fmt: skip
        now = h.c.get(f"/ui/api/transactions/{debit['id']}").json()
        if now.get("transferId"):
            made(change(h.c, "Txn", now, transferWithId=None))
        page, problems = signed_in(browser, h, f"/ui/accounts/{loan['id']}", "main .card")
        wait(page, '.card:has(h3:text("Looks like a payment"))', problems)
        card = page.locator('.card:has(h3:text("Looks like a payment"))')
        assert "pair with the payment of" in card.inner_text()
        card.locator('button:text("Pair")').click()
        wait(page, '.toast:has-text("Paired")', problems)
        rows = [r for r in h.c.get("/ui/api/transactions", params={"pageSize": 1000}).json()[
            "items"] if r["accountId"] == loan["id"]]  # fmt: skip
        assert len(rows) == 1 and rows[0]["transferId"] == debit["id"]
        # A second debit already in the bank: the dialog finds it and pairs with it.
        later = today - dt.timedelta(days=2)
        second = made(make(h.c, "Txn", accountId=bank["id"], date=later.isoformat(),
                           amount="-1199.10", payee="ROCKET MORTGAGE"))  # fmt: skip
        page.get_by_role("button", name="Record a payment").click()
        dialog = page.locator(".dialog")
        dialog.locator("#f-paid-on").fill(later.isoformat())
        dialog.locator("#f-amount").fill("1199.10")
        dialog.locator("#f-from-account").select_option(bank["id"])
        wait(page, '.dialog .notice:has-text("already holds this payment")', problems)
        assert problems == []
        page.close()
        del second
    finally:
        _drop(h.c, "Acct", f"/accounts/{loan['id']}")
        _drop(h.c, "Acct", f"/accounts/{bank['id']}")


def test_an_uncovered_call_on_its_own_risks_without_limit(browser, household):
    """CR3-6: an option outside a strategy counts as its shape: an uncovered short call makes
    the account's capital at risk unlimited; the trade's return is on its capital required."""
    from edits import option_trade

    h = household
    a = made(make(h.c, "Acct", name="Calls only", type="brokerage", mask="7301"))
    today = dt.date.today()
    opened = (today - dt.timedelta(days=5)).isoformat()
    expiry = (today + dt.timedelta(days=40)).isoformat()
    r = option_trade(h.c, a["id"], opened, "sell-to-open", "CRMX", "call", "120", expiry, 1, "2.10")
    assert r.status_code == 200, r.text
    try:
        page, problems = signed_in(browser, h, f"/ui/accounts/{a['id']}", "main .card")
        wait(page, '[data-help="capital-at-risk"]', problems)
        line = page.locator('.list-item:has([data-help="capital-at-risk"])').inner_text()
        assert "unlimited" in line
        page.goto(h.base + "/ui/positions/trades")
        wait(page, 'th:text("Capital required")', problems)
        assert problems == []
        page.close()
    finally:
        _drop(h.c, "Acct", f"/accounts/{a['id']}")
