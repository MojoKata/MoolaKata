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


def test_shares_moved_in_without_their_lots_list_with_their_term_unknown(alice):
    """S2.2, CR3-73: shares moved in with no lots typed are one lot whose day bought is
    missing: Positions lists it with its term unknown, beside a lot bought, and doesn't fail."""
    brk = new_account(alice, name="Brokerage", type="brokerage")
    trade(alice, brk["id"], "2024-01-05", "buy", "10", "100")
    add(alice, brk["id"], "0.00", "2026-09-12", kind="transfer-in", symbol="VTI", quantity="5")
    r = alice.get("/ui/api/positions")
    assert r.status_code == 200, r.text
    vti = next(x for x in r.json()["open"] if x["symbol"] == "VTI")
    assert [x["longTerm"] for x in vti["lots"]] == [True, None]
    assert vti["term"] == "unknown"
    # Sold, the shares' row has its day opened unknown, as its term is (CR3-435).
    trade(alice, brk["id"], "2026-10-01", "sell", "15", "110")
    sold = alice.get("/ui/api/positions").json()["closed"]
    assert [(x["symbol"], x["opened"], x["term"]) for x in sold] == [("VTI", None, "unknown")]


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


@pytest.mark.parametrize(
    ("symbol", "cash", "refused"),
    [
        ("MSFT", None, "cash-missing"),  # blank: asked, never read as none (S2.4.5, R3.11)
        ("MSFT", "0", None),  # paid all in shares: 0, typed or filled in by Min
        ("MSFT", "-1", "cash-invalid"),
        (None, None, "cash-missing"),  # all in cash: what each share was paid
        (None, "0", "cash-missing"),
        (None, "54.20", None),
    ],
)
def test_a_mergers_cash_is_asked_of_every_merger(server, alice, symbol, cash, refused):
    a = new_account(alice, name="Brokerage", type="brokerage")["id"]
    add(alice, a, "10000.00", "2025-01-01", kind="deposit")
    add(alice, a, "-2000.00", "2025-01-02", kind="buy", symbol="TWTR", quantity="50", price="40")
    [held] = alice.get("/ui/api/positions").json()["open"]
    body = dict(accountId=a, instrumentId=held["instrumentId"], kind="merger", date="2026-10-13")
    body |= {"newSymbol": symbol, "ratio": "0.2"} if symbol else {}
    body |= {"cashPerShare": cash} if cash is not None else {}
    r = create(alice, "CorpA", **body)
    if refused:
        assert r.status_code == 422, r.text
        first = r.json()["errors"][0]
        assert (first["field"], first["code"]) == ("cashPerShare", refused)
        said = {
            (
                True,
                "cash-missing",
            ): "The cash for each share held: 0 for a merger paid all in shares.",
            (False, "cash-missing"): "What each share was paid.",
            (True, "cash-invalid"): "Zero or more.",
        }
        assert first["message"] == said[(symbol is not None, refused)]
        return
    assert r.status_code == 200, r.text
    lots, disposals = _lots(server, a)
    if symbol:
        assert lots["MSFT"][:2] == (Decimal("10.0"), Decimal("2000.00")), "the basis moves whole"
        assert disposals == [], "no cash, no gain, and no price asked for"
    else:
        assert disposals[0].proceeds == Decimal("2710.00")


# ---- Each row as Positions shows it (S3.1) ----


def _option(c, acct, action, day, premium, right="put", strike="480", expiry="2026-11-20",
            contracts="1", under="msft"):  # fmt: skip
    from edits import option_trade

    r = option_trade(c, acct, day, action, under, right, strike, expiry, contracts, premium,
                     "0.65")  # fmt: skip
    assert r.status_code == 200, r.text


def _held_book(alice):
    """20 MSFT, half bought in 2024 at $100 and half in June at $200, its last trade; two MSFT
    480 puts sold, a 310 put bought expiring in 8 days and a 300 put in 7, and an AAPL call
    with no price for AAPL."""
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    trade(alice, brk, "2024-01-05", "buy", "10", "100", "MSFT")
    trade(alice, brk, "2026-06-01", "buy", "10", "200", "MSFT")
    _option(alice, brk, "sell-to-open", "2026-09-02", "6.40", contracts="2")
    _option(alice, brk, "buy-to-open", "2026-09-03", "1.00", strike="300", expiry="2026-10-20")
    _option(alice, brk, "buy-to-open", "2026-09-03", "1.00", strike="310", expiry="2026-10-21")
    _option(alice, brk, "buy-to-open", "2026-09-04", "2.00", right="call", strike="250",
            under="aapl")  # fmt: skip
    return brk


