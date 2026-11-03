"""The lot ledger's rules one at a time, on plain objects (no database): which lots a sale
takes by each method and what each realizes, a sale or a close with nothing to take, the basis
a new lot opens with, holding snapshots, options to their end, corporate actions, and the
order of a day's events. Each test names the rule; the mutation run found them unchecked."""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal as D

import pytest
from test_ledger import Lot, Pick, Snap, Txn

from moolakata.ledger import lots

d = dt.date
T0 = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


@dataclass
class T(Txn):
    price: D | None = None
    proceedsAdjustment: D | None = None
    optionTransactionId: str | None = None


@dataclass
class L(Lot):
    acquiredMissing: bool = False


def at(n: int) -> dt.datetime:
    return T0 + dt.timedelta(minutes=n)


def sold(r):
    return [(x.lotId, x.quantity, x.proceeds, x.basis, x.method) for x in r.disposals]


def problems(r):
    return [(p.kind, p.instrumentId, p.date, p.quantity) for p in r.problems]


def three_lots():
    return [
        Lot("L1", "VTI", d(2024, 1, 1), D(2), D(20)),  # $10 a share
        Lot("L2", "VTI", d(2024, 6, 1), D(2), D(60)),  # $30
        Lot("L3", "VTI", d(2025, 1, 1), D(2), D(40)),  # $20
    ]


# -- Which lots a sale takes, by its method (S2.3) -------------------------------------------

FIFO = [("L1", D(2), D(60), D(20), "fifo"), ("L2", D(1), D(30), D(30), "fifo")]


@pytest.mark.parametrize(
    ("method", "averaged", "want"),
    [
        ("fifo", (), FIFO),
        ("lifo", (), [("L3", D(2), D(60), D(40), "lifo"), ("L2", D(1), D(30), D(30), "lifo")]),
        ("hifo", (), [("L2", D(2), D(60), D(60), "hifo"), ("L3", D(1), D(30), D(20), "hifo")]),
        # The pool's $120 over 6 shares re-bases every lot to $20 a share, taken first in.
        (
            "average",
            ("VTI",),
            [("L1", D(2), D(60), D(40), "average"), ("L2", D(1), D(30), D(20), "average")],
        ),
        # Average cost is for funds and coins: a share goes first in.
        ("average", (), FIFO),
        # Specific with no lots picked, or a method not known: first in, and said so.
        ("specific", (), FIFO),
        ("zzz", (), FIFO),
    ],
)
def test_a_sale_takes_its_lots_in_its_methods_order(method, averaged, want):
    """Three shares sold for $90 out of three lots of two: each lot taken realizes its share of
    the proceeds by quantity, the last what rounding leaves."""
    sale = Txn(d(2025, 3, 1), "sell", D(90), "VTI", D(-3))
    r = lots.replay(method, [sale], three_lots(), [], [], averaged=frozenset(averaged))
    assert sold(r) == want
    assert r.quantity("VTI") == D(3)


def test_picked_lots_make_a_sale_specific_whatever_the_method():
    sale = Txn(d(2025, 3, 1), "sell", D(90), "VTI", D(-3))
    picks = [Pick(sale.id, "L3", D(1)), Pick(sale.id, "L1", D(2))]
    r = lots.replay("fifo", [sale], three_lots(), picks, [])
    assert sold(r) == [("L3", D(1), D(30), D(20), "specific"),
                       ("L1", D(2), D(60), D(20), "specific")]  # fmt: skip


def test_proceeds_split_by_quantity_the_last_lot_taking_what_rounding_leaves():
    made = [
        Lot("A", "VTI", d(2024, 1, 1), D(1), D(10)),
        Lot("B", "VTI", d(2024, 2, 1), D(2), D(20)),
    ]
    sale = Txn(d(2025, 3, 1), "sell", D(100), "VTI", D(-3))
    r = lots.replay("fifo", [sale], made, [], [])
    assert [x.proceeds for x in r.disposals] == [D("33.33"), D("66.67")]


def test_a_sales_proceeds_take_its_adjustment():
    made = [Lot("A", "VTI", d(2024, 1, 1), D(1), D(10))]
    sale = T(d(2025, 3, 1), "sell", D(50), "VTI", D(-1), proceedsAdjustment=D(5))
    assert sold(lots.replay("fifo", [sale], made, [], [])) == [("A", D(1), D(55), D(10), "fifo")]


