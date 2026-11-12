"""How holdings are priced and valued, at the edges each rule draws (S4.6, S4.7, S4.10, S3.7,
S5.2.3): which source a day's price comes from and how it is labelled, the days a range of
prices keeps, an account's value day by day, and the money moved in. Rows are written straight
to the database where only prices matter, and through the app where lots must be replayed."""

import datetime as dt
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import create, make, option_trade, saved, terms
from sqlalchemy import select
from test_accounts import add, new_account

from moolakata import clock, ids, valuation
from moolakata.prices import refresh as pricing
from moolakata.store.entities.accounts import (
    Account,
    Holding,
    Instrument,
    OptionContract,
    Transaction,
)
from moolakata.store.entities.prices import Price, TypedPrice
from moolakata.store.repos import ledger as repo

d = dt.date
P = valuation.Price
TODAY = d(2026, 10, 15)
GONE = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)  # when a deleted row was deleted


def sep(day: int) -> dt.date:
    return d(2026, 9, day)


@pytest.fixture(autouse=True)
def stored_closes(monkeypatch):
    """Stored closes value holdings, as on the running server, on a fixed today; both put back
    after."""
    monkeypatch.setattr(valuation, "_closes", [])
    monkeypatch.setattr(valuation, "_history", [])
    pricing.install()
    clock.fix(dt.datetime.combine(TODAY, dt.time(15), dt.UTC))
    yield
    clock.fix(None)


# ---------- rows written straight to the database ----------


def _gone(deleted: bool):
    return GONE if deleted else None


def _account(s, owner: str) -> str:
    a = Account(id=ids.new_id("Acct"), ownerId=owner, name="Brokerage", type="brokerage")
    s.add(a)
    s.flush()
    return a.id


def _instrument(s, symbol: str, cls: str = "equity") -> str:
    i = Instrument(id=ids.new_id("Instr"), symbol=symbol, instrumentClass=cls)
    s.add(i)
    s.flush()
    return i.id


def _contract(s, iid: str, under: str, multiplier: int = 100, deleted: bool = False) -> None:
    s.add(OptionContract(id=ids.new_id("OptCt"), instrumentId=iid, underlyingId=under,
                         right="call", strike=D(480), expiry=d(2026, 12, 18),
                         multiplier=multiplier, deletedAt=_gone(deleted)))  # fmt: skip
    s.flush()


def _trade(s, account: str, iid: str, day, price, kind="buy", quantity=1, deleted=False):
    s.add(Transaction(id=ids.new_id("Txn"), accountId=account, date=day, kind=kind,
                      amount=-D(price) * quantity if kind == "buy" else D(0), instrumentId=iid,
                      quantity=D(quantity), price=None if price is None else D(price),
                      deletedAt=_gone(deleted)))  # fmt: skip
    s.flush()


def _statement(s, account: str, iid: str, day, quantity, value, deleted=False) -> None:
    s.add(Holding(id=ids.new_id("Hold"), accountId=account, instrumentId=iid, asOf=day,
                  quantity=D(quantity), marketValue=None if value is None else D(value),
                  deletedAt=_gone(deleted)))  # fmt: skip
    s.flush()


def _typed(s, owner: str, iid: str, day, close, deleted=False) -> None:
    s.add(TypedPrice(userId=owner, instrumentId=iid, date=day, close=D(close),
                     deletedAt=_gone(deleted)))  # fmt: skip
    s.flush()


def _close(s, iid: str, day, close) -> None:
    s.add(Price(instrumentId=iid, date=day, close=D(close), source="test"))
    s.flush()


def _symbol(s, symbol: str) -> str:
    return s.scalars(select(Instrument.id).where(Instrument.symbol == symbol)).one()


def _option(s, under: str, strike: int) -> str:
    return s.scalars(
        select(OptionContract.instrumentId).where(
            OptionContract.underlyingId == under, OptionContract.strike == strike
        )
    ).one()