def test_an_open_row_is_its_lots_cost_value_and_gain_largest_first(alice):
    """S3.1: the rows by their value's size; a short position's cost its credit, its average
    a positive price and its gain a share of that credit; an option's days to expiry and
    whether it is in the money at its underlying's last price, unknown without one."""
    _held_book(alice)
    v = alice.get("/ui/api/positions").json()
    keys = ("symbol", "name", "instrumentClass", "side", "quantity", "cost", "averageCost",
            "value", "priceSource", "unrealized", "unrealizedPct", "realized", "term", "days",
            "expiry", "daysToExpiry", "inTheMoney")  # fmt: skip
    assert [tuple(r[k] for k in keys) for r in v["open"]] == [
        ("MSFT 20NOV26 480 P", "MSFT put 480, expiring Nov 20, 2026", "option", "short", "-2.0",
         "-1279.35", "639.675", "-56000.00", "intrinsic", "-54720.65", "-4277.22", "0.00",
         "short", 41, "2026-11-20", 38, True),
        ("MSFT 21OCT26 310 P", "MSFT put 310, expiring Oct 21, 2026", "option", "long", "1.0",
         "100.65", "100.65", "11000.00", "intrinsic", "10899.35", "10828.96", "0.00", "short",
         40, "2026-10-21", 8, True),
        ("MSFT 20OCT26 300 P", "MSFT put 300, expiring Oct 20, 2026", "option", "long", "1.0",
         "100.65", "100.65", "10000.00", "intrinsic", "9899.35", "9835.42", "0.00", "short",
         40, "2026-10-20", 7, True),
        ("MSFT", None, "equity", "long", "20.0", "3000.00", "150.0", "4000.00", "trade",
         "1000.00", "33.33", "0.00", "mixed", 1012, None, None, None),
        ("AAPL 20NOV26 250 C", "AAPL call 250, expiring Nov 20, 2026", "option", "long", "1.0",
         "200.65", "200.65", None, None, None, None, "0.00", "short", 39, "2026-11-20", 38,
         None),
    ]  # fmt: skip
    msft = v["open"][3]
    assert [(x["acquiredOn"], x["heldFrom"], x["quantity"], x["basis"], x["days"],
             x["longTerm"]) for x in msft["lots"]] == [
        ("2024-01-05", None, "10.0", "1000.00", 1012, True),
        ("2026-06-01", None, "10.0", "2000.00", 134, False)]  # fmt: skip
    assert v["summary"]["expiringSoon"] == [
        {"symbol": "MSFT 20OCT26 300 P", "days": 7, "inTheMoney": True}
    ]
    assert v["summary"]["unrealized"] == "-32921.95"


