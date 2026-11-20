"""The lot ledger at its edges, on plain objects (no database): a lot of one share or less, a
lot already emptied, the last of several taking what rounding leaves, a step that must stop
once its quantity is used up, a basis missing part way, wash-sale replacements, and what a
problem or a sale part names. Each test names the rule; the mutation run found them unchecked."""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
from test_ledger import Lot, Pick, Snap, book, replay, sell
from test_lot_rules import T, at, old_and_new, opt, sold

from moolakata.ledger import lots

d = dt.date


@dataclass
class W:
    """A wash sale (S3.8): the loss sale, its replacement buy, how many shares it covers, the
    loss disallowed and the sold shares' day bought."""

    id: str
    saleId: str
    replacementId: str
    quantity: D
    disallowed: D
    heldFrom: dt.date
    lotId: str | None = None


def kept(r):
    return [(x.lotId, x.instrumentId, x.quantity, x.basis, x.heldFrom) for x in r.open]


# -- Wash sales (S3.8) ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("account_type", "adds"),
    [("ira", False), ("roth-ira", False), ("brokerage", True), ("taxable", True)],
)
def test_only_an_ira_or_a_roth_ira_loses_the_disallowed_loss_for_good(account_type, adds):
    """S3.8.3: a replacement in an IRA or a Roth IRA takes no basis (Rev. Rul. 2008-5)."""
    assert lots.adds_basis(account_type) is adds


def test_wash_sales_on_one_buy_take_its_lots_in_turn():
    """Two wash sales replaced by one buy of two lots (S3.8.2): the first takes the one-share
    lot, the second the next lot, never the emptied one; each part takes its own loss into its
    basis and its sold shares' day bought."""
    buy = T(d(2025, 3, 5), "buy", D(-150), "VTI", D(3), createdAt=at(1))
    made = [
        Lot("RA", "VTI", d(2025, 3, 5), D(1), D(50), transactionId=buy.id),
        Lot("RB", "VTI", d(2025, 3, 5), D(2), D(100), transactionId=buy.id),
    ]
    washes = [
        W("W1", "S1", buy.id, D(1), D(30), d(2024, 1, 1)),
        W("W2", "S2", buy.id, D(2), D(40), d(2024, 2, 1)),
    ]
    r = replay("fifo", [buy], made, [], [], washes=washes)
    assert kept(r) == [
        ("RA", "VTI", D(1), D(80), d(2024, 1, 1)),
        ("RB", "VTI", D(2), D(140), d(2024, 2, 1)),
    ]


def test_a_replacement_without_a_basis_keeps_it_missing_and_takes_the_day():
    """A replacement whose basis is missing (S2.2) still takes the sold shares' day bought; no
    basis is made up for it."""
    buy = T(d(2025, 3, 5), "buy", D(0), "VTI", D(10), createdAt=at(1))
    made = [Lot("R", "VTI", d(2025, 3, 5), D(10), None, transactionId=buy.id, basisMissing=True)]
    washes = [W("W1", "S1", buy.id, D(10), D(300), d(2024, 1, 1))]
    r = replay("fifo", [buy], made, [], [], washes=washes)
    assert kept(r) == [("R", "VTI", D(10), None, d(2024, 1, 1))]


def test_a_replacement_partly_sold_before_the_loss_sale_takes_its_share_of_the_loss():
    """S3.8.3: a replacement bought before the loss sale is a plain lot until then; four of its
    ten sold in between go at their own basis, and the six left take 6/10 of the loss."""
    old = Lot("A", "VTI", d(2024, 1, 2), D(10), D(1000))
    buy = T(d(2025, 3, 1), "buy", D(-500), "VTI", D(10), createdAt=at(1))
    made = [Lot("R", "VTI", d(2025, 3, 1), D(10), D(500), transactionId=buy.id)]
    early = T(d(2025, 3, 5), "sell", D(220), "VTI", D(-4), lotMethod="lifo", createdAt=at(2))
    loss = T(d(2025, 3, 10), "sell", D(700), "VTI", D(-10), createdAt=at(3))
    wash = W("W1", loss.id, buy.id, D(10), D(300), d(2024, 1, 2))
    r = replay("fifo", [buy, early, loss], [old, *made], [], [], washes=[wash],
                    sale_at={loss.id: (loss.date, loss.createdAt)})  # fmt: skip
    assert sold(r) == [("R", D(4), D(220), D(200), "lifo"), ("A", D(10), D(700), D(1000), "fifo")]
    assert [x.gain for x in r.disposals] == [D(20), D(0)]
    assert kept(r) == [("R", "VTI", D(6), D(480), d(2024, 1, 2))]


