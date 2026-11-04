"""The money that came into an account from outside or left it, day by day (CR3-28): what the
series, returns and benchmark read as contributed. Each kind of account is checked on its own
days and amounts, and the window's edges: `first` is left out, `last` is counted."""

import datetime as dt
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import make, saved, sell, terms
from test_accounts import add, new_account

from moolakata import valuation

d = dt.date


@pytest.fixture
def alice(server):
    make_user(server, "alice")
    return sign_in(server, "alice")


def flows(server, account_id, first, last, investing=True):
    from moolakata.store.entities.accounts import Account
    from moolakata.store.repos import ledger as repo

    with server.db.read(unscoped="test") as s:
        led = repo.load(s, s.get(Account, account_id))
        return valuation.flows(s, led, investing, first, last)


def test_a_loan_owes_its_principal_from_its_start_and_takes_its_payments_and_draws(server, alice):
    loan = new_account(alice, name="HELOC", type="mortgage")
    saved(terms(alice, loan["id"], principal="300000", startDate="2026-01-01", termMonths=360,
                rate="6"))  # fmt: skip
    add(alice, loan["id"], "2000.00", "2026-07-01", kind="deposit")
    add(alice, loan["id"], "-500.00", "2026-08-01", kind="withdrawal")
    year = flows(server, loan["id"], d(2025, 12, 31), d(2026, 12, 31))
    # The days before the first payment recorded count as paid as scheduled (S1.9.3): each
    # assumed payment is money in, as a recorded one is.
    assumed = {d(2026, m, 1): D("1798.65") for m in range(2, 7)}
    assert year == {d(2026, 1, 1): D("-300000.00"), **assumed, d(2026, 7, 1): D("2000.00"),
                    d(2026, 8, 1): D("-500.00")}  # fmt: skip
    # The window's first day is left out and its last counted.
    assert flows(server, loan["id"], d(2026, 1, 1), d(2026, 7, 1)) == {
        **assumed,
        d(2026, 7, 1): D("2000.00"),
    }
    assert flows(server, loan["id"], d(2026, 1, 1), d(2026, 6, 30)) == assumed
    assert flows(server, loan["id"], d(2026, 6, 1), d(2026, 6, 30)) == {}


def test_a_loan_without_terms_has_no_flows(server, alice):
    loan = new_account(alice, name="Car loan", type="auto-loan")
    add(alice, loan["id"], "400.00", "2026-07-01", kind="deposit")
    assert flows(server, loan["id"], d(2025, 12, 31), d(2026, 12, 31)) == {}


def test_an_item_comes_in_at_its_worth_and_leaves_at_what_its_sale_brought(server, alice):
    coll = new_account(alice, name="Collectables", type="collectables")
    coin = make(alice, "Item", accountId=coll["id"], name="Coin", acquiredOn="2026-02-01",
                costBasis="1000").json()  # fmt: skip
    saved(sell(alice, coin["id"], "2026-05-01", "2100", "100"))
    got = flows(server, coll["id"], d(2025, 12, 31), d(2026, 12, 31))
    assert got == {d(2026, 2, 1): D("1000"), d(2026, 5, 1): D("-2000")}
    assert flows(server, coll["id"], d(2026, 2, 1), d(2026, 4, 30)) == {}


def test_shares_moved_count_at_the_series_price_in_and_out(server, alice):
    a = new_account(alice, name="Brokerage", type="brokerage", openingBalance="0.00",
                    openingDate="2026-01-01")  # fmt: skip
    add(alice, a["id"], "0.00", "2026-01-05", kind="transfer-in", symbol="VXUS", quantity="7",
        costBasis="400")  # fmt: skip
    add(alice, a["id"], "10000.00", "2026-01-02", kind="deposit")
    add(alice, a["id"], "-10000.00", "2026-01-10", kind="buy", symbol="VTI", quantity="100",
        price="100")  # fmt: skip
    add(alice, a["id"], "0.00", "2026-06-01", kind="transfer-in", symbol="VTI", quantity="50",
        costBasis="4000")  # fmt: skip
    add(alice, a["id"], "-12000.00", "2026-06-15", kind="buy", symbol="VTI", quantity="100",
        price="120")  # fmt: skip
    add(alice, a["id"], "0.00", "2026-07-01", kind="transfer-out", symbol="VTI", quantity="-30")
    got = flows(server, a["id"], d(2025, 12, 31), d(2026, 12, 31))
    # VXUS moved in before it had any price: nothing, in the flows as in the series.
    assert got == {d(2026, 1, 2): D("10000.00"), d(2026, 6, 1): D("5000.00"),
                   d(2026, 7, 1): D("-3600.00")}  # fmt: skip
    # A move on the window's first day is left out, one on its last counted.
    assert flows(server, a["id"], d(2026, 6, 1), d(2026, 7, 1)) == {d(2026, 7, 1): D("-3600.00")}
    assert flows(server, a["id"], d(2026, 5, 31), d(2026, 6, 1)) == {d(2026, 6, 1): D("5000.00")}
    # Not investing: the cash in and out only.
    assert flows(server, a["id"], d(2025, 12, 31), d(2026, 12, 31), investing=False) == {
        d(2026, 1, 2): D("10000.00")
    }