def _prices(server, owner: str, iids: list[str], day) -> dict:
    with server.db.read(unscoped="test") as s:
        return valuation.prices(s, iids, day, owner=owner)


def _ledger(s, account_id: str):
    return repo.load(s, s.get(Account, account_id))


# ---------- a day's price, and a range of them ----------


def test_without_a_history_reader_a_range_is_its_first_days_close_carried(server):
    """Closes installed with a lookup alone: a range of prices reads the close standing on its
    first day and nothing after, and nothing fails for the reader that isn't there."""
    owner = make_user(server, "alice").id
    with server.db.tx(unscoped="test") as s:
        x = _instrument(s, "VTI")
        _close(s, x, sep(1), "100")
        _close(s, x, sep(5), "105")
    valuation.use_closes(pricing.stored_closes)
    with server.db.read(unscoped="test") as s:
        got = valuation.price_points(s, [x], sep(2), sep(10), owner=owner)
    assert got == {x: [(sep(2), D(100))]}


def test_typed_lists_the_owners_live_prices_after_first_up_to_last_oldest_first(server):
    """`typed`: only the instruments asked for, never a deleted price, after `first` (not on
    it) and up to `last` (on it too), or with no `first` every one up to `last`, oldest first
    whatever order they were typed in."""
    owner = make_user(server, "alice").id
    with server.db.tx(unscoped="test") as s:
        x, y = _instrument(s, "VTI"), _instrument(s, "VXUS")
        for day, close in ((5, "13"), (4, "12"), (3, "11"), (2, "10")):  # newest first
            _typed(s, owner, x, sep(day), close)
        _typed(s, owner, x, sep(6), "99", deleted=True)
        _typed(s, owner, y, sep(3), "50")
    with server.db.read(unscoped="test") as s:

        def got(first, last):
            return [(t.date.day, t.close) for t in valuation.typed(s, owner, [x], first, last)]

        assert got(None, sep(4)) == [(2, D(10)), (3, D(11)), (4, D(12))]
        assert got(sep(2), sep(6)) == [(3, D(11)), (4, D(12)), (5, D(13))]


def test_cash_and_money_market_are_worth_one_on_the_day_asked(server):
    """A cash or money-market instrument is priced 1, as of the day asked, labelled fixed."""
    owner = make_user(server, "alice").id
    with server.db.tx(unscoped="test") as s:
        cash, mm = _instrument(s, "USD", "cash"), _instrument(s, "SPAXX", "money-market")
    assert _prices(server, owner, [cash, mm], sep(9)) == {
        cash: P(D(1), sep(9), "fixed"),
        mm: P(D(1), sep(9), "fixed"),
    }


def test_a_typed_price_is_stale_once_older_than_90_days(server):
    """S4.7: a typed price, like a statement's value, is stale once older than 90 days; at 90
    days, or fresher, it is not."""
    owner = make_user(server, "alice").id
    ago = {90: None, 91: None, 1: None}
    with server.db.tx(unscoped="test") as s:
        for days in ago:
            ago[days] = _instrument(s, f"Z{days}")
            _typed(s, owner, ago[days], TODAY - dt.timedelta(days=days), "10")
    got = _prices(server, owner, list(ago.values()), TODAY)
    assert {days: (got[iid].source, got[iid].stale) for days, iid in ago.items()} == {
        90: ("manual", False),
        91: ("manual", True),
        1: ("manual", False),
    }
    assert all(type(p.stale) is bool for p in got.values())


def test_a_typed_price_wins_from_its_day_over_an_earlier_close(server):
    """S4.10: a price the owner typed stands from its day until the next close, in a day's
    price and in a range's points alike."""
    owner = make_user(server, "alice").id
    with server.db.tx(unscoped="test") as s:
        x = _instrument(s, "VTI")
        _close(s, x, sep(1), "100")
        _typed(s, owner, x, sep(5), "120")
        _close(s, x, sep(10), "110")
    before, on = _prices(server, owner, [x], sep(4))[x], _prices(server, owner, [x], sep(7))[x]
    assert (before.price, before.source) == (D(100), "close")
    assert (on.price, on.asOf, on.source) == (D(120), sep(5), "manual")
    with server.db.read(unscoped="test") as s:
        got = valuation.price_points(s, [x], sep(1), sep(12), owner=owner)
    assert got == {x: [(sep(1), D(100)), (sep(5), D(120)), (sep(10), D(110))]}