def _bought_back(early: bool):
    """A loss of $300 on ten shares of lot A, replaced by a buy of ten (S3.8): bought before the
    loss sale (`early`) or after it, the sale's day and making known."""
    old = Lot("A", "VTI", d(2024, 1, 2), D(10), D(1000))
    loss = T(d(2025, 3, 10), "sell", D(700), "VTI", D(-10), createdAt=at(2))
    day = d(2025, 3, 1) if early else d(2025, 3, 20)
    buy = T(day, "buy", D(-500), "VTI", D(10), createdAt=at(1 if early else 3))
    made = [Lot("R", "VTI", day, D(10), D(500), transactionId=buy.id)]
    wash = W("W1", loss.id, buy.id, D(10), D(300), d(2024, 1, 2))
    return loss, buy, [old, *made], wash


def test_a_replacement_bought_after_its_loss_sale_takes_the_loss_when_bought():
    """S3.8.3: the sale has passed by the buy, so the replacement opens with the loss in its
    basis and the sold shares' day."""
    loss, buy, made, wash = _bought_back(early=False)
    r = replay("fifo", [loss, buy], made, [], [], washes=[wash],
               sale_at={loss.id: (loss.date, loss.createdAt)})  # fmt: skip
    assert kept(r) == [("R", "VTI", D(10), D(800), d(2024, 1, 2))]


def test_a_wash_sale_settles_before_what_is_made_after_its_loss_sale_that_day():
    """S3.8.3: a replacement bought before the loss sale takes the loss from the sale on, so a
    sale of four of it later that same day sells them at the adjusted basis, held from the
    sold shares' day."""
    loss, buy, made, wash = _bought_back(early=True)
    later = T(loss.date, "sell", D(220), "VTI", D(-4), createdAt=at(3))
    r = replay("fifo", [buy, loss, later], made, [], [], washes=[wash],
               sale_at={loss.id: (loss.date, loss.createdAt)})  # fmt: skip
    assert sold(r) == [("A", D(10), D(700), D(1000), "fifo"), ("R", D(4), D(220), D(320), "fifo")]
    assert r.disposals[1].heldFrom == d(2024, 1, 2)
    assert kept(r) == [("R", "VTI", D(6), D(480), d(2024, 1, 2))]


def _part(lot_id, proceeds, basis, sale="S"):
    """One share of a sale from a lot, at a gain or a loss (no basis: missing)."""
    return lots.Disposal(sale, lot_id, "VTI", d(2024, 1, 2), d(2025, 3, 10), D(1), D(proceeds),
                         None if basis is None else D(basis), "fifo")  # fmt: skip


def test_a_lots_disallowed_loss_goes_on_its_losing_parts_by_loss_the_last_taking_the_rest():
    """S3.8.2: the loss disallowed is the sold lot's, two wash sales of it adding up. A lot a
    wash sale split sells in parts: $10 over three equal losses is 3.33, 3.33 and 3.34. Its
    part at a gain, even under a dollar, or with its basis missing has no loss to take any;
    another lot's part and another sale's keep their own."""
    out = lots.Replay()
    out.disposals = [
        _part("A", 90, 100),
        _part("A", "100.50", 100),
        _part("A", 90, None),
        _part("B", 60, 100),
        _part("A", 90, 100),
        _part("A", 80, 100, sale="S2"),
        _part("A", 90, 100),
    ]
    washes = [W("W1", "S", "R", D(1), D(4), d(2024, 1, 2), lotId="A"),
              W("W2", "S", "R", D(2), D(6), d(2024, 1, 2), lotId="A")]  # fmt: skip
    lots._disallow(out, washes)
    assert [x.adjustment for x in out.disposals] == [
        D("3.33"), 0, 0, 0, D("3.33"), 0, D("3.34")
    ]  # fmt: skip


# -- Return of capital (S2.4) ----------------------------------------------------------------