def test_more_sold_than_held_is_a_sale_without_a_lot():
    """The two held realize their share; the other three are a disposal with no lot and no
    basis, and a problem (S8.4). A transfer out has the problem only."""
    made = [Lot("A", "VTI", d(2024, 1, 1), D(2), D(20))]
    sale = Txn(d(2025, 3, 1), "sell", D(100), "VTI", D(-5), lotMethod="lifo")
    r = lots.replay("fifo", [sale], made, [], [])
    assert sold(r) == [("A", D(2), D(40), D(20), "lifo"), (None, D(3), D(60), None, "lifo")]
    assert problems(r) == [("sale-without-lot", "VTI", d(2025, 3, 1), D(3))]
    out = Txn(d(2025, 3, 1), "transfer-out", D(0), "VTI", D(-5))
    r = lots.replay("fifo", [out], made, [], [])
    assert r.disposals == []
    assert problems(r) == [("sale-without-lot", "VTI", d(2025, 3, 1), D(3))]


# -- The basis a new lot opens with ------------------------------------------------------------


@pytest.mark.parametrize(
    ("txn", "basis"),
    [
        (T(d(2026, 1, 5), "buy", D("-1000"), "VTI", D(10)), D(1000)),
        (T(d(2026, 1, 5), "reinvest", D("-50"), "VTI", D(1)), D(50)),
        (T(d(2026, 1, 5), "buy", D(0), "VTI", D(10)), None),  # no cost given: missing
        (T(d(2026, 1, 5), "transfer-in", D("-500"), "VTI", D(10)), None),  # its lots say
        # A reward is income at its price that day (S3.9), to the cent.
        (T(d(2026, 1, 5), "reward", D(0), "ETH", D("0.003"), price=D("1234.56")), D("3.70")),
        (T(d(2026, 1, 5), "reward", D(0), "ETH", D("0.003")), None),
    ],
)
def test_a_lot_opens_at_its_cost_on_its_day(txn, basis):
    r = lots.replay("fifo", [txn], [], [], [], by_snapshots=False)
    (lot,) = r.open
    assert (lot.lotId, lot.instrumentId, lot.acquiredOn, lot.quantity, lot.basis) == (
        None, txn.instrumentId, txn.date, txn.quantity, basis
    )  # fmt: skip


# -- Shares moved between accounts carry what is known of them (CR3-73) ------------------------


def test_a_transfer_out_takes_its_lots_with_what_is_known_of_them():
    into = Txn(d(2026, 1, 5), "transfer-in", D(0), "VTI", D(5), createdAt=at(1))
    made = [L("M", "VTI", d(2026, 1, 5), D(5), D(500), transactionId=into.id, acquiredMissing=True)]
    snap = Snap("VXUS", d(2026, 1, 6), D(4))
    out = Txn(d(2026, 2, 1), "transfer-out", D(0), "VTI", D(-2), createdAt=at(2))
    out2 = Txn(d(2026, 2, 1), "transfer-out", D(0), "VXUS", D(-1), createdAt=at(3))
    r = lots.replay("fifo", [into, out, out2], made, [], [snap], by_snapshots=True)
    assert r.moved[out.id] == [lots.OpenLot(None, "VTI", d(2026, 1, 5), D(2), D(200),
                                            acquiredMissing=True)]  # fmt: skip
    assert r.moved[out2.id] == [lots.OpenLot(None, "VXUS", d(2026, 1, 6), D(1), None,
                                             standIn=True)]  # fmt: skip


def test_a_transfer_in_opens_the_lots_its_pair_took_whole():
    carried = lots.OpenLot(None, "VTI", d(2020, 3, 1), D(2), D(200), standIn=True,
                           heldFrom=d(2019, 3, 1), acquiredMissing=True)  # fmt: skip
    into = Txn(d(2026, 2, 1), "transfer-in", D(0), "VTI", D(2), accountId="B")
    r = lots.replay("fifo", [into], [], [], [], carried_in={into.id: [carried]})
    assert r.open == [carried]


# -- Holding snapshots (R3.2, S8.4) ------------------------------------------------------------