def test_a_single_days_price_reads_no_stored_history(server, monkeypatch):
    """A day's price takes the close standing on it alone; the stored history is read only
    for a range of days."""
    owner = make_user(server, "alice").id
    with server.db.tx(unscoped="test") as s:
        x = _instrument(s, "VTI")
        _close(s, x, sep(1), "100")
    asked = []

    def history(s, iids, first, last):
        asked.append((first, last))
        return pricing.close_history(s, iids, first, last)

    monkeypatch.setattr(valuation, "_history", [history])
    assert _prices(server, owner, [x], sep(5))[x].price == D(100)
    assert asked == []
    with server.db.read(unscoped="test") as s:
        valuation.price_points(s, [x], sep(1), sep(5), owner=owner)
    assert asked == [(sep(1), sep(5))]


def test_a_statement_prices_a_share_at_value_over_quantity_ahead_of_any_trade(server):
    """S4.7: a statement's value counts per share (its value over its quantity), and once
    reported it stands ahead of any trade, later ones too."""
    owner = make_user(server, "alice").id
    with server.db.tx(unscoped="test") as s:
        a, x = _account(s, owner), _instrument(s, "FUND")
        _trade(s, a, x, sep(1), "200")
        _statement(s, a, x, sep(5), "4", "1000")
        _trade(s, a, x, sep(8), "300")
    assert _prices(server, owner, [x], sep(3))[x] == P(D(200), sep(1), "trade")
    assert _prices(server, owner, [x], sep(6))[x] == P(D(250), sep(5), "statement")
    assert _prices(server, owner, [x], sep(9))[x] == P(D(250), sep(5), "statement")


def test_deleted_or_valueless_statements_and_deleted_trades_price_nothing(server):
    """A deleted statement, a statement line with no value, a deleted trade and another
    instrument's statement give the instrument asked for no price."""
    owner = make_user(server, "alice").id
    with server.db.tx(unscoped="test") as s:
        a, x, y = _account(s, owner), _instrument(s, "FUND"), _instrument(s, "OTHER")
        _trade(s, a, x, sep(1), "100")
        _statement(s, a, x, sep(5), "1", "500", deleted=True)
        _statement(s, a, x, sep(6), "2", None)
        _trade(s, a, x, sep(7), "999", deleted=True)
        _statement(s, a, y, sep(6), "1", "70")
    assert _prices(server, owner, [x], sep(10)) == {x: P(D(100), sep(1), "trade")}


def _every(s, account: str, interval: str) -> None:
    s.get(Account, account).statementInterval = interval
    s.flush()


def test_a_statements_value_is_stale_by_the_day_asked_not_by_today(server):
    """CR3-8: a quarterly plan's Mar 31 value is stale from Jul 30, the day its next statement
    is overdue; a figure for an earlier day saw it fresh, though it is stale today."""
    owner = make_user(server, "alice").id
    with server.db.tx(unscoped="test") as s:
        a, x = _account(s, owner), _instrument(s, "CIT")
        _every(s, a, "quarterly")
        _statement(s, a, x, d(2026, 3, 31), "10", "1000")
    assert _prices(server, owner, [x], d(2026, 7, 29))[x].stale is False
    assert _prices(server, owner, [x], d(2026, 7, 30))[x].stale is True
    assert _prices(server, owner, [x], TODAY)[x].stale is True