def test_a_return_of_capital_spreads_over_the_instruments_lots_held_by_quantity():
    """Over every lot of the instrument still held, one share each here, by quantity, the last
    taking what rounding leaves; a lot without a basis keeps its share, and the next lot still
    takes its own. A lot already sold and another instrument's lot take none."""
    made = [
        Lot("A", "VTI", d(2024, 1, 1), D(1), None, basisMissing=True),
        Lot("E", "VXUS", d(2024, 1, 1), D(1), D(100)),
        Lot("B", "VTI", d(2024, 1, 2), D(1), D(100)),
        Lot("C", "VTI", d(2024, 1, 3), D(1), D(100)),
        Lot("Z", "VTI", d(2024, 1, 4), D(1), D(100)),
    ]
    sale = T(d(2025, 2, 1), "sell", D(100), "VTI", D(-1), lotMethod="lifo", createdAt=at(1))
    roc = T(d(2025, 3, 1), "return-of-capital", D(100), "VTI", createdAt=at(2))
    r = replay("fifo", [sale, roc], made, [], [])
    assert [(x.lotId, x.basis) for x in r.open] == [
        ("A", None), ("E", D(100)), ("B", D("66.67")), ("C", D("66.66"))
    ]  # fmt: skip
    assert sold(r) == [("Z", D(1), D(100), D(100), "lifo")]


@pytest.mark.parametrize(
    ("amount", "gains"),
    [(D(100), []), (D("100.50"), [(None, D(0), D("0.50"), D(0), "return-of-capital")])],
)
def test_a_return_of_capital_is_a_gain_only_past_the_basis(amount, gains):
    """What exceeds a lot's basis is a capital gain (IRS Pub. 550), even under a dollar; up to
    the basis, none."""
    made = [Lot("A", "VTI", d(2024, 1, 1), D(10), D(100))]
    roc = T(d(2025, 3, 1), "return-of-capital", amount, "VTI")
    r = replay("fifo", [roc], made, [], [])
    assert [(x.lotId, x.basis) for x in r.open] == [("A", D(0))]
    assert [(None, *x[1:]) for x in sold(r)] == gains


def test_a_return_of_capital_of_nothing_changes_no_lot():
    """Even a lot whose basis is below zero (a put's credit past the shares' cost, S3.4) keeps
    it, and nothing is a gain."""
    made = [Lot("A", "VTI", d(2024, 1, 1), D(10), D(-50))]
    roc = T(d(2025, 3, 1), "return-of-capital", D(0), "VTI")
    r = replay("fifo", [roc], made, [], [])
    assert [(x.lotId, x.basis) for x in r.open] == [("A", D(-50))] and r.disposals == []


# -- Corporate actions (S2.4) ----------------------------------------------------------------


@pytest.mark.parametrize("qty", [D(1), D("0.5")])
def test_a_symbol_change_carries_a_lot_of_one_share_or_less(qty):
    made = [Lot("A", "OLD", d(2024, 1, 1), qty, D(100))]
    old, nxt = old_and_new("symbol-change")
    r = replay("fifo", [old, nxt], made, [], [])
    assert kept(r) == [("A", "NEW", qty, D(100), None)]


def test_a_symbol_changes_cash_is_no_part_of_the_lots():
    """Only a merger's old leg pays cash that can be a gain (IRC §356); a symbol change's
    amount leaves the lots whole."""
    made = [Lot("A", "OLD", d(2024, 1, 1), D(10), D(1000))]
    old, nxt = old_and_new("symbol-change", cash=D(5))
    r = replay("fifo", [old, nxt], made, [], [])
    assert kept(r) == [("A", "NEW", D(10), D(1000), None)] and r.disposals == []


def test_a_new_leg_without_its_old_one_carries_nothing():
    nxt = T(d(2026, 5, 1), "symbol-change", D(0), "NEW", D(10), transferId="gone")
    r = replay("fifo", [nxt], [], [], [])
    assert r.open == [] and r.disposals == [] and r.problems == []


# -- Options to their end (S3.3, S3.4) ---------------------------------------------------------


def _two_longs():
    return [
        opt(d(2026, 1, 5), "buy-to-open", "-100", 1, 1),
        opt(d(2026, 1, 6), "buy-to-open", "-200", 1, 2),
    ]


