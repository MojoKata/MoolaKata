"""Positions (requirements S3.1, S3.9): open and closed, lots' holding periods, and gains
grouped."""

import datetime as dt
from decimal import Decimal

import pytest
from conftest import make_user, sign_in
from edits import change, create, remove, saved
from test_accounts import add, new_account

from moolakata import clock

T0 = dt.datetime(2026, 10, 13, 12, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


@pytest.fixture
def alice(server, frozen):
    make_user(server, "alice")
    return sign_in(server, "alice")


def trade(c, acct, day, kind, qty, price, symbol="VTI"):
    amount = float(qty) * float(price)
    add(
        c,
        acct,
        f"{-amount if kind == 'buy' else amount:.2f}",
        day,
        kind=kind,
        symbol=symbol,
        quantity=qty,
        price=price,
    )


def test_open_and_closed_with_their_lots(alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")
    trade(alice, brk["id"], "2024-01-05", "buy", "10", "100")
    trade(alice, brk["id"], "2026-06-01", "buy", "10", "200")
    trade(alice, brk["id"], "2026-08-01", "sell", "5", "220")
    trade(alice, brk["id"], "2025-02-01", "buy", "4", "50", "AAPL")
    trade(alice, brk["id"], "2026-03-01", "sell", "4", "40", "AAPL")
    v = alice.get("/ui/api/positions").json()
    vti = next(r for r in v["open"] if r["symbol"] == "VTI")
    assert vti["quantity"] == "15.0" and vti["term"] == "mixed" and len(vti["lots"]) == 2
    assert vti["cost"] == "2500.00" and vti["realized"] == "600.00"
    assert [x["longTerm"] for x in vti["lots"]] == [True, False]
    closed = {r["symbol"]: r for r in v["closed"]}
    assert closed["AAPL"]["realized"] == "-40.00" and closed["AAPL"]["term"] == "long"
    assert closed["AAPL"]["how"] == "sold"
    assert v["summary"]["realizedThisYear"] == "560.00"
    assert v["summary"]["realizedLong"] == "560.00"
    assert alice.get("/ui/api/positions", params={"kind": "options"}).json()["open"] == []


def test_gains_by_month_account_and_term(alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")
    trade(alice, brk["id"], "2026-01-05", "buy", "10", "100")
    trade(alice, brk["id"], "2026-02-01", "sell", "5", "120")
    trade(alice, brk["id"], "2026-03-01", "sell", "5", "90")
    g = alice.get("/ui/api/positions/gains", params={"by": "month", "year": 2026}).json()
    assert [(x["label"], x["total"]) for x in g["realized"]] == [
        ("March 2026", "-50.00"),
        ("February 2026", "100.00"),
    ]
    t = alice.get("/ui/api/positions/gains", params={"by": "term"}).json()
    assert t["realized"] == [
        {
            "key": "short",
            "label": "Short term",
            "shortTerm": "50.00",
            "longTerm": "0.00",
            "total": "50.00",
        }
    ]


def test_a_wash_sale_moves_the_loss_into_the_replacement_lot(server, alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")
    other = new_account(alice, name="Joint", type="brokerage")
    ira = new_account(alice, name="IRA", type="ira")
    trade(alice, brk["id"], "2025-03-01", "buy", "10", "200", "AAPL")
    trade(alice, brk["id"], "2026-06-01", "sell", "10", "150", "AAPL")  # a 500 loss, long term
    trade(alice, other["id"], "2026-06-20", "buy", "4", "155", "AAPL")
    v = alice.get("/ui/api/positions").json()
    sale = next(r for r in v["closed"] if r["symbol"] == "AAPL")
    assert sale["realized"] == "-300.00", "200 of the 500 loss disallowed: 4 of 10 replaced"
    held = next(r for r in v["open"] if r["symbol"] == "AAPL")
    assert held["cost"] == "820.00", "620 paid and the 200 disallowed"
    # In an IRA the replacement's loss is lost for good: no basis added (S3.8.3).
    trade(alice, ira["id"], "2026-06-21", "buy", "6", "155", "AAPL")
    v = alice.get("/ui/api/positions").json()
    sale = next(r for r in v["closed"] if r["symbol"] == "AAPL")
    assert sale["realized"] == "0.00", "all 500 disallowed: 10 of 10 replaced"
    in_ira = next(r for r in v["open"] if r["symbol"] == "AAPL" and r["accountId"] == ira["id"])
    assert in_ira["cost"] == "930.00", "930 paid, nothing added"
    remove(alice, "Txn", _txns(alice, ira)[0])
    # The rest of this test replaces in the IRA alone.
    remove(alice, "Txn", _txns(alice, other)[0])
    trade(alice, ira["id"], "2026-06-20", "buy", "4", "155", "AAPL")
    v = alice.get("/ui/api/positions").json()
    held = next(r for r in v["open"] if r["symbol"] == "AAPL")
    assert held["cost"] == "620.00", "in the IRA, the 200 disallowed adds nothing"
    lot = held["lots"][0]
    assert lot["acquiredOn"] == "2026-06-20", "acquired, and taken in order, by the day bought"
    assert lot["heldFrom"] == "2025-03-20", "the sold shares' 457 days carried over, for the term"
    assert lot["longTerm"]
    # Selling the replacement in the IRA undoes nothing; deleting the buy removes the wash.
    items = alice.get("/ui/api/transactions", params={"account": ira["id"]}).json()["items"]
    buy = items[0]
    r = remove(alice, "Txn", buy)
    assert r.status_code == 200
    sale = next(r for r in alice.get("/ui/api/positions").json()["closed"] if r["symbol"] == "AAPL")
    assert sale["realized"] == "-500.00"


def _txns(c, acct):
    return c.get("/ui/api/transactions", params={"account": acct["id"]}).json()["items"]


def test_changing_the_lot_method_works_the_wash_sales_out_again(server, alice):
    # B7: a change of the account's method reruns the household's wash sales (S2.3), and the
    # rerun takes each sale by the method recorded on it, not the account's new one.
    from sqlalchemy import delete

    from moolakata.store.entities.accounts import Transaction, WashSale

    brk = new_account(alice, name="Brokerage", type="brokerage", lotMethod="fifo")
    trade(alice, brk["id"], "2026-01-05", "buy", "10", "100")
    trade(alice, brk["id"], "2026-02-02", "buy", "10", "50")
    trade(alice, brk["id"], "2026-06-01", "sell", "10", "80")  # FIFO: the $100 lot, a 200 loss
    trade(alice, brk["id"], "2026-06-15", "buy", "10", "80")  # replaces all 10

    def realized():
        return alice.get("/ui/api/positions").json()["summary"]["realizedThisYear"]

    assert realized() == "0.00", "all 200 disallowed"
    # Wash sales gone stale, as a rerun would put right.
    with server.db.tx(unscoped="test") as s:
        s.execute(delete(WashSale))
    assert realized() == "-200.00"
    acct = alice.get(f"/ui/api/accounts/{brk['id']}").json()
    r = change(alice, "Acct", acct, lotMethod="lifo")
    assert r.status_code == 200, r.text
    # By LIFO the sale would take the $50 lot, a 300 gain with nothing to disallow.
    assert realized() == "0.00", "worked out again, by the FIFO recorded on the sale"
    with server.db.read(unscoped="test") as s:
        sale = s.query(Transaction).filter_by(accountId=brk["id"], kind="sell").one()
        assert sale.lotMethod == "fifo"
        assert s.query(WashSale).filter_by(saleId=sale.id).count() == 1


# ---- Corporate actions (S2.4, N4) ----


def _ca(c, acct, inst_id, **body):
    """The corporate action, recorded through the save, its transactions with it."""
    return saved(create(c, "CorpA", accountId=acct, instrumentId=inst_id, **body))


def _lots(server, acct):
    from moolakata.store.entities.accounts import Account, Instrument
    from moolakata.store.repos import ledger as repo

    with server.db.read(unscoped="test") as s:
        rp = repo.load(s, s.get(Account, acct)).replay()
        out = {}
        for x in rp.open:
            sym = s.get(Instrument, x.instrumentId).symbol
            q, b, d = out.get(sym, (0, 0, x.acquiredOn))
            out[sym] = (q + x.quantity, b + (x.basis or 0), min(d, x.acquiredOn))
        return out, rp.disposals


def test_symbol_changes_spin_offs_and_mergers_move_lots_never_sell_them(server, alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")
    a = brk["id"]
    add(alice, a, "100000.00", "2025-01-01", kind="deposit")
    for sym, qty, price in (("FB", "10", "100"), ("GE", "100", "100"), ("ATVI", "100", "50")):
        add(
            alice,
            a,
            f"-{int(qty) * int(price)}.00",
            "2025-01-02",
            kind="buy",
            symbol=sym,
            quantity=qty,
            price=price,
        )
    held = {p["symbol"]: p["instrumentId"] for p in alice.get("/ui/api/positions").json()["open"]}
    _ca(alice, a, held["FB"], kind="symbol-change", date="2026-06-09", newSymbol="META")
    _ca(
        alice,
        a,
        held["GE"],
        kind="spin-off",
        date="2026-01-03",
        newSymbol="GEHC",
        ratio="0.3333",
        basisShare="13.65",
    )
    _ca(
        alice,
        a,
        held["ATVI"],
        kind="merger",
        date="2026-10-13",
        newSymbol="MSFT",
        ratio="0.2",
        cashPerShare="10.00",
        newPrice="400",
    )
    lots, disposals = _lots(server, a)
    assert "FB" not in lots and lots["META"][:2] == (10, Decimal("1000.00"))
    assert lots["META"][2] == dt.date(2025, 1, 2), "the days held carry over"
    assert lots["GE"][:2] == (100, Decimal("8635.00"))
    assert lots["GEHC"][:2] == (Decimal("33.3300"), Decimal("1365.00"))
    assert lots["MSFT"][:2] == (Decimal("20.0"), Decimal("5000.00"))
    [boot] = disposals
    assert boot.proceeds == Decimal("1000.00"), "the cash is a gain, the gain being larger"
    h = alice.get(f"/ui/api/accounts/{a}/holdings").json()
    assert h["cash"] == "85000.00", "the merger's cash is in the account"


def test_an_all_cash_merger_is_a_sale_and_a_pair_is_undone_whole(server, alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")
    a = brk["id"]
    add(alice, a, "10000.00", "2025-01-01", kind="deposit")
    add(alice, a, "-2000.00", "2025-01-02", kind="buy", symbol="TWTR", quantity="50", price="40")
    add(alice, a, "-500.00", "2025-01-02", kind="buy", symbol="FB", quantity="5", price="100")
    held = {p["symbol"]: p["instrumentId"] for p in alice.get("/ui/api/positions").json()["open"]}
    _ca(alice, a, held["TWTR"], kind="merger", date="2026-10-13", cashPerShare="54.20")
    lots, disposals = _lots(server, a)
    assert "TWTR" not in lots and disposals[0].proceeds == Decimal("2710.00")
    action = _ca(alice, a, held["FB"], kind="symbol-change", date="2026-06-09", newSymbol="META")
    _, new = action["transactions"]
    r = remove(alice, "Txn", new)
    assert r.status_code == 200, r.text
    lots, _ = _lots(server, a)
    assert "FB" in lots and "META" not in lots
    r = remove(alice, "CorpA", action)
    assert r.status_code == 404, "the action went with its transaction"
    # Deleting the action undoes it, its transactions with it.
    action = _ca(alice, a, held["FB"], kind="symbol-change", date="2026-06-09", newSymbol="META")
    assert "META" in _lots(server, a)[0]
    assert remove(alice, "CorpA", action).status_code == 200
    lots, _ = _lots(server, a)
    assert "FB" in lots and "META" not in lots
    r = create(alice, "CorpA", accountId=a, instrumentId=held["FB"], kind="spin-off",
               date="2026-06-09", newSymbol="X", ratio="1", basisShare="150")  # fmt: skip
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "basisShare"
