"""A tax book reads in the same number of queries however many trades it counts (the filed tax
years walk, decision 3.6): no query a row. (Found by it: the wash sales were read one query a
wash sale, 358 queries for 600 trades.) The trades are written straight to the database, so
a household of hundreds of them is made in a moment; the time each read takes is printed, never
asserted (a slow machine is no failure).
"""

import datetime as dt
import time
from decimal import Decimal

from conftest import make_user, sign_in
from edits import make
from sqlalchemy import event
from sqlalchemy.engine import Engine

from moolakata import clock, ids, washes
from moolakata.store.entities.accounts import Account, Lot, Transaction
from moolakata.store.repos import ledger as repo

T0 = dt.datetime(2026, 12, 20, 15, 0, tzinfo=dt.UTC)
SYMBOLS = ("AAPL", "MSFT", "IBM", "VTSAX", "KO")
READS = ("/tax-books/{book}", "/tax-books/{book}/panels", "/tax-books")
# Large enough that the small household already has every shape a query depends on (each
# instrument in each account, sales in each year, wash sales): only the number of rows grows.
SMALL, LARGE = 150, 600


def _household(server) -> tuple:
    clock.fix(T0)
    make_user(server, "alice")
    c = sign_in(server, "alice")
    me = c.get("/ui/api/session").json()["user"]["id"]
    names = ("Brokerage", "Second", "Third")
    accts = [make(c, "Acct", name=n, type="brokerage").json()["id"] for n in names]
    book = make(c, "TaxBk", year=2025, filers=[me]).json()["id"]
    return c, me, accts, book


def _trades(server, me: str, accts: list[str], start: int, end: int) -> None:
    """Trades `start` to `end` (a buy and a later sale of part of it, each), written as the
    importer writes them."""
    with server.db.tx(unscoped="test: a household of trades") as s:
        insts = [repo.instrument(s, sym, None, repo.class_by_symbol(sym)) for sym in SYMBOLS]
        first = dt.date(2024, 1, 2)
        for i in range(start // 2, end // 2):
            a = s.get(Account, accts[i % 3])
            inst = insts[i % len(insts)]
            day = first + dt.timedelta(days=(i * 29) % 700)  # every year, small or large
            price = Decimal(50 + i % 37)
            buy = Transaction(id=ids.new_id("Txn"), accountId=a.id, date=day, kind="buy",
                              amount=-price * 10, instrumentId=inst.id, quantity=Decimal(10),
                              price=price)  # fmt: skip
            s.add(buy)
            s.flush()
            s.add(Lot(id=ids.new_id("Lot"), accountId=a.id, instrumentId=inst.id,
                      transactionId=buy.id, acquiredOn=day, quantity=Decimal(10),
                      costBasis=price * 10))  # fmt: skip
            sold = Decimal(45 + i % 41)
            s.add(Transaction(id=ids.new_id("Txn"), accountId=a.id,
                              date=day + dt.timedelta(days=60), kind="sell", amount=sold * 4,
                              instrumentId=inst.id, quantity=Decimal(-4), price=sold,
                              lotMethod="fifo"))  # fmt: skip
        s.flush()
        washes.recompute(s, me)


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


def test_a_tax_books_reads_take_the_same_queries_at_any_size(server):
    try:
        c, me, accts, book = _household(server)
        seen: dict[int, dict[str, int]] = {}
        made = 0
        for trades in (SMALL, LARGE):
            _trades(server, me, accts, made, trades)
            made = trades
            seen[trades] = {}
            for path in READS:
                p = path.format(book=book)
                _counted(c, p)  # once to warm what is kept
                n, took = _counted(c, p)
                print(f"\n{trades} trades {path}: {n} queries, {took * 1000:.0f} ms")
                seen[trades][path] = n
        grew = {
            p: (seen[SMALL][p], seen[LARGE][p]) for p in READS if seen[LARGE][p] > seen[SMALL][p]
        }
        assert not grew, f"queries grow with the trades: {grew}"
    finally:
        clock.fix(None)