@pytest.mark.parametrize(("later", "stale"), [("monthly", True), ("quarterly", False)])
def test_two_accounts_statements_the_newer_values_it_by_its_own_accounts_interval(
    server, later, stale
):
    """The same fund in two of the owner's accounts: the newer statement's value counts, and
    whether it is stale is its own account's interval's to say (Aug 31: monthly, stale from
    Oct 15, today; quarterly, from Dec 30)."""
    owner = make_user(server, "alice").id
    with server.db.tx(unscoped="test") as s:
        a, b, x = _account(s, owner), _account(s, owner), _instrument(s, "SHARED")
        _every(s, a, "quarterly")
        _every(s, b, later)
        _statement(s, a, x, d(2026, 6, 30), "10", "1000")
        _statement(s, b, x, d(2026, 8, 31), "10", "1100")
    assert _prices(server, owner, [x], TODAY)[x] == P(D(110), d(2026, 8, 31), "statement", stale)


@pytest.mark.parametrize("newer", ["typed", "close"])
def test_a_typed_price_or_a_close_after_a_stale_statement_values_it_instead(server, newer):
    """A stale statement's value gives way to a later typed price or a close, neither stale:
    nothing is left valued from the old statement, so no alert either."""
    owner = make_user(server, "alice").id
    with server.db.tx(unscoped="test") as s:
        a, x = _account(s, owner), _instrument(s, "CIT")
        _every(s, a, "quarterly")
        _statement(s, a, x, d(2026, 3, 31), "10", "1000")
        if newer == "typed":
            _typed(s, owner, x, d(2026, 10, 1), "104")
        else:
            _close(s, x, d(2026, 10, 14), "104")
    got = _prices(server, owner, [x], TODAY)[x]
    assert (got.price, got.source, got.stale) == (
        D(104),
        "manual" if newer == "typed" else "close",
        False,
    )


def test_a_statement_line_of_no_shares_prices_nothing(server):
    """A position the statement lists at zero shares (sold in the period) gives no price, and
    no division by zero: the earlier line's value stands."""
    owner = make_user(server, "alice").id
    with server.db.tx(unscoped="test") as s:
        a, x = _account(s, owner), _instrument(s, "SOLD")
        _statement(s, a, x, sep(5), "2", "500")
        _statement(s, a, x, sep(6), "0", "0")
    assert _prices(server, owner, [x], sep(10))[x] == P(D(250), sep(5), "statement")


def test_a_trade_on_the_day_asked_prices_it(server):
    """The owner's last trade prices an instrument with nothing else, a trade on the day asked
    included."""
    owner = make_user(server, "alice").id
    with server.db.tx(unscoped="test") as s:
        a, x = _account(s, owner), _instrument(s, "PRIV")
        _trade(s, a, x, sep(1), "100")
        _trade(s, a, x, sep(4), "120")
    assert _prices(server, owner, [x], sep(4))[x] == P(D(120), sep(4), "trade")


def test_tiers_stop_at_last_and_fetch_no_statement_or_trade_once_a_close_stands(server):
    """`_tiers`: an instrument's points go no later than `last`; a fixed instrument's one point
    is in the first tier; and statements and trades are read only for an instrument with no
    close or typed price on or before `first`."""
    owner = make_user(server, "alice").id
    with server.db.tx(unscoped="test") as s:
        a = _account(s, owner)
        x, y = _instrument(s, "LOOSE"), _instrument(s, "CLOSED")
        cash = _instrument(s, "USD", "cash")
        for iid in (x, y):
            _statement(s, a, iid, sep(2), "1", "50")
            _trade(s, a, iid, sep(3), "60")
            _statement(s, a, iid, sep(20), "1", "70")
            _trade(s, a, iid, sep(20), "80")
        _close(s, y, sep(5), "100")
    with server.db.read(unscoped="test") as s:
        got = valuation._tiers(s, [x, y, cash], sep(5), sep(10), owner)
    assert got[x] == [
        [],
        [P(D(50), sep(2), "statement")],
        [P(D(60), sep(3), "trade")],
    ]
    assert got[y] == [[P(D(100), sep(5), "close")], [], []]
    assert got[cash] == [[P(D(1), dt.date.min, "fixed")], [], []]