@pytest.mark.parametrize(
    ("end", "want"),
    [
        (
            opt(d(2026, 2, 1), "sell-to-close", "150", -1, 3),
            [(d(2026, 1, 5), D(1), D(150), D(100), "fifo")],
        ),
        (
            opt(d(2026, 3, 20), "expire", "0", -2, 3),
            [
                (d(2026, 1, 5), D(1), D(0), D(100), "fifo"),
                (d(2026, 1, 6), D(1), D(0), D(200), "fifo"),
            ],
        ),
    ],
)
def test_option_closes_and_expiries_go_oldest_first_whatever_is_picked(end, want):
    """S3.3: closing trades and expiries take an option's lots oldest first, whatever lot method
    is used for shares; a lot picked for one changes neither the order nor the method."""
    r = replay("fifo", [*_two_longs(), end], [], [Pick(end.id, "X", D(1))], [])
    assert [(x.acquiredOn, x.quantity, x.proceeds, x.basis, x.method) for x in r.disposals] == want


def test_an_assignment_takes_its_shorts_oldest_first_and_stops_when_done():
    """Three of six short contracts assigned (S3.4): two from the oldest, one from the next,
    the third untouched though its basis is missing; the shares bought take the premium of the
    three, and the contract left part way keeps the rest of its credit."""
    put1 = opt(d(2026, 1, 5), "sell-to-open", "300", -2, 1)
    put2 = opt(d(2026, 1, 6), "sell-to-open", "600", -3, 2)
    third = Lot("P3", "OPT", d(2026, 1, 7), D(-1), None, basisMissing=True)
    end = opt(d(2026, 3, 20), "assign", "0", 3, 4)
    leg = T(d(2026, 3, 20), "buy", D(-15000), "VTI", D(300), createdAt=at(3),
            optionTransactionId=end.id)  # fmt: skip
    made = [Lot("S", "VTI", d(2026, 3, 20), D(300), D(15000), transactionId=leg.id)]
    r = replay("fifo", [put1, put2, leg, end], [third, *made], [], [])
    assert [(x.lotId, x.instrumentId, x.quantity, x.basis) for x in r.open] == [
        (None, "OPT", D(-2), D(-400)),
        ("P3", "OPT", D(-1), None),
        ("S", "VTI", D(300), D(14500)),
    ]
    assert r.disposals == []


def test_an_assignment_with_a_basis_missing_leaves_its_shares_basis_missing():
    """S3.4: the premium is worked out from the option's lots; with one of them missing its
    basis, every stock trade made with the assignment has its basis missing too."""
    missing = Lot("P0", "OPT", d(2026, 1, 5), D(-1), None, basisMissing=True)
    put = opt(d(2026, 1, 6), "sell-to-open", "200", -1, 1)
    end = opt(d(2026, 3, 20), "assign", "0", 2, 4)
    a = T(d(2026, 3, 20), "buy", D(-3000), "AAA", D(100), createdAt=at(2),
          optionTransactionId=end.id)  # fmt: skip
    b = T(d(2026, 3, 20), "buy", D(-1000), "BBB", D(50), createdAt=at(3),
          optionTransactionId=end.id)  # fmt: skip
    made = [Lot("A", "AAA", d(2026, 3, 20), D(100), D(3000), transactionId=a.id),
            Lot("B", "BBB", d(2026, 3, 20), D(50), D(1000), transactionId=b.id)]  # fmt: skip
    r = replay("fifo", [put, a, b, end], [missing, *made], [], [])
    assert [(x.instrumentId, x.basis) for x in r.open] == [("AAA", None), ("BBB", None)]


@pytest.mark.parametrize(("size", "exercised"), [(D(2), D(1)), (D("0.5"), D("0.25"))])
def test_an_exercised_long_gives_up_the_contracts_exercised(size, exercised):
    """A long call exercised (S3.4): the lot gives up what is exercised, whatever its size (an
    adjusted contract can hold a fraction, S3.10), and its share of the premium goes into the
    shares' basis."""
    call = opt(d(2026, 1, 5), "buy-to-open", "-300", size, 1)
    end = opt(d(2026, 3, 20), "exercise", "0", -exercised, 3)
    leg = T(d(2026, 3, 20), "buy", D(-5000), "VTI", D(100), createdAt=at(2),
            optionTransactionId=end.id)  # fmt: skip
    made = [Lot("S", "VTI", d(2026, 3, 20), D(100), D(5000), transactionId=leg.id)]
    r = replay("fifo", [call, leg, end], made, [], [])
    assert [(x.instrumentId, x.quantity, x.basis) for x in r.open] == [
        ("OPT", size - exercised, D(150)),
        ("VTI", D(100), D(5150)),
    ]