def test_a_snapshot_explains_what_the_transactions_dont_and_says_so():
    """More held than replayed: a stand-in lot with its basis missing. Fewer: taken first in.
    Either way a `history-missing` problem by how many. A snapshot is at its day's end."""
    buy = Txn(d(2026, 1, 5), "buy", D(-30), "VTI", D(3), createdAt=at(5))
    snaps = [
        Snap("VTI", d(2026, 1, 5), D(3)),  # the day's buy is in it: nothing missing
        Snap("VTI", d(2026, 1, 31), D(10)),
        Snap("VTI", d(2026, 2, 28), D(4)),
    ]
    for n, h in enumerate(snaps):
        h.createdAt, h.id = at(n), f"H{n}"
    r = lots.replay("fifo", [buy], [], [], snaps, by_snapshots=True)
    assert problems(r) == [("history-missing", "VTI", d(2026, 1, 31), D(7)),
                           ("history-missing", "VTI", d(2026, 2, 28), D(-6))]  # fmt: skip
    # The buy's three went first; four of the stand-in's seven are left.
    assert [(x.acquiredOn, x.quantity, x.basis, x.standIn) for x in r.open] == [
        (d(2026, 1, 31), D(4), None, True)
    ]


# -- Options to their end (S3.2–S3.4) ---------------------------------------------------------


def run(*txns):
    return lots.replay("fifo", list(txns), [], [], [])


def opt(day, kind, amount, qty, n, **kw):
    return T(day, kind, D(amount), "OPT", D(qty), createdAt=at(n), **kw)


def test_a_long_option_that_expires_loses_its_premium():
    r = run(
        opt(d(2026, 1, 5), "buy-to-open", "-300", 2, 1), opt(d(2026, 3, 20), "expire", "0", -2, 2)
    )
    assert sold(r) == [(None, D(2), D(0), D(300), "fifo")]
    assert r.disposals[0].gain == D(-300) and r.open == [] and r.problems == []


def test_an_expiry_takes_the_longs_held_and_no_more():
    r = run(
        opt(d(2026, 1, 5), "buy-to-open", "-150", 1, 1), opt(d(2026, 3, 20), "expire", "0", -2, 2)
    )
    assert sold(r) == [(None, D(1), D(0), D(150), "fifo")] and r.problems == []


def test_a_short_option_that_expires_keeps_its_credit():
    r = run(
        opt(d(2026, 1, 5), "sell-to-open", "200", -1, 1), opt(d(2026, 3, 20), "expire", "0", 1, 2)
    )
    (x,) = r.disposals
    assert (x.quantity, x.proceeds, x.basis, x.written, x.gain) == (D(1), 0, D(-200), True, 200)


def test_a_close_shares_its_cost_over_the_shorts_oldest_first():
    r = run(
        opt(d(2026, 1, 5), "sell-to-open", "200", -1, 1),
        opt(d(2026, 2, 5), "sell-to-open", "300", -2, 2),
        opt(d(2026, 3, 5), "buy-to-close", "-100", 3, 3),
    )
    assert [(x.acquiredOn, x.quantity, x.proceeds, x.basis, x.written) for x in r.disposals] == [
        (d(2026, 1, 5), D(1), D("-33.33"), D(-200), True),
        (d(2026, 2, 5), D(2), D("-66.67"), D(-300), True),
    ]
    assert r.open == [] and r.problems == []


def test_closing_more_than_is_open_is_a_close_without_an_open():
    r = run(
        opt(d(2026, 1, 5), "sell-to-open", "200", -1, 1),
        opt(d(2026, 3, 5), "buy-to-close", "-300", 2, 2),
    )
    assert sold(r) == [(None, D(1), D(-150), D(-200), "fifo")]
    assert problems(r) == [("close-without-open", "OPT", d(2026, 3, 5), D(1))]


def test_an_assignment_moves_its_share_of_the_premium_into_the_shares_bought():
    """A short put of two, one assigned: half its credit goes into the basis of the shares the
    assignment buys, whose trade is made before it on its day (S3.4); the other half stays."""
    put = opt(d(2026, 1, 5), "sell-to-open", "400", -2, 1)
    end = opt(d(2026, 3, 20), "assign", "0", 1, 3)
    leg = T(d(2026, 3, 20), "buy", D(-5000), "VTI", D(100), createdAt=at(2),
            optionTransactionId=end.id)  # fmt: skip
    made = [Lot("S", "VTI", d(2026, 3, 20), D(100), D(5000), transactionId=leg.id)]
    r = lots.replay("fifo", [put, leg, end], made, [], [])
    assert [(x.instrumentId, x.quantity, x.basis) for x in r.open] == [
        ("OPT", D(-1), D(-200)),
        ("VTI", D(100), D(4800)),
    ]
    assert r.disposals == []


