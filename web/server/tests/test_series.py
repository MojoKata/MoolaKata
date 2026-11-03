"""An account's value day by day for its chart (`valuation.series`), for the kinds valued
apart from their transactions: a loan at minus what it owes, an item at its worth. Each step's
day is a point, and the last day always is."""

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


def series(server, account_id, first, last, step=1):
    from moolakata.store.entities.accounts import Account
    from moolakata.store.repos import ledger as repo

    with server.db.read(unscoped="test") as s:
        led = repo.load(s, s.get(Account, account_id))
        return valuation.series(s, led, True, first, last, step)


def test_a_loan_counts_minus_what_it_owes_each_step_and_on_the_last_day(server, alice):
    loan = new_account(alice, name="HELOC", type="mortgage")
    saved(terms(alice, loan["id"], principal="100000", startDate="2026-01-01", termMonths=120,
                rate="0"))  # fmt: skip
    add(alice, loan["id"], "10000.00", "2026-01-10", kind="deposit")  # paid down
    add(alice, loan["id"], "-2500.00", "2026-01-20", kind="withdrawal")  # drawn again
    got = series(server, loan["id"], d(2026, 1, 1), d(2026, 1, 25), step=7)
    # At no interest what is owed is the principal less payments plus draws.
    assert got == [
        (d(2026, 1, 1), D(-100000)),
        (d(2026, 1, 8), D(-100000)),
        (d(2026, 1, 15), D(-90000)),
        (d(2026, 1, 22), D(-92500)),
        (d(2026, 1, 25), D(-92500)),
    ]
    assert [x for x, _ in series(server, loan["id"], d(2026, 1, 1), d(2026, 1, 15), 7)] == [
        d(2026, 1, 1), d(2026, 1, 8), d(2026, 1, 15)
    ]  # fmt: skip


def test_a_loan_without_terms_has_no_series(server, alice):
    loan = new_account(alice, name="Car loan", type="auto-loan")
    assert series(server, loan["id"], d(2026, 1, 1), d(2026, 1, 31)) == []


def test_an_item_counts_its_worth_while_held(server, alice):
    coll = new_account(alice, name="Collectables", type="collectables")
    coin = make(alice, "Item", accountId=coll["id"], name="Coin", acquiredOn="2026-02-01",
                costBasis="1000").json()  # fmt: skip
    r = make(alice, "Valtn", itemId=coin["id"], date="2026-02-10", value="1200", source="guide")
    assert r.status_code == 200, r.text
    saved(sell(alice, coin["id"], "2026-02-20", "1300"))
    got = dict(series(server, coll["id"], d(2026, 1, 31), d(2026, 2, 25), step=5))
    assert got[d(2026, 1, 31)] == 0
    assert got[d(2026, 2, 5)] == D(1000)
    assert got[d(2026, 2, 15)] == D(1200)
    assert got[d(2026, 2, 25)] == 0