def test_an_assignment_with_no_stock_trade_closes_the_contract():
    """A contract assigned whose stock trade isn't in yet: the contract is closed, with no gain
    of its own, and its premium waits for no one."""
    put = opt(d(2026, 1, 5), "sell-to-open", "200", -1, 1)
    r = replay("fifo", [put, opt(d(2026, 3, 20), "assign", "0", 1, 2)], [], [], [])
    assert r.open == [] and r.disposals == [] and r.problems == []


def test_an_assignments_premium_over_three_stock_trades_the_last_taking_the_rounding():
    """S3.10.4: by each trade's cash, $100 over three equal trades is 33.33, 33.33 and 33.34."""
    put = opt(d(2026, 1, 5), "sell-to-open", "100", -1, 1)
    end = opt(d(2026, 3, 20), "assign", "0", 1, 5)
    legs = [
        T(d(2026, 3, 20), "buy", D(-1000), sym, D(10), createdAt=at(n), optionTransactionId=end.id)
        for n, sym in ((2, "AAA"), (3, "BBB"), (4, "CCC"))
    ]
    made = [Lot(f"L{x.instrumentId}", x.instrumentId, x.date, D(10), D(1000), transactionId=x.id)
            for x in legs]  # fmt: skip
    r = replay("fifo", [put, *legs, end], made, [], [])
    assert [(x.instrumentId, x.basis) for x in r.open] == [
        ("AAA", D("966.67")), ("BBB", D("966.67")), ("CCC", D("966.66"))
    ]  # fmt: skip


# -- Closing shorts (S3.3) ---------------------------------------------------------------------


def test_a_close_takes_only_open_shorts_and_stops_when_done():
    """A short already closed is passed over; once the close is used up, the next short is left
    as it is, with no sale part of nothing."""
    r = replay("fifo", [
        opt(d(2026, 1, 5), "sell-to-open", "100", -1, 1),
        opt(d(2026, 1, 6), "buy-to-close", "-50", 1, 2),
        opt(d(2026, 1, 7), "sell-to-open", "100", -1, 3),
        opt(d(2026, 1, 8), "sell-to-open", "100", -1, 4),
        opt(d(2026, 1, 9), "buy-to-close", "-30", 1, 5),
    ], [], [], [])  # fmt: skip
    assert [(x.acquiredOn, x.quantity, x.proceeds, x.basis) for x in r.disposals] == [
        (d(2026, 1, 5), D(1), D(-50), D(-100)),
        (d(2026, 1, 7), D(1), D(-30), D(-100)),
    ]
    assert [(x.acquiredOn, x.quantity, x.basis) for x in r.open] == [
        (d(2026, 1, 8), D(-1), D(-100))
    ]


def test_a_close_shares_its_cost_by_quantity_the_last_taking_the_rounding():
    """$10.01 to close four contracts over shorts of two, one and one: 5.00, 2.50, and 2.51."""
    r = replay("fifo", [
        opt(d(2026, 1, 5), "sell-to-open", "200", -2, 1),
        opt(d(2026, 1, 6), "sell-to-open", "100", -1, 2),
        opt(d(2026, 1, 7), "sell-to-open", "100", -1, 3),
        opt(d(2026, 2, 1), "buy-to-close", "-10.01", 4, 4),
    ], [], [], [])  # fmt: skip
    assert [x.proceeds for x in r.disposals] == [D("-5.00"), D("-2.50"), D("-2.51")]


def test_a_short_without_a_basis_closes_with_its_basis_missing():
    short = Lot("P", "OPT", d(2026, 1, 5), D(-1), None, basisMissing=True)
    close = opt(d(2026, 2, 1), "buy-to-close", "-50", 1, 1)
    r = replay("fifo", [close], [short], [], [])
    assert sold(r) == [("P", D(1), D(-50), None, "fifo")] and r.disposals[0].gain is None


def test_a_partial_close_leaves_the_rest_of_the_credit_on_the_short():
    r = replay("fifo", [
        opt(d(2026, 1, 5), "sell-to-open", "300", -3, 1),
        opt(d(2026, 2, 1), "buy-to-close", "-40", 1, 2),
    ], [], [], [])  # fmt: skip
    assert sold(r) == [(None, D(1), D(-40), D(-100), "fifo")]
    assert [(x.quantity, x.basis) for x in r.open] == [(D(-2), D(-200))]


