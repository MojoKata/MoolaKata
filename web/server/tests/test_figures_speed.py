"""The figures built on accounts read in queries that don't grow with the trades, and grow with
the accounts by a bounded few each (the values, taxes and options walk, 16.5): a portfolio's
value, Holdings and series, a projection built on it, a loan's screen. Accounts and trades are
written straight to the database; the time each read takes is printed, never asserted.
"""

import datetime as dt
import time
from decimal import Decimal

from conftest import make_user, sign_in
from edits import make, saved, terms
from sqlalchemy import event
from sqlalchemy.engine import Engine

from moolakata import clock, ids
from moolakata.store.entities.accounts import Lot, Transaction
from moolakata.store.repos import ledger as repo

T0 = dt.datetime(2026, 10, 13, 15, 0, tzinfo=dt.UTC)
SYMBOLS = ("VTI", "AAPL", "MSFT", "BND", "KO")
READS = (
    "/portfolios/all",
    "/portfolios/all/holdings",
    "/portfolios/all/series?range=1Y",
    "/projections/{projection}",
    "/accounts/{loan}/loan",
)
# Queries an account may add to a read that is over every account (its ledger, its lots, its
# prices, a loan's terms or an item's valuations). Measured at 13 to 24, as on main before this
# batch (Holdings 1,083 queries, about 1.5 s, at 50 accounts): a ceiling against growth, not a
# goal; reading the accounts' ledgers together would bring it down.
PER_ACCOUNT = 25


def _counted(c, path: str) -> tuple[int, float]:
    n = [0]

    def count(*_a, **_k):
        n[0] += 1

    event.listen(Engine, "before_cursor_execute", count)
    try:
        t = time.perf_counter()
        r = c.get("/ui/api" + path)
        took = time.perf_counter() - t
    finally:
        event.remove(Engine, "before_cursor_execute", count)
    assert r.status_code == 200, r.text
    return n[0], took


def _brokerages(server, c, n: int) -> list[str]:
    return [make(c, "Acct", name=f"Brokerage {k}", type="brokerage").json()["id"]
            for k in range(n)]  # fmt: skip


def _trades(server, accts: list[str], count: int) -> None:
    with server.db.tx(unscoped="test: trades") as s:
        insts = [repo.instrument(s, sym, None, "equity") for sym in SYMBOLS]
        for i in range(count):
            a, inst = accts[i % len(accts)], insts[i % len(insts)]
            day = dt.date(2025, 1, 2) + dt.timedelta(days=(i * 7) % 600)
            price = Decimal(50 + i % 31)
            buy = Transaction(id=ids.new_id("Txn"), accountId=a, date=day, kind="buy",
                              amount=-price * 5, instrumentId=inst.id, quantity=Decimal(5),
                              price=price)  # fmt: skip
            s.add(buy)
            s.flush()
            s.add(Lot(id=ids.new_id("Lot"), accountId=a, instrumentId=inst.id,
                      transactionId=buy.id, acquiredOn=day, quantity=Decimal(5),
                      costBasis=price * 5))  # fmt: skip


def _household(server, accounts: int):
    clock.fix(T0)
    make_user(server, "alice")
    c = sign_in(server, "alice")
    accts = _brokerages(server, c, accounts)
    loan = make(c, "Acct", name="Mortgage", type="mortgage").json()["id"]
    saved(terms(c, loan, principal="300000", startDate="2026-01-01", termMonths=360, rate="6"))
    homes = make(c, "Acct", name="Home", type="real-estate").json()["id"]
    make(c, "Item", accountId=homes, name="House", acquiredOn="2024-01-10", costBasis="500000",
         valuation="valuations")  # fmt: skip
    return c, accts, loan, homes


def _projection(c, ids_: list[str]) -> str:
    r = make(c, "Prjct", name="Grow", goal="savings", builtOn={"kind": "accounts", "ids": ids_},
             inputs={"target": 50000, "targetDate": "2030-01-01"})  # fmt: skip
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _read_all(c, loan: str, projection: str, label: str) -> dict[str, int]:
    out = {}
    for path in READS:
        p = path.format(loan=loan, projection=projection)
        _counted(c, p)  # once to warm what is kept
        n, took = _counted(c, p)
        print(f"\n{label} {path}: {n} queries, {took * 1000:.0f} ms")
        out[path] = n
    return out


def test_reads_over_accounts_dont_grow_with_the_trades(server):
    try:
        c, accts, loan, homes = _household(server, 10)
        projection = _projection(c, [*accts, loan, homes])
        _trades(server, accts, 50)
        small = _read_all(c, loan, projection, "10 accounts, 50 trades")
        _trades(server, accts, 450)
        large = _read_all(c, loan, projection, "10 accounts, 500 trades")
        grew = {p: (small[p], large[p]) for p in small if large[p] > small[p]}
        assert not grew, f"queries grow with the trades: {grew}"
    finally:
        clock.fix(None)


def test_reads_over_accounts_grow_by_a_few_queries_an_account(server):
    try:
        c, accts, loan, homes = _household(server, 10)
        _trades(server, accts, 100)
        small = _read_all(c, loan, _projection(c, [*accts, loan, homes]), "10 accounts")
        accts += _brokerages(server, c, 40)
        _trades(server, accts[10:], 400)
        large = _read_all(c, loan, _projection(c, [*accts, loan, homes]), "50 accounts")
        over = {p: (small[p], large[p]) for p in small
                if large[p] - small[p] > PER_ACCOUNT * 40}  # fmt: skip
        assert not over, f"more than {PER_ACCOUNT} queries an account: {over}"
    finally:
        clock.fix(None)