def test_effective_is_the_last_point_by_the_day_of_the_first_tier_with_one():
    """`_effective`: a later point in a tier doesn't hide its earlier one; a tier with nothing
    by the day passes to the next; a fixed price is dated the day asked."""
    tiers = [
        [P(D(1), sep(1), "close"), P(D(2), sep(9), "close")],
        [P(D(5), sep(2), "statement")],
    ]
    assert valuation._effective(tiers, sep(5)) == P(D(1), sep(1), "close")
    assert valuation._effective([[P(D(2), sep(9), "close")], tiers[1]], sep(5)) == tiers[1][0]
    assert valuation._effective(tiers, d(2026, 8, 31)) is None
    fixed = [[P(D(1), dt.date.min, "fixed")], [], []]
    assert valuation._effective(fixed, sep(5)) == P(D(1), sep(5), "fixed")


def test_the_markets_closes_are_none_without_a_lookup():
    """`closes`: with no stored closes installed there are none, for any instrument."""
    valuation._closes[:] = []
    assert valuation.closes(None, ["I1"], sep(5)) == {}
    assert valuation.closes(None, [], sep(5)) == {}


def test_a_range_keeps_only_the_days_its_price_changes(server):
    """`price_points`: a close at the same price as the one before adds no point."""
    owner = make_user(server, "alice").id
    with server.db.tx(unscoped="test") as s:
        x = _instrument(s, "VTI")
        for day, close in ((1, "100"), (2, "100"), (3, "101"), (4, "101"), (5, "100")):
            _close(s, x, sep(day), close)
    with server.db.read(unscoped="test") as s:
        got = valuation.price_points(s, [x], sep(1), sep(6), owner=owner)
    assert got == {x: [(sep(1), D(100)), (sep(3), D(101)), (sep(5), D(100))]}


def test_multipliers_name_only_the_live_contracts_asked_for(server):
    """`multipliers`: the contracts of the instruments asked for, never a deleted one; a stock
    isn't among them."""
    with server.db.tx(unscoped="test") as s:
        under = _instrument(s, "MSFT")
        a, b, gone = (_instrument(s, f"MSFT C{k}", "option") for k in range(3))
        _contract(s, a, under)
        _contract(s, b, under, multiplier=10)
        _contract(s, gone, under, deleted=True)
    with server.db.read(unscoped="test") as s:
        assert valuation.multipliers(s, [a, gone, under]) == {a: 100}


# ---------- holdings and an account's value ----------


@pytest.fixture
def alice(server):
    make_user(server, "alice")
    return sign_in(server, "alice")


def test_an_options_mark_stands_and_its_intrinsic_value_is_the_days(server, alice):
    """S3.7: an option the owner typed a mark for is valued at it, never at its intrinsic
    value; one with no mark at its intrinsic value at the underlying's price on the day asked,
    dated as that price is."""
    a = new_account(alice, name="Options", type="brokerage", openingBalance="0.00",
                    openingDate="2026-01-01")  # fmt: skip
    saved(create(alice, "Txn", accountId=a["id"], date="2026-09-01", kind="buy", symbol="MSFT",
                 quantity="10", price="500", amount="-5000.00"))  # fmt: skip
    for right, strike in (("call", "480"), ("put", "520")):
        saved(option_trade(alice, a["id"], "2026-09-02", "buy-to-open", "MSFT", right, strike,
                           "2026-12-18", 1, "5.00"))  # fmt: skip
    with server.db.tx(unscoped="test") as s:
        owner = s.get(Account, a["id"]).ownerId
        msft = _symbol(s, "MSFT")
        call, put = _option(s, msft, 480), _option(s, msft, 520)
        _typed(s, owner, msft, sep(10), "510")
        _typed(s, owner, msft, d(2026, 10, 10), "600")
        _typed(s, owner, put, sep(15), "7.5")
    with server.db.read(unscoped="test") as s:
        got = {p.instrumentId: p for p in valuation.positions(s, _ledger(s, a["id"]), sep(20))}
    assert got[call].price == P(D(30), sep(10), "intrinsic")
    assert got[put].price == P(D("7.5"), sep(15), "manual")
    assert got[call].value == D("3000.00") and got[put].value == D("750.00")