# -- Shares bought while short (S3.4) ---------------------------------------------------------


def _short():
    """Three shares short at $100 each, as an assignment with none held leaves them."""
    return Lot("SH", "VTI", d(2026, 1, 5), D(-3), D(-300))


def test_shares_bought_while_short_close_it_from_the_buys_lots_in_turn():
    """S3.4: seven bought for $140 in two lots while three are short: the three close the short
    at their share of the cost, taken from the first lot's two and then one of the second; the
    rest stay long at their basis."""
    buy = T(d(2026, 2, 1), "buy", D(-140), "VTI", D(7), createdAt=at(1))
    made = [Lot("B1", "VTI", buy.date, D(2), D(40), transactionId=buy.id),
            Lot("B2", "VTI", buy.date, D(5), D(100), transactionId=buy.id)]  # fmt: skip
    r = replay("fifo", [buy], [_short(), *made], [], [])
    assert sold(r) == [("SH", D(3), D(-60), D(-300), "fifo")]
    assert (r.disposals[0].short, r.disposals[0].gain) == (True, D(240))
    assert [(x.lotId, x.quantity, x.basis) for x in r.open] == [("B2", D(4), D(80))]


def test_a_buy_without_a_lot_of_its_own_closes_the_short_from_its_own_shares():
    """S3.4: the shares a buy opens itself close the short; a lot held before it, another
    instrument's here, keeps all of its own."""
    other = Lot("X", "VXUS", d(2026, 1, 6), D(10), D(500))
    buy = T(d(2026, 2, 1), "buy", D(-140), "VTI", D(7), createdAt=at(1))
    r = replay("fifo", [buy], [_short(), other], [], [])
    assert sold(r) == [("SH", D(3), D(-60), D(-300), "fifo")]
    assert [(x.lotId, x.instrumentId, x.quantity, x.basis) for x in r.open] == [
        ("X", "VXUS", D(10), D(500)), (None, "VTI", D(4), D(80))
    ]  # fmt: skip


def test_a_buy_without_a_quantity_closes_no_short():
    """A file's buy can come without its shares (S1.3.2): it opens nothing and closes nothing."""
    buy = T(d(2026, 2, 1), "buy", D(-140), "VTI", None, createdAt=at(1))
    r = replay("fifo", [buy], [_short()], [], [])
    assert r.disposals == [] and kept(r) == [("SH", "VTI", D(-3), D(-300), None)]


# -- What the replay is given, and the order of a day (S2.2, R3.2) ---------------------------------


def test_a_lot_without_its_transaction_is_refused_naming_it():
    lot = Lot("L9", "VTI", d(2025, 1, 2), D(1), D(10))
    with pytest.raises(
        ValueError, match=r"^lot L9 has no transaction: every lot is made by one \(S2\.2\)$"
    ):
        lots.replay("fifo", [], [lot], [], [])


def test_a_new_leg_comes_before_its_days_snapshot_though_the_snapshot_was_read_first():
    """An account kept by snapshots (R3.2) whose holding changes symbol: the new symbol's
    snapshot that day is at the day's end, after the pair, however early it was read in, so it
    finds the lots carried and nothing missing."""
    old, nxt = old_and_new("symbol-change")
    before = Snap("OLD", d(2026, 4, 30), D(10), id="H0", createdAt=at(0))
    after = Snap("NEW", nxt.date, D(10), id="H1", createdAt=at(0))
    r = replay("fifo", [old, nxt], [], [], [before, after])
    assert [(x.instrumentId, x.quantity, x.standIn) for x in r.open] == [("NEW", D(10), True)]
    assert [(p.instrumentId, p.date, p.quantity) for p in r.problems] == [
        ("OLD", d(2026, 4, 30), D(10))
    ]


def test_a_ratio_on_what_is_no_split_splits_nothing():
    """S2.4: only a split's ratio changes the shares held; a dividend with one leaves them."""
    made = [Lot("A", "VTI", d(2024, 1, 2), D(10), D(1000))]
    div = T(d(2025, 3, 1), "dividend", D(25), "VTI", splitRatio=D(2), createdAt=at(1))
    r = replay("fifo", [div], made, [], [])
    assert kept(r) == [("A", "VTI", D(10), D(1000), None)]


# -- What a problem or a sale part names (S8.4) -------------------------------------------------


