"""Positions' rules one at a time (requirements S3.1, S3.9, S3.10): an open row's quantity, side
and realized gain; and an option trade's steps through buys, sales, contracts moved in and out,
and adjustments, with what it notes of them."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import option_trade
from test_accounts import add, new_account
from test_adjusted import _split_msft
from test_positions import T0, _option, trade

from moolakata import clock


@pytest.fixture
def alice(server):
    clock.fix(T0)
    make_user(server, "alice")
    yield sign_in(server, "alice")
    clock.fix(None)


KEYS = ("symbol", "side", "contracts", "opened", "closed", "how", "premiumIn", "premiumOut",
        "pl", "capitalRequired", "adjustedFrom", "adjustedOn")  # fmt: skip


def _trades(c):
    rows = c.get("/ui/api/positions/option-trades").json()["items"]
    return sorted(tuple(r[k] for k in KEYS) for r in rows)


def _held(c):
    return {r["symbol"]: r["instrumentId"] for r in c.get("/ui/api/positions").json()["open"]}


def _instrument(c, acct, symbol):
    """An instrument's id from the account's transactions."""
    items = c.get("/ui/api/transactions", params={"account": acct}).json()["items"]
    return next(t["instrumentId"] for t in items if t.get("symbol") == symbol)


def _move(c, acct, day, kind, instrument_id, contracts="1"):
    """Contracts moved in or out as the transaction form records it (S2.2)."""
    add(c, acct, "0.00", day, kind=kind, instrumentId=instrument_id, quantity=contracts,
        fees="0")  # fmt: skip


def _adjust_to_msft1(c, day="2026-10-05"):
    """Every open MSFT contract adjusted to deliver 150 shares under the root MSFT1 (S3.10.2)."""
    [g] = c.get("/ui/api/options/adjustable").json()["items"]
    contracts = [
        {
            "instrumentId": cn["instrumentId"],
            "root": "MSFT1",
            "strike": str(cn["strike"]),
            "deliverable": [{"symbol": "MSFT", "shares": "150"}],
        }
        for cn in g["contracts"]
    ]
    r = c.post("/ui/api/options/adjust", json={"date": day, "contracts": contracts})
    assert r.status_code == 200, r.text


# ---- An open row (S3.1) ----


def test_an_open_rows_realized_gain_is_every_close_of_it_so_far(alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    trade(alice, brk, "2026-01-05", "buy", "10", "100")
    trade(alice, brk, "2026-02-02", "sell", "2", "110")
    trade(alice, brk, "2026-03-02", "sell", "3", "130")
    [vti] = alice.get("/ui/api/positions").json()["open"]
    assert (vti["quantity"], vti["realized"]) == ("5.0", "110.00"), "20 and 90"


def test_a_fraction_of_a_share_held_is_long(alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    trade(alice, brk, "2026-01-05", "buy", "0.5", "100")
    [vti] = alice.get("/ui/api/positions").json()["open"]
    assert (vti["side"], vti["quantity"], vti["averageCost"]) == ("long", "0.5", "100.0")


def test_a_contract_held_both_ways_at_once_is_no_row_and_the_rest_still_are(alice):
    """A put bought and then the same put sold to open leave a long and a short lot, none held
    in all: no row for it, whichever position comes after it."""
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    _option(alice, brk, "buy-to-open", "2026-09-01", "1.00")
    _option(alice, brk, "sell-to-open", "2026-09-02", "1.00")
    trade(alice, brk, "2026-09-03", "buy", "10", "100")
    assert [r["symbol"] for r in alice.get("/ui/api/positions").json()["open"]] == ["VTI"]


# ---- An option trade's steps (S3.9.1) ----


def test_contracts_moved_in_open_a_long_trade_and_moved_out_end_it(alice):
    """S3.9.1, S2.2: contracts moved in open or add to a trade, long, with no premium paid, so
    a sale of every contract held closes it; contracts moved out take from it the same way.
    The trades agree with Positions, which holds none of them."""
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    _option(alice, brk, "buy-to-open", "2026-09-01", "1.00")
    _option(alice, brk, "buy-to-open", "2026-09-01", "1.00", right="call", strike="500")
    put, call = (_held(alice)[f"MSFT 20NOV26 {k}"] for k in ("480 P", "500 C"))
    _move(alice, brk, "2026-09-02", "transfer-in", put)
    _option(alice, brk, "sell-to-close", "2026-09-04", "2.00", contracts="2")
    _option(alice, brk, "sell-to-close", "2026-09-02", "1.00", right="call", strike="500")
    _move(alice, brk, "2026-09-03", "transfer-in", call)
    _move(alice, brk, "2026-09-05", "transfer-out", call)
    assert _trades(alice) == [
        ("MSFT 20NOV26 480 P", "long", "2.0", "2026-09-01", "2026-09-04", "sold", "399.35",
         "100.65", "298.70", "100.65", None, None),
        ("MSFT 20NOV26 500 C", "long", "1.0", "2026-09-01", "2026-09-02", "sold", "99.35",
         "100.65", "-1.30", "100.65", None, None),
        ("MSFT 20NOV26 500 C", "long", "1.0", "2026-09-03", "2026-09-05", "moved out",
         "0.00", "0.00", "0.00", "0.00", None, None),
    ]  # fmt: skip
    assert alice.get("/ui/api/positions").json()["open"] == []


def test_contracts_bought_or_sold_again_add_to_the_trade_and_its_premium(alice):
    """A second buy adds to a long trade and a second sale to a short one, each premium with
    it; a credit of a dollar is premium in."""
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    _option(alice, brk, "buy-to-open", "2026-09-01", "1.00")
    _option(alice, brk, "buy-to-open", "2026-09-02", "2.00")
    _option(alice, brk, "sell-to-close", "2026-09-03", "3.00", contracts="2")
    _option(alice, brk, "sell-to-open", "2026-09-01", "6.40", right="call", strike="500")
    _option(alice, brk, "sell-to-open", "2026-09-02", "5.00", right="call", strike="500")
    _option(alice, brk, "buy-to-close", "2026-09-03", "1.00", right="call", strike="500",
            contracts="2")  # fmt: skip
    r = option_trade(alice, brk, "2026-09-01", "sell-to-open", "msft", "put", "300",
                     "2026-11-20", "1", "0.01", "0")  # fmt: skip
    assert r.status_code == 200, r.text
    assert _trades(alice) == [
        ("MSFT 20NOV26 300 P", "short", "1.0", "2026-09-01", None, None, "1.00", "0.00",
         None, "30000.00", None, None),
        ("MSFT 20NOV26 480 P", "long", "2.0", "2026-09-01", "2026-09-03", "sold", "599.35",
         "301.30", "298.05", "301.30", None, None),
        ("MSFT 20NOV26 500 C", "short", "2.0", "2026-09-01", "2026-09-03", "bought back",
         "1138.70", "200.65", "938.05", "100000.00", None, None),
    ]  # fmt: skip


# ---- Through an adjustment (S3.10.4) ----


def test_an_adjusted_contract_takes_the_side_its_trades_left_so_its_close_ends_the_trade(alice):
    """S3.10.4: the adjusted contract is held on the side every trade of the old one left it,
    a buy back, a second buy, contracts moved in and out each counted, so closing the adjusted
    contracts ends the trade."""
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    sides = {
        # strike, right: each trade's action and contracts, and the side they leave
        ("480", "put"): ([("sell-to-open", "2"), ("buy-to-close", "2"), ("buy-to-open", "1")],
                         "sell-to-close"),
        ("500", "call"): ([("buy-to-open", "2"), ("buy-to-open", "1"), ("sell-to-close", "1")],
                          "sell-to-close"),
        ("300", "put"): ([("sell-to-open", "2"), ("buy-to-close", "1")], "buy-to-close"),
        ("520", "call"): ([("buy-to-open", "2"), ("sell-to-close", "2"), ("sell-to-open", "1")],
                          "buy-to-close"),
    }  # fmt: skip
    for (strike, right), (steps, _) in sides.items():
        for i, (action, contracts) in enumerate(steps):
            _option(alice, brk, action, f"2026-09-0{i + 1}", "1.00", right=right, strike=strike,
                    contracts=contracts)  # fmt: skip
    # Moved in and out: a put moved in is long; a call bought, moved out and sold is short.
    _option(alice, brk, "buy-to-open", "2026-09-01", "1.00", right="call", strike="540",
            contracts="2")  # fmt: skip
    _option(alice, brk, "buy-to-open", "2026-09-01", "1.00", strike="320")
    _option(alice, brk, "sell-to-close", "2026-09-02", "1.00", strike="320")
    held = _held(alice)
    _move(alice, brk, "2026-09-03", "transfer-out", held["MSFT 20NOV26 540 C"], "2")
    _option(alice, brk, "sell-to-open", "2026-09-04", "1.00", right="call", strike="540")
    _move(alice, brk, "2026-09-03", "transfer-in", _instrument(alice, brk, "MSFT 20NOV26 320 P"))
    sides[("540", "call")] = ([], "buy-to-close")
    sides[("320", "put")] = ([], "sell-to-close")
    _split_msft(alice, brk)
    for (strike, right), (_, close) in sides.items():
        new = f"{int(strike) // 2}"
        contracts = alice.get("/ui/api/positions").json()["open"]
        [row] = [r for r in contracts if r["symbol"] == f"MSFT 20NOV26 {new} {right[0].upper()}"]
        _option(alice, brk, close, "2026-10-10", "1.00", right=right, strike=new,
                contracts=str(abs(int(float(str(row["quantity"]))))))  # fmt: skip
    got = [(r[0], r[1], r[4], r[5]) for r in _trades(alice) if r[10] is not None]
    assert got == [
        ("MSFT 20NOV26 150 P", "short", "2026-10-10", "bought back"),
        ("MSFT 20NOV26 160 P", "long", "2026-10-10", "sold"),
        ("MSFT 20NOV26 240 P", "long", "2026-10-10", "sold"),
        ("MSFT 20NOV26 250 C", "long", "2026-10-10", "sold"),
        ("MSFT 20NOV26 260 C", "short", "2026-10-10", "bought back"),
        ("MSFT 20NOV26 270 C", "short", "2026-10-10", "bought back"),
    ]
    assert alice.get("/ui/api/positions", params={"kind": "options"}).json()["open"] == []


def test_a_trade_on_the_old_contract_the_day_it_is_adjusted_comes_before_the_adjustment(alice):
    """S3.10.4: the lots take every trade of the adjustment's day before it, one typed after
    the adjustment too, so the adjusted contract's side counts it: a put sold, then on the
    day two bought, is adjusted long, and selling the adjusted one ends the trade."""
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    _option(alice, brk, "sell-to-open", "2026-09-01", "1.00")
    _adjust_to_msft1(alice)
    clock.fix(T0 + dt.timedelta(hours=1))
    _option(alice, brk, "buy-to-open", "2026-10-05", "1.00", contracts="2")
    [row] = alice.get("/ui/api/positions", params={"kind": "options"}).json()["open"]
    assert (row["symbol"], row["side"], row["quantity"]) == ("MSFT1 20NOV26 480 P", "long", "1.0")
    _option(alice, brk, "sell-to-close", "2026-10-06", "1.00", under="msft1")
    [got] = [r for r in _trades(alice) if r[0] == "MSFT1 20NOV26 480 P"]
    assert got[:6] == ("MSFT1 20NOV26 480 P", "short", "1.0", "2026-09-01", "2026-10-06", "sold")


def test_a_contract_adjusted_twice_is_one_trade_through_both(alice):
    """S3.10.4: a trade runs through every adjustment of its contract, each the next one's
    start, noting the contract it opened on and the latest adjustment's day."""
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    _option(alice, brk, "sell-to-open", "2026-09-01", "6.40")
    _split_msft(alice, brk, "2026-10-01")
    _split_msft(alice, brk, "2026-10-05")
    _option(alice, brk, "buy-to-close", "2026-10-10", "1.00", strike="120", contracts="4")
    assert _trades(alice) == [
        ("MSFT 20NOV26 120 P", "short", "4.0", "2026-09-01", "2026-10-10", "bought back",
         "639.35", "400.65", "238.70", "48000.00", "MSFT 20NOV26 480 P", "2026-10-05"),
    ]  # fmt: skip