# -- Corporate actions (S3.10) ------------------------------------------------------------------


def old_and_new(kind, n_new_first=True, **new):
    """An old leg and its new one on the same day, the new one made first: the new leg still
    comes after the old."""
    old = T(d(2026, 5, 1), kind, new.pop("cash", D(0)), "OLD", D(-10), createdAt=at(2),
            splitRatio=new.pop("oldRatio", None))  # fmt: skip
    nxt = T(d(2026, 5, 1), kind, D(0), "NEW", D(10), transferId=old.id,
            createdAt=at(1 if n_new_first else 3), **new)  # fmt: skip
    return old, nxt


def test_a_symbol_change_carries_the_lots_whole():
    made = [L("A", "OLD", d(2024, 1, 1), D(10), D(1000), acquiredMissing=True)]
    old, nxt = old_and_new("symbol-change")
    r = lots.replay("fifo", [old, nxt], made, [], [])
    assert r.open == [lots.OpenLot("A", "NEW", d(2024, 1, 1), D(10), D(1000), acquiredMissing=True)]


def test_a_spin_off_moves_its_share_of_the_basis_to_the_new_shares():
    made = [Lot("A", "OLD", d(2024, 1, 1), D(10), D(1000))]
    old, nxt = old_and_new("spin-off", oldRatio=D("0.2"), splitRatio=D("0.5"))
    old.transferId = None
    old.quantity = D(0)
    r = lots.replay("fifo", [old, nxt], made, [], [])
    assert [(x.lotId, x.instrumentId, x.acquiredOn, x.quantity, x.basis) for x in r.open] == [
        ("A", "OLD", d(2024, 1, 1), D(10), D(800)),
        ("A", "NEW", d(2024, 1, 1), D(5), D(200)),
    ]


@pytest.mark.parametrize(
    ("basis", "gain", "kept"),
    [(D(1000), D(300), D(1000)), (D(1200), D(100), D(1000)), (D(2000), D(0), D(1700))],
)
def test_a_mergers_cash_is_a_gain_only_as_far_as_the_gain_goes(basis, gain, kept):
    """Ten shares for twenty of the acquirer at $50 and $300 cash (IRC §356)."""
    made = [Lot("A", "OLD", d(2024, 1, 1), D(10), basis)]
    old, nxt = old_and_new("merger", cash=D(300), splitRatio=D(2), price=D(50))
    r = lots.replay("fifo", [old, nxt], made, [], [])
    assert [(x.instrumentId, x.quantity, x.basis) for x in r.open] == [("NEW", D(20), kept)]
    assert sold(r) == ([("A", D(0), gain, D(0), "merger")] if gain else [])


def test_an_all_cash_merger_is_a_sale():
    made = [Lot("A", "OLD", d(2024, 1, 1), D(10), D(1000))]
    old = T(d(2026, 5, 1), "merger", D(1500), "OLD", D(-10))
    r = lots.replay("fifo", [old], made, [], [])
    assert sold(r) == [("A", D(10), D(1500), D(1000), "fifo")] and r.open == []


# -- What is known of a lot goes wherever it goes (S2.2, CR3-398, CR3-399) ----------------------
# Each fact a lot can carry, crossed with each thing that can happen to it: the lots and sale
# parts that come of it carry the fact, and one without it gains none.

FACTS = {
    "nothing": {},
    "basis missing": {"basis": None},
    "day bought missing": {"acquiredMissing": True},
    "a snapshot's stand-in": {"standIn": True},
    "a replacement's held-from day": {"heldFrom": d(2023, 1, 1)},
}


def _carried(**fact):
    return lots.OpenLot(None, "VTI", d(2024, 1, 2), D(10), fact.pop("basis", D(1000)), **fact)


def _run(lot, *txns, by_snapshots=False):
    into = T(d(2025, 1, 2), "transfer-in", D(0), "VTI", D(10), createdAt=at(1))
    return lots.replay("fifo", [into, *txns], [], [], [], by_snapshots=by_snapshots,
                       carried_in={into.id: [lot]})  # fmt: skip