def test_a_close_or_sale_with_nothing_to_take_names_its_transaction():
    close = opt(d(2026, 2, 1), "buy-to-close", "-50", 1, 1)
    sale = T(d(2026, 2, 1), "sell", D(90), "VTI", D(-3), createdAt=at(2))
    r = replay("fifo", [close, sale], [], [], [])
    assert [(p.kind, p.transactionId) for p in r.problems] == [
        ("close-without-open", close.id), ("sale-without-lot", sale.id)
    ]  # fmt: skip
    assert [(x.saleId, x.lotId, x.quantity, x.proceeds) for x in r.disposals] == [
        (sale.id, None, D(3), D(90))
    ]


# -- Holding snapshots (R3.2, S8.4) ------------------------------------------------------------


def _snapped(buys, *snaps, inst="VTI"):
    txns = [
        T(d(2026, 1, 1 + n), "buy", D(-q), inst, D(q), createdAt=at(n)) for n, q in enumerate(buys)
    ]
    for n, h in enumerate(snaps):
        h.id = f"H{n}"
    return replay("fifo", txns, [], [], list(snaps), by_snapshots=True)


@pytest.mark.parametrize(("held", "standin", "left"), [(D(4), [D(1)], [D(3)]), (D(2), [], [D(2)])])
def test_a_snapshot_one_share_off_says_so(held, standin, left):
    """One share more than replayed is a stand-in lot of one; one fewer takes one away."""
    r = _snapped([3], Snap("VTI", d(2026, 1, 31), held))
    assert [x.quantity for x in r.open if not x.standIn] == left
    assert [x.quantity for x in r.open if x.standIn] == standin
    assert [p.quantity for p in r.problems] == [held - 3]


def test_a_snapshot_takes_the_difference_first_in_and_stops_there():
    """Five fewer than the lots of 2, 5 and 3: the 2, then 3 of the 5; the last lot untouched,
    and the problem said by how many."""
    r = _snapped([2, 5, 3], Snap("VTI", d(2026, 1, 31), D(5)))
    assert [(x.acquiredOn, x.quantity) for x in r.open] == [
        (d(2026, 1, 2), D(2)),
        (d(2026, 1, 3), D(3)),
    ]
    assert [(p.kind, p.quantity) for p in r.problems] == [("history-missing", D(-5))]


def test_a_snapshot_leaves_a_short_lot_past_the_difference_alone():
    """Holding one contract net of a long five and a short two: two of the long go, and the
    short, after the difference is used up, is left as it is."""
    r = replay("fifo", [
        opt(d(2026, 1, 5), "buy-to-open", "-500", 5, 1),
        opt(d(2026, 1, 6), "sell-to-open", "200", -2, 2),
    ], [], [], [Snap("OPT", d(2026, 1, 31), D(1))], by_snapshots=True)  # fmt: skip
    assert [(x.quantity, x.basis) for x in r.open] == [(D(3), D(300)), (D(-2), D(-200))]
    assert [p.quantity for p in r.problems] == [D(-2)]


def test_two_picks_of_one_lot_take_no_more_than_it_holds():
    """S2.3: a lot picked twice (the route allows one live pick a lot; the ledger holds on its
    own) gives its 10 shares once, and the rest of the sale goes first in."""
    txns, lots_ = book()
    s = sell(12, 3000, method="specific")
    picks = [Pick(s.id, lots_[1].id, D(6)), Pick(s.id, lots_[1].id, D(6))]
    r = replay("fifo", [*txns, s], lots_, picks, [])
    assert [(x.lotId, x.quantity) for x in r.disposals] == [
        (lots_[1].id, D(6)), (lots_[1].id, D(4)), (lots_[0].id, D(2))
    ]  # fmt: skip
    assert all(x.quantity >= 0 for x in r.open)


def test_picks_take_a_lot_whatever_is_missing_from_it_and_carry_what_is():
    """S2.3, S2.2, S8.4: a sale's picks take a lot whose basis is missing (its gain unknown)
    and one whose day bought is missing (its term unknown) as they take any; a pick of a lot
    not held takes nothing, and the rest of the sale goes first in."""
    plain = Lot("L1", "VTI", d(2024, 1, 5), D(10), D(1000))
    no_basis = Lot("L2", "VTI", d(2025, 3, 5), D(10), None, basisMissing=True)
    no_day = Lot("L3", "VTI", d(2025, 6, 1), D(10), D(2000), acquiredMissing=True)
    s = sell(8, 2400, method="specific")
    picks = [Pick(s.id, "L2", D(3)), Pick(s.id, "L3", D(2)), Pick(s.id, "GONE", D(1))]
    r = replay("fifo", [s], [plain, no_basis, no_day], picks, [])
    got = [(x.lotId, x.quantity, x.basis, x.acquiredMissing) for x in r.disposals]
    assert got == [("L2", D(3), None, False), ("L3", D(2), D(400), True),
                   ("L1", D(3), D(300), False)]  # fmt: skip
    assert r.disposals[0].gain is None