def _traded(server, alice):
    """A brokerage account: $100,000 in on 2 January; a call bought on 2 September (marked
    $6 from then), 10 MSFT bought at $500 on 3 September (typed $510 from the 10th), sold on
    the 20th."""
    a = new_account(alice, name="Brokerage", type="brokerage", openingBalance="0.00",
                    openingDate="2026-01-01")  # fmt: skip
    add(alice, a["id"], "100000.00", "2026-01-02", kind="deposit")
    saved(option_trade(alice, a["id"], "2026-09-02", "buy-to-open", "MSFT", "call", "480",
                       "2026-12-18", 1, "5.00"))  # fmt: skip
    for day, kind, amount in (("03", "buy", "-5000.00"), ("20", "sell", "5200.00")):
        price = "500" if kind == "buy" else "520"
        saved(create(alice, "Txn", accountId=a["id"], date=f"2026-09-{day}", kind=kind,
                     symbol="MSFT", quantity="10", price=price, amount=amount))  # fmt: skip
    with server.db.tx(unscoped="test") as s:
        owner = s.get(Account, a["id"]).ownerId
        msft = _symbol(s, "MSFT")
        _typed(s, owner, _option(s, msft, 480), sep(2), "6")
        _typed(s, owner, msft, sep(10), "510")
    return a["id"]


def test_a_series_is_daily_with_options_by_default_and_counts_their_shares(server, alice):
    """`series` with no step or options given: a point every day, options counted at their
    100 shares a contract; positions are those of each day, not today's."""
    a = _traded(server, alice)
    with server.db.read(unscoped="test") as s:
        got = valuation.series(s, _ledger(s, a), True, sep(5), sep(12))
    # Cash 94,500; MSFT 10 x 500 then x 510 from the 10th; the call 1 x 6 x 100.
    assert got == [(sep(k), D(100100) if k < 10 else D(100200)) for k in range(5, 13)]


def test_a_series_without_options_leaves_them_out_and_keeps_its_step(server, alice):
    """`series` without options counts every other holding, whatever order they are held in;
    a step of 2 takes every other day, and the last."""
    a = _traded(server, alice)
    with server.db.read(unscoped="test") as s:
        led = _ledger(s, a)
        assert next(iter(led.replay(sep(12)).positions())) != _symbol(s, "MSFT"), "option first"
        got = valuation.series(s, led, True, sep(5), sep(12), 2, options=False)
    assert got == [(sep(5), D(99500)), (sep(7), D(99500)), (sep(9), D(99500)),
                   (sep(11), D(99600)), (sep(12), D(99600))]  # fmt: skip


def test_a_series_counts_a_trade_on_its_last_day(server, alice):
    """A trade on the window's last day changes what is held on it."""
    a = _traded(server, alice)
    with server.db.read(unscoped="test") as s:
        got = valuation.series(s, _ledger(s, a), True, sep(1), sep(3))
    assert got == [(sep(1), D(100000)), (sep(2), D(100100)), (sep(3), D(100100))]


def test_a_window_that_ends_before_it_begins_has_no_points(server, alice):
    """A series asked from a day after its last (an account whose history starts in the
    future) has no points, step 1 or more."""
    a = _traded(server, alice)
    with server.db.read(unscoped="test") as s:
        led = _ledger(s, a)
        assert valuation.series(s, led, True, sep(12), sep(5)) == []
        assert valuation.series(s, led, False, sep(12), sep(5)) == []


