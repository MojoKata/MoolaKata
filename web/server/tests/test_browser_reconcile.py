"""The Reconcile tab as the account page shows it, in headless Chromium (requirements S1.11,
CR3-17): every account kept from files or statements has one, retirement, plan and exchange
accounts among them, and a plan's statement values and holdings are checked there; cash on
hand and a loan have none. The tab follows the account's own `reconcilable`, as the server
sends it."""

import pytest
from browser import Household, made, signed_in
from edits import make
from test_brokerage import EMPOWER
from test_reading import text_pdf
from test_statements import _import

pytestmark = pytest.mark.browser

TABS = "[role=tablist]"


def account(h: Household, name: str, kind: str, **more) -> str:
    return made(make(h.c, "Acct", name=name, type=kind, **more))["id"]


def tabs(browser, h: Household, acct: str) -> list[str]:
    page, problems = signed_in(browser, h, f"/ui/accounts/{acct}", f"{TABS} >> text=Overview")
    got = [t.strip() for t in page.locator(f"{TABS} a").all_inner_texts()]
    assert problems == []
    page.close()
    return got


@pytest.mark.parametrize("kind", ["401k", "ira", "crypto-exchange"])
def test_a_retirement_or_exchange_account_has_a_reconcile_tab(browser, household, kind):
    acct = account(household, f"Reconciled {kind}", kind)
    assert "Reconcile" in tabs(browser, household, acct)


@pytest.mark.parametrize("kind", ["cash", "auto-loan"])
def test_cash_on_hand_and_a_loan_have_none(browser, household, kind):
    acct = account(household, f"Unreconciled {kind}", kind)
    assert "Reconcile" not in tabs(browser, household, acct)


def test_a_plans_statement_values_show_on_its_reconcile_tab(browser, household):
    h = household
    acct = account(h, "Acme 401(k) checked", "401k", institution="Empower")
    review = _import(h.c, acct, text_pdf(EMPOWER.splitlines()))["result"]
    body = {
        "periodStart": review["periodStart"],
        "periodEnd": review["periodEnd"],
        "endingValue": review["summary"]["ending"],
        "positions": [
            {k: p[k] for k in ("label", "quantity", "price", "marketValue")}
            for p in review["positions"]
        ],
        "rows": [],
    }
    r = h.c.post(f"/ui/api/imports/{review['uploadId']}/brokerage", json=body)
    assert r.status_code == 200, r.text
    page, problems = signed_in(
        browser, h, f"/ui/accounts/{acct}/reconcile", "h3:has-text('Statement Values')"
    )
    card = page.locator(".card", has=page.locator("h3:has-text('Statement Values')"))
    assert "93,710.55" in card.inner_text()
    assert problems == []
    page.close()