def _pair(kind, old_amount=D(0), old_qty=D(-10), **new):
    old = T(d(2025, 5, 1), kind, old_amount, "VTI", old_qty, createdAt=at(2),
            splitRatio=new.pop("oldRatio", None))  # fmt: skip
    nxt = T(d(2025, 5, 1), kind, D(0), "NEW", D(10), transferId=old.id, createdAt=at(3), **new)
    return old, nxt


def _sell(lot):
    r = _run(lot, T(d(2025, 3, 1), "sell", D(400), "VTI", D(-4), createdAt=at(2)))
    return [*r.disposals, *r.open]


def _move(lot):
    out = T(d(2025, 3, 1), "transfer-out", D(0), "VTI", D(-4), createdAt=at(2))
    r = _run(lot, out)
    into = T(d(2025, 3, 1), "transfer-in", D(0), "VTI", D(4), accountId="B")
    there = lots.replay("fifo", [into], [], [], [], carried_in={into.id: r.moved[out.id]})
    return [*r.moved[out.id], *r.open, *there.open]


def _split(lot):
    return _run(lot, T(d(2025, 3, 1), "split", D(0), "VTI", splitRatio=D(2), createdAt=at(2))).open


def _symbol_change(lot):
    return _run(lot, *_pair("symbol-change")).open


def _spin_off(lot):
    return _run(lot, *_pair("spin-off", old_qty=D(0), oldRatio=D("0.2"), splitRatio=D("0.5"))).open


def _merger(lot):
    r = _run(lot, *_pair("merger", D(300), splitRatio=D(2), price=D(80)))
    return [*r.open, *r.disposals]


def _cash_merger(lot):
    return _run(lot, T(d(2025, 5, 1), "merger", D(1500), "VTI", D(-10), createdAt=at(2))).disposals


def _return_of_capital(lot):
    r = _run(lot, T(d(2025, 6, 1), "return-of-capital", D(1500), "VTI", createdAt=at(2)))
    return [*r.open, *r.disposals]


OPERATIONS = {f.__name__.strip("_").replace("_", " "): f for f in (
    _sell, _move, _split, _symbol_change, _spin_off, _merger, _cash_merger, _return_of_capital
)}  # fmt: skip


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("fact", FACTS)
def test_what_is_known_of_a_lot_goes_with_it(fact, operation):
    lot = _carried(**FACTS[fact])
    made = OPERATIONS[operation](lot)
    assert made, "the operation makes a lot or a sale part"
    known = (lot.standIn, lot.heldFrom, lot.acquiredMissing, lot.basis is None)
    for x in made:
        # A return of capital or merger cash past a lot's basis is a gain with no basis of its
        # own (zero), which only a lot with a basis has.
        assert (x.standIn, x.heldFrom, x.acquiredMissing, x.basis is None) == known, x


def test_a_lot_bought_on_29_february_is_long_term_from_1_march_a_year_on():
    """S3.1: held more than a year; a 29 February's anniversary is 28 February."""
    assert lots.long_term(d(2024, 2, 29), d(2025, 2, 28)) is False
    assert lots.long_term(d(2024, 2, 29), d(2025, 3, 1)) is True
    assert lots.long_term(d(2024, 3, 1), d(2025, 3, 1)) is False


def test_an_assignments_premium_is_spread_over_its_stock_trades_by_their_cash():
    """S3.10.4: a put assigned whose deliverable is two stocks: the credit taken into the
    shares' basis goes by each trade's cash, the last what rounding leaves."""
    put = opt(d(2026, 1, 5), "sell-to-open", "300", -1, 1)
    end = opt(d(2026, 3, 20), "assign", "0", 1, 4)
    a = T(d(2026, 3, 20), "buy", D(-3000), "AAA", D(100), createdAt=at(2),
          optionTransactionId=end.id)  # fmt: skip
    b = T(d(2026, 3, 20), "buy", D(-1001), "BBB", D(50), createdAt=at(3),
          optionTransactionId=end.id)  # fmt: skip
    made = [Lot("A", "AAA", d(2026, 3, 20), D(100), D(3000), transactionId=a.id),
            Lot("B", "BBB", d(2026, 3, 20), D(50), D(1001), transactionId=b.id)]  # fmt: skip
    r = lots.replay("fifo", [put, a, b, end], made, [], [])
    # 300 credit: 3000/4001 of it is 224.94, the rest 75.06.
    assert [(x.instrumentId, x.basis) for x in r.open] == [
        ("AAA", D("2775.06")), ("BBB", D("925.94"))
    ]  # fmt: skip