def test_a_snapshot_account_holds_each_statements_positions_to_the_last_day(server, alice):
    """An account kept by statements (R3.2) holds, from `first`, what its last statement
    before then reported, even with an earlier transaction on the instrument; a statement on
    the window's last day counts on it."""
    a = new_account(alice, name="Kept", type="brokerage", openingBalance="0.00",
                    openingDate="2026-01-01")  # fmt: skip
    add(alice, a["id"], "10000.00", "2026-01-02", kind="deposit")
    add(alice, a["id"], "50.00", "2026-08-01", kind="dividend", symbol="MSFT")
    with server.db.tx(unscoped="test") as s:
        msft = _symbol(s, "MSFT")
        _statement(s, a["id"], msft, sep(1), "10", "5000")
        _statement(s, a["id"], msft, sep(12), "20", "10000")
    with server.db.read(unscoped="test") as s:
        got = valuation.series(s, _ledger(s, a["id"]), True, sep(5), sep(12))
    assert got == [(sep(k), D(15050)) for k in range(5, 12)] + [(sep(12), D(20050))]


def test_a_loans_series_of_one_day_and_its_last_point_owe_what_was_owed_then(server, alice):
    """A loan's series over one day has that day's point; its last point, off the step, owes
    what was owed that day, not after a later payment."""
    loan = new_account(alice, name="HELOC", type="mortgage")
    saved(terms(alice, loan["id"], principal="100000", startDate="2026-01-01", termMonths=120,
                rate="0"))  # fmt: skip
    add(alice, loan["id"], "10000.00", "2026-02-15", kind="deposit")
    with server.db.read(unscoped="test") as s:
        led = _ledger(s, loan["id"])
        assert valuation.series(s, led, True, d(2026, 1, 10), d(2026, 1, 10)) == [
            (d(2026, 1, 10), D(-100000))
        ]
        got = valuation.series(s, led, True, d(2026, 1, 1), d(2026, 1, 25), 7)
    assert got[-1] == (d(2026, 1, 25), D(-100000))


def test_an_items_series_keeps_its_step(server, alice):
    """An item account's series takes the step asked for, and the last day."""
    coll = new_account(alice, name="Collectables", type="collectables")
    make(alice, "Item", accountId=coll["id"], name="Coin", acquiredOn="2026-02-01",
         costBasis="1000")  # fmt: skip
    with server.db.read(unscoped="test") as s:
        got = valuation.series(s, _ledger(s, coll["id"]), True, d(2026, 1, 31), d(2026, 2, 22), 5)
    assert [x for x, _ in got] == [d(2026, 1, 31), d(2026, 2, 5), d(2026, 2, 10),
                                   d(2026, 2, 15), d(2026, 2, 20), d(2026, 2, 22)]  # fmt: skip


# ---------- the money moved in and out ----------


def test_a_days_flows_add_up(server, alice):
    """Money in and out on the same day nets to one flow (CR3-28)."""
    loan = new_account(alice, name="HELOC", type="mortgage")
    saved(terms(alice, loan["id"], principal="300000", startDate="2026-01-01", termMonths=360,
                rate="6"))  # fmt: skip
    add(alice, loan["id"], "2000.00", "2026-07-01", kind="deposit")
    add(alice, loan["id"], "-500.00", "2026-07-01", kind="withdrawal")
    with server.db.read(unscoped="test") as s:
        got = valuation.flows(s, _ledger(s, loan["id"]), False, d(2026, 6, 1), d(2026, 7, 31))
    assert got == {d(2026, 7, 1): D("1500.00")}


def test_options_moved_in_count_their_shares_at_that_days_price(server):
    """CR3-28: contracts moved in count at the price the series takes for them on the day of
    the move (a mark typed that day included), times their 100 shares a contract."""
    owner = make_user(server, "alice").id
    with server.db.tx(unscoped="test") as s:
        a, under = _account(s, owner), _instrument(s, "MSFT")
        call = _instrument(s, "MSFT C480", "option")
        _contract(s, call, under)
        _typed(s, owner, call, sep(5), "3")
        _typed(s, owner, call, sep(10), "4")
        _trade(s, a, call, sep(10), None, kind="transfer-in", quantity=2)
    with server.db.read(unscoped="test") as s:
        got = valuation.flows(s, _ledger(s, a), True, sep(1), sep(30))
    assert got == {sep(10): D("800.00")}
