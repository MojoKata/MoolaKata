"""Bitcoin network fees in Form 8949 (requirements S8.19; the filed tax years walk, decision 3):
every case of where the coins went (to someone else, or to the owner's own wallet) by how the
book reads fees (a sale, or not taxed) by how long the coins were held.

A fee paid in bitcoin is a sale of its sats at the day's price, taken from the lots like any
sale, in a self-custody wallet's boxes (I short, L long). A book that reads fees on transfers
between the owner's own wallets as not taxed leaves those out, and only those.
"""

import datetime as dt
import itertools
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import make

from moolakata import clock, ids
from moolakata.bitcoin import sources, sync
from moolakata.store.entities.accounts import Lot, Transaction
from moolakata.store.entities.prices import Price
from moolakata.store.repos import ledger as repo

T0 = dt.datetime(2026, 3, 2, 15, 0, tzinfo=dt.UTC)
SENT = dt.datetime(2025, 6, 10, 15, 0, tzinfo=dt.UTC)
SAT = D(100_000_000)
FEE = 12_000  # sats
PRICE = D("60000")

CASES = list(itertools.product(("others", "own"), ("sale", "not-taxed"), ("short", "long")))


@pytest.mark.parametrize(("to", "reading", "term"), CASES,
                         ids=["-".join(c) for c in CASES])  # fmt: skip
def test_a_network_fee_is_a_sale_unless_the_book_reads_own_transfers_as_not_taxed(
    server, to, reading, term
):
    from moolakata.prices import refresh

    refresh.install()  # stored closes value the fee, as the running server reads them
    clock.fix(T0)
    try:
        make_user(server, "alice")
        c = sign_in(server, "alice")
        me = c.get("/ui/api/session").json()["user"]["id"]
        hot = make(c, "Acct", name="Hot wallet", type="crypto-wallet").json()["id"]
        cold = make(c, "Acct", name="Cold storage", type="crypto-wallet").json()["id"]
        acquired = dt.date(2024, 3, 1) if term == "long" else dt.date(2025, 3, 1)
        with server.db.tx(unscoped="test: coins held, and their price") as s:
            btc = repo.instrument(s, "BTC", "Bitcoin", "crypto")
            got = Transaction(id=ids.new_id("Txn"), accountId=hot, date=acquired,
                              kind="transfer-in", amount=D(0), instrumentId=btc.id,
                              quantity=D(1))  # fmt: skip
            s.add(got)
            s.flush()
            s.add(Lot(id=ids.new_id("Lot"), accountId=hot, instrumentId=btc.id,
                      transactionId=got.id, acquiredOn=acquired, quantity=D(1),
                      costBasis=D("30000")))  # fmt: skip
            s.add(Price(instrumentId=btc.id, date=SENT.date(), close=PRICE, source="test"))
            s.flush()
            # Sent: 0.1 BTC, the fee paid on top.
            sync.record(s, hot, [sources.Tx("a" * 64, SENT, -(10_000_000 + FEE), FEE)])
            if to == "own":
                sync.record(s, cold, [sources.Tx("a" * 64, SENT, 10_000_000, 0)])
                out = s.query(Transaction).filter_by(accountId=hot, kind="transfer-out").one()
                into = s.query(Transaction).filter_by(accountId=cold, kind="transfer-in").one()
                out.transferId, into.transferId = into.id, out.id
        book = make(c, "TaxBk", year=2025, filers=[me], bitcoinFees=reading).json()["id"]
        rows = c.get(f"/ui/api/tax-books/{book}/panels").json()["rows"]
        fees = [r for r in rows if r["description"].endswith(" BTC")]
        if to == "own" and reading == "not-taxed":
            assert fees == [], "an own transfer's fee, read as not taxed, leaves Form 8949"
            return
        (r,) = fees
        qty = D(FEE) / SAT
        assert r["description"] == f"{qty.normalize():f} BTC"
        assert D(str(r["proceeds"])) == (qty * PRICE).quantize(D("0.01"))
        assert D(str(r["basis"])) == (D("30000") * qty).quantize(D("0.01"))
        assert r["box"] == ("L" if term == "long" else "I")
        assert r["account"] == "Hot wallet"
    finally:
        clock.fix(None)