def test_a_call_above_its_underlyings_price_is_out_of_the_money(alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    trade(alice, brk, "2026-06-01", "buy", "10", "200", "MSFT")
    _option(alice, brk, "sell-to-open", "2026-09-02", "1.00", right="call", strike="250")
    [call] = alice.get("/ui/api/positions", params={"kind": "options"}).json()["open"]
    assert (call["inTheMoney"], call["value"], call["priceSource"]) == (False, 0, "intrinsic")


def test_shares_moved_in_with_no_basis_have_no_cost_average_or_gain(alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    trade(alice, brk, "2026-06-01", "buy", "10", "200", "MSFT")
    add(alice, brk, "0.00", "2026-09-12", kind="transfer-in", symbol="MSFT", quantity="5")
    [row] = alice.get("/ui/api/positions").json()["open"]
    assert (row["cost"], row["averageCost"], row["value"], row["unrealized"],
            row["unrealizedPct"]) == (None, None, "3000.00", None, None)  # fmt: skip
    assert alice.get("/ui/api/positions").json()["summary"]["unrealized"] == "0.00"


def test_positions_of_a_kind_are_its_open_and_closed_rows_alone(alice):
    """Stocks, options or crypto: each asked for alone leaves out the others' rows, open and
    closed, whichever comes first."""
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    for sym in ("VTI", "MSFT", "AAPL"):
        trade(alice, brk, "2026-06-01", "buy", "10", "100", sym)
        trade(alice, brk, "2026-07-01", "sell", "5", "120", sym)
    for strike in ("300", "310", "320"):
        _option(alice, brk, "buy-to-open", "2026-09-03", "1.00", strike=strike)
        _option(alice, brk, "sell-to-close", "2026-09-04", "2.00", strike=strike, contracts="1")
        _option(alice, brk, "buy-to-open", "2026-09-05", "1.00", strike=strike)
    want = {"stocks": {"VTI", "MSFT", "AAPL"},
            "options": {f"MSFT 20NOV26 {k} P" for k in ("300", "310", "320")},
            "crypto": set()}  # fmt: skip
    for kind, symbols in want.items():
        v = alice.get("/ui/api/positions", params={"kind": kind}).json()
        assert {r["symbol"] for r in v["open"]} == symbols
        assert {r["symbol"] for r in v["closed"]} == symbols
    v = alice.get("/ui/api/positions").json()
    assert len(v["open"]) == len(v["closed"]) == 6


def test_a_closed_row_is_each_closing_trade_latest_first_with_how_it_closed(alice):
    """S3.1: a sale from two lots is one row, opened when the first was bought; a short
    position's close is short; how each closed in words, or the action's own name; a sale with
    no lot to match has no cost, no gain and an unknown term (CR3-415)."""
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    trade(alice, brk, "2025-01-02", "buy", "10", "100", "VTI")
    trade(alice, brk, "2025-06-02", "buy", "10", "110", "VTI")
    trade(alice, brk, "2026-03-02", "sell", "15", "120", "VTI")
    trade(alice, brk, "2026-03-03", "sell", "2", "50", "IBM")
    _option(alice, brk, "sell-to-open", "2026-09-02", "6.40", contracts="2")
    _option(alice, brk, "buy-to-close", "2026-09-10", "2.10", contracts="2")
    _option(alice, brk, "buy-to-open", "2026-09-03", "3.00", right="call", strike="500")
    _option(alice, brk, "sell-to-close", "2026-09-11", "4.00", right="call", strike="500")
    _option(alice, brk, "sell-to-open", "2026-09-04", "1.00", strike="300", expiry="2026-10-09")
    trade(alice, brk, "2025-01-02", "buy", "10", "40", "TWTR")
    held = {r["symbol"]: r["instrumentId"] for r in alice.get("/ui/api/positions").json()["open"]}
    r = alice.post(f"/ui/api/accounts/{brk}/options/{held['MSFT 09OCT26 300 P']}/settle",
                   json={"how": "expired", "date": "2026-10-09", "contracts": "1"})  # fmt: skip
    assert r.status_code == 201, r.text
    r = create(alice, "CorpA", accountId=brk, instrumentId=held["TWTR"], kind="merger",
               date="2026-10-12", cashPerShare="54.20")  # fmt: skip
    assert r.status_code == 200, r.text
    keys = ("symbol", "instrumentClass", "side", "quantity", "opened", "closed", "how",
            "proceeds", "cost", "realized", "washDisallowed", "term")  # fmt: skip
    v = alice.get("/ui/api/positions").json()
    assert [tuple(r[k] for k in keys) for r in v["closed"]] == [
        ("TWTR", "equity", "long", "10.0", "2025-01-02", "2026-10-12", "merger", "542.00",
         "400.00", "142.00", "0.00", "long"),
        ("MSFT 09OCT26 300 P", "option", "short", "1.0", "2026-09-04", "2026-10-09", "expired",
         "0.00", "-99.35", "99.35", "0.00", "short"),
        ("MSFT 20NOV26 500 C", "option", "long", "1.0", "2026-09-03", "2026-09-11", "sold",
         "399.35", "300.65", "98.70", "0.00", "short"),
        ("MSFT 20NOV26 480 P", "option", "short", "2.0", "2026-09-02", "2026-09-10",
         "bought back", "-420.65", "-1279.35", "858.70", "0.00", "short"),
        ("IBM", "equity", "long", "2.0", None, "2026-03-03", "sold", "100.00", None, None,
         "0.00", "unknown"),
        ("VTI", "equity", "long", "15.0", "2025-01-02", "2026-03-02", "sold", "1800.00",
         "1550.00", "250.00", "0.00", "mixed"),
    ]  # fmt: skip
    assert all(r["saleId"].startswith("Txn_") for r in v["closed"])


# ---- Option trades (S3.9.2) ----


def test_each_option_trade_open_latest_first_then_each_closed_latest_first(alice):
    """S3.9.2: an open trade is worth its mark, and without one has no P/L; a long option
    requires its premium, so one bought for nothing has no return; an assignment and an
    exercise close a trade in words."""
    from edits import option_trade

    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    add(alice, brk, "100000.00", "2025-01-01", kind="deposit")
    trade(alice, brk, "2026-06-01", "buy", "10", "200", "MSFT")
    _option(alice, brk, "buy-to-open", "2026-09-06", "5.00", right="call", strike="100",
            expiry="2026-10-09")  # fmt: skip
    _option(alice, brk, "sell-to-open", "2026-09-05", "5.00", strike="450", expiry="2026-10-09")
    _option(alice, brk, "buy-to-open", "2026-09-07", "2.00", strike="500")
    _option(alice, brk, "buy-to-open", "2026-09-08", "2.00", right="call", strike="250",
            under="aapl")  # fmt: skip
    r = option_trade(alice, brk, "2026-09-09", "buy-to-open", "msft", "call", "900",
                     "2026-11-20", "1", "0", "0")  # fmt: skip
    assert r.status_code == 200, r.text
    held = {r["symbol"]: r["instrumentId"] for r in alice.get("/ui/api/positions").json()["open"]}
    for symbol, how, day in (("MSFT 09OCT26 450 P", "assign", "2026-10-09"),
                             ("MSFT 09OCT26 100 C", "exercise", "2026-10-08")):  # fmt: skip
        r = alice.post(f"/ui/api/accounts/{brk}/options/{held[symbol]}/settle",
                       json={"how": how, "date": day, "contracts": "1"})  # fmt: skip
        assert r.status_code == 201, r.text
    keys = ("symbol", "side", "contracts", "opened", "closed", "how", "premiumIn", "premiumOut",
            "value", "pl", "capitalRequired", "returnPct")  # fmt: skip
    rows = alice.get("/ui/api/positions/option-trades").json()["items"]
    assert [tuple(r[k] for k in keys) for r in rows] == [
        ("MSFT 20NOV26 900 C", "long", "1.0", "2026-09-09", None, None, "0.00", "0.00", "0.00",
         "0.00", "0.00", None),
        ("AAPL 20NOV26 250 C", "long", "1.0", "2026-09-08", None, None, "0.00", "200.65", None,
         None, "200.65", None),
        ("MSFT 20NOV26 500 P", "long", "1.0", "2026-09-07", None, None, "0.00", "200.65",
         "5000.00", "4799.35", "200.65", "2391.90"),
        ("MSFT 09OCT26 450 P", "short", "1.0", "2026-09-05", "2026-10-09", "assigned",
         "499.35", "0.00", None, "499.35", "45000.00", "1.11"),
        ("MSFT 09OCT26 100 C", "long", "1.0", "2026-09-06", "2026-10-08", "exercised", "0.00",
         "500.65", None, "-500.65", "500.65", "-100.0"),
    ]  # fmt: skip


def test_an_adjusted_contracts_trade_goes_on_under_it_on_the_side_it_was(alice):
    """S3.10.4, CR3-438: a trade open when its contract is adjusted goes on under the adjusted
    contract, from the day it opened, on the side held: a put sold, bought back and then bought
    is long; a call bought, sold and then sold again is short."""
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    for action, day, contracts in (("sell-to-open", "2026-09-01", "2"),
                                   ("buy-to-close", "2026-09-02", "2"),
                                   ("buy-to-open", "2026-09-03", "1")):  # fmt: skip
        _option(alice, brk, action, day, "1.00", contracts=contracts)
    for action, day, contracts in (("buy-to-open", "2026-09-01", "2"),
                                   ("sell-to-close", "2026-09-02", "2"),
                                   ("sell-to-open", "2026-09-03", "1")):  # fmt: skip
        _option(alice, brk, action, day, "1.00", right="call", strike="500",
                contracts=contracts)  # fmt: skip
    [g] = alice.get("/ui/api/options/adjustable").json()["items"]
    contracts = [
        {
            "instrumentId": cn["instrumentId"],
            "root": "MSFT1",
            "strike": str(cn["strike"]),
            "deliverable": [{"symbol": "MSFT", "shares": "150"}],
        }
        for cn in g["contracts"]
    ]
    r = alice.post("/ui/api/options/adjust", json={"date": "2026-10-05", "contracts": contracts})
    assert r.status_code == 200, r.text
    rows = alice.get("/ui/api/positions/option-trades").json()["items"]
    got = sorted((r["symbol"], r["side"], r["contracts"], r["opened"], r["closed"], r["how"])
                 for r in rows)  # fmt: skip
    assert got == [
        ("MSFT 20NOV26 480 P", "short", "2.0", "2026-09-01", "2026-09-02", "bought back"),
        ("MSFT 20NOV26 500 C", "long", "2.0", "2026-09-01", "2026-09-02", "sold"),
        ("MSFT1 20NOV26 480 P", "long", "1.0", "2026-09-03", None, None),
        ("MSFT1 20NOV26 500 C", "short", "1.0", "2026-09-03", None, None),
    ]