# -- How a sale takes its lots, on plain lots (S2.3) ---------------------------------------------


def _open(*held):
    """Lots held, oldest first: (lot id, quantity, basis or None)."""
    out = lots.Replay()
    for i, (lot_id, q, b) in enumerate(held):
        basis = None if b is None else D(b)
        out.open.append(lots.OpenLot(lot_id, "VTI", d(2025, 1, i + 1), D(q), basis))
    return out


def _sale(qty, proceeds, method, picks=(), out=None):
    t = SimpleNamespace(id="S", instrumentId="VTI", date=d(2026, 3, 2))
    lots._consume(out, t, D(qty), method, D(proceeds), realize=True, picks=list(picks))
    return [(x.lotId, x.quantity, x.proceeds, x.basis, x.method) for x in out.disposals]


def test_a_method_not_known_is_refused_naming_the_ones_there_are():
    with pytest.raises(
        ValueError, match=r"'random' is none of fifo, lifo, hifo, specific, average"
    ):
        _sale(1, 10, "random", out=_open(("A", 1, 10)))


def test_picks_count_only_for_specific_identification():
    out = _open(("A", 5, 50), ("B", 5, 100))
    assert _sale(2, 40, "fifo", [Pick("S", "B", D(2))], out) == [("A", D(2), D(40), D(20), "fifo")]


def test_a_pick_takes_no_more_than_the_sale_and_a_lot_used_up_gives_no_empty_part():
    """A pick larger than the sale takes the sale's shares; a second pick of the lot it used up
    adds no part of no shares."""
    out = _open(("A", 10, 100), ("B", 10, 200))
    picks = [Pick("S", "A", D(8)), Pick("S", "A", D(5)), Pick("S", "B", D(1))]
    got = _sale(5, 50, "specific", picks, out)
    assert got == [("A", D(5), D(50), D(50), "specific")]


def test_a_pick_of_a_split_lot_takes_its_parts_in_turn_and_no_more_than_picked():
    """A lot a wash sale split is two parts of one id: a pick of 4 takes 3 and then 1, and the
    rest of the sale goes first in, here from an older lot."""
    out = _open(("M", 10, 100), ("L", 3, 30), ("L", 3, 60))
    got = _sale(6, 60, "specific", [Pick("S", "L", D(4))], out)
    assert [(x[0], x[1]) for x in got] == [("L", D(3)), ("L", D(1)), ("M", D(2))]


def test_a_sales_proceeds_are_shared_by_quantity_the_last_part_taking_the_cents_left():
    out = _open(("A", 1, 1), ("B", 1, 1), ("C", 1, 1))
    got = _sale(3, 10, "fifo", out=out)
    assert [x[2] for x in got] == [D("3.33"), D("3.33"), D("3.34")]
    assert sum(x[2] for x in got) == D(10)


def test_average_cost_rebases_the_shares_held_the_last_lot_taking_the_cents_left():
    """S2.3: every share held is re-based to the pool's average; the last lot held takes what
    rounding leaves, and a lot of no shares left is no part of the pool."""
    out = _open(("A", 1, "3"), ("B", 1, "3"), ("C", 1, "4"), ("Z", 0, "0"))
    _sale(1, 5, "average", out=out)
    assert [(x.lotId, x.quantity, x.basis) for x in out.open] == [
        ("A", D(0), D(0)), ("B", D(1), D("3.33")), ("C", D(1), D("3.34")), ("Z", D(0), D(0))
    ]  # fmt: skip


def test_hifo_takes_the_highest_cost_a_share_first_and_a_lot_without_a_basis_last():
    out = _open(("A", 1, 10), ("N", 1, None), ("B", 1, 30), ("C", 1, 20))
    got = _sale(4, 40, "hifo", out=out)
    assert [x[0] for x in got] == ["B", "C", "A", "N"]