def test_a_trade_that_ends_on_the_contract_it_opened_on_notes_no_adjustment(alice):
    """S3.10.4: the contract it opened on and the day it was adjusted come together, for a
    trade that ends on another contract: one ending on its own notes neither."""
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    _option(alice, brk, "sell-to-open", "2026-09-01", "1.00")
    _split_msft(alice, brk, "2026-10-01")
    _option(alice, brk, "sell-to-open", "2026-10-06", "1.00")
    _option(alice, brk, "buy-to-close", "2026-10-07", "1.00", strike="240", contracts="2")
    _option(alice, brk, "buy-to-close", "2026-10-08", "1.00")
    [got] = _trades(alice)
    assert got[:6] + got[10:] == (
        "MSFT 20NOV26 480 P", "short", "1.0", "2026-09-01", "2026-10-08", "bought back", None,
        None)  # fmt: skip


def test_a_trade_ends_at_an_adjustment_onto_a_contract_held_the_other_way(alice):
    """S3.10.4: a put sold, adjusted onto a contract already held long as many times, leaves
    none held: the trade ends there, adjusted."""
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    _option(alice, brk, "sell-to-open", "2026-09-01", "6.40")
    r = option_trade(alice, brk, "2026-09-02", "buy-to-open", "msft1", "put", "480",
                     "2026-11-20", "1", "2.00", "0")  # fmt: skip
    assert r.status_code == 200, r.text
    groups = alice.get("/ui/api/options/adjustable").json()["items"]
    [old] = [cn for g in groups for cn in g["contracts"] if cn["symbol"] == "MSFT 20NOV26 480 P"]
    r = alice.post("/ui/api/options/adjust", json={"date": "2026-10-05", "contracts": [
        {"instrumentId": old["instrumentId"], "root": "MSFT1", "strike": "480",
         "deliverable": [{"symbol": "MSFT", "shares": "150"}]}]})  # fmt: skip
    assert r.status_code == 200, r.text
    assert _trades(alice) == [
        ("MSFT1 20NOV26 480 P", "short", "1.0", "2026-09-01", "2026-10-05", "adjusted",
         "639.35", "200.00", "439.35", "48000.00", "MSFT 20NOV26 480 P", "2026-10-05"),
    ]  # fmt: skip
