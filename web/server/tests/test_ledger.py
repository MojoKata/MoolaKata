"""The ledger's calculations, on plain objects (no database)."""

import ast
import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

from moolakata import paths
from moolakata.ledger import balances, lots, reconcile, transfers

T0 = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
_n = iter(range(1, 10_000))


@dataclass
class Txn:
    date: dt.date
    kind: str
    amount: D
    instrumentId: str | None = None
    quantity: D | None = None
    lotMethod: str | None = None
    splitRatio: D | None = None
    accountId: str = "A"
    transferId: str | None = None
    payee: str | None = None
    payeeRaw: str | None = None
    runningBalance: D | None = None
    amountWas: D | None = None
    duplicateAnswer: str | None = None
    id: str = field(default_factory=lambda: f"Txn{next(_n)}")
    createdAt: dt.datetime = field(default_factory=lambda: T0 + dt.timedelta(seconds=next(_n)))


@dataclass
class Lot:
    id: str
    instrumentId: str
    acquiredOn: dt.date
    quantity: D
    costBasis: D | None
    transactionId: str | None = None
    basisMissing: bool = False
    createdAt: dt.datetime = T0


@dataclass
class Pick:
    saleId: str
    lotId: str
    quantity: D


@dataclass
class Snap:
    instrumentId: str
    asOf: dt.date
    quantity: D
    id: str = "H1"
    createdAt: dt.datetime = T0


def buy(day, qty, cost, inst="VTI"):
    t = Txn(day, "buy", -D(cost), inst, D(qty))
    return t, Lot(f"L{t.id}", inst, day, D(qty), D(cost), t.id)


def d(y, m, day):
    return dt.date(y, m, day)


def book():
    b1, l1 = buy(d(2024, 1, 5), 10, 1000)  # $100 a share
    b2, l2 = buy(d(2025, 3, 5), 10, 3000)  # $300 a share
    b3, l3 = buy(d(2025, 6, 1), 10, 2000)  # $200 a share
    return [b1, b2, b3], [l1, l2, l3]


SOLD = dt.date(2025, 8, 1)


def sell(qty, proceeds, day=SOLD, method=None):
    return Txn(day, "sell", D(proceeds), "VTI", D(qty), lotMethod=method)


def test_fifo_lifo_hifo():
    txns, lots_ = book()
    for method, basis, long_term in (
        ("fifo", D(2500), True),
        ("lifo", D(3500), False),
        ("hifo", D(4000), False),
    ):
        s = sell(15, 3750, method=method)
        r = lots.replay("fifo", [*txns, s], lots_, [], [])
        assert sum(x.basis for x in r.disposals) == basis, method
        assert sum(x.proceeds for x in r.disposals) == D(3750)
        assert r.disposals[0].longTerm is long_term
        assert r.quantity("VTI") == D(15)


def test_the_method_recorded_on_the_sale_wins():
    txns, lots_ = book()
    r = lots.replay("fifo", [*txns, sell(10, 2500, method="lifo")], lots_, [], [])
    assert r.disposals[0].lotId == lots_[2].id


def test_specific_identification_and_average_cost():
    txns, lots_ = book()
    s = sell(5, 1250, method="specific")
    r = lots.replay("fifo", [*txns, s], lots_, [Pick(s.id, lots_[1].id, D(5))], [])
    assert r.disposals[0].lotId == lots_[1].id and r.disposals[0].basis == D(1500)
    r = lots.replay("average", [*txns, sell(15, 3750)], lots_, [], [])
    assert sum(x.basis for x in r.disposals) == D(3000)  # $200 average
    assert sum(x.basis for x in r.open) == D(3000)


def test_splits_return_of_capital_and_problems():
    txns, lots_ = book()
    split = Txn(d(2025, 7, 1), "split", D(0), "VTI", splitRatio=D(2))
    roc = Txn(d(2025, 7, 2), "return-of-capital", D(60), "VTI")
    r = lots.replay("fifo", [*txns, split, roc], lots_, [], [])
    assert r.quantity("VTI") == D(60)
    assert sum(x.basis for x in r.open) == D(5940)
    r = lots.replay("fifo", [*txns, sell(40, 8000)], lots_, [], [])
    assert r.problems[0].kind == "sale-without-lot" and r.problems[0].quantity == D(10)
    assert r.disposals[-1].basis is None


def test_return_of_capital_over_every_lot_and_its_excess_a_gain():
    # B10: a lot without a basis keeps its share; what exceeds a lot's basis is a gain, held
    # as long as the lot.
    b1, l1 = buy(d(2024, 1, 5), 10, 100)
    t2 = Txn(d(2025, 3, 5), "transfer-in", D(0), "VTI", D(10))
    l2 = Lot(f"L{t2.id}", "VTI", t2.date, D(10), None, t2.id, basisMissing=True)
    roc = Txn(d(2025, 7, 2), "return-of-capital", D(300), "VTI")
    r = lots.replay("fifo", [b1, t2, roc], [l1, l2], [], [])
    first, second = sorted(r.open, key=lambda x: x.acquiredOn)
    assert first.basis == 0 and second.basis is None
    (gain,) = r.disposals
    assert gain.proceeds == D(50) and gain.basis == 0 and gain.quantity == 0
    assert gain.acquiredOn == d(2024, 1, 5) and gain.longTerm
    l2.costBasis, l2.basisMissing = D(1000), False  # its basis entered: its share applies
    r = lots.replay("fifo", [b1, t2, roc], [l1, l2], [], [])
    assert sorted(x.basis for x in r.open) == [0, D(850)]


def test_a_snapshot_is_the_holdings_only_of_an_account_kept_by_snapshots():
    # B9: in an account with trades of its own, a file's positions are a check and change no
    # lot; an account with none is kept by its snapshots, which stand in for its history.
    txns, lots_ = book()
    r = lots.replay("fifo", txns, lots_, [], [Snap("VTI", d(2025, 9, 30), D(45))])
    assert not any(x.standIn for x in r.open) and r.quantity("VTI") == D(30)
    assert r.problems == []
    r = lots.replay("fifo", [], [], [], [Snap("VTI", d(2025, 9, 30), D(45))])
    stand = [x for x in r.open if x.standIn]
    assert stand and stand[0].quantity == D(45) and stand[0].basisMissing
    assert r.problems[0].kind == "history-missing"
    r = lots.replay(
        "fifo",
        [],
        [],
        [],
        [Snap("VTI", d(2025, 9, 30), D(45)), Snap("VTI", d(2025, 12, 31), D(40))],
    )
    assert r.quantity("VTI") == D(40)


def test_income_on_a_holding_is_not_a_trade():
    """CR3-15: a cash dividend, interest or a fee naming the holding leaves the account kept by
    its snapshots; a buy, a reinvestment or shares moved in end it (R3.2)."""
    snap = [Snap("VTI", d(2025, 9, 30), D(100))]
    for kind in ("dividend", "interest", "fee", "return-of-capital", "split"):
        income = [Txn(d(2025, 9, 15), kind, D(12), "VTI")]
        assert lots.kept_by_snapshots(income, []), kind
        assert lots.replay("fifo", income, [], [], snap).quantity("VTI") == D(100), kind
    for kind in ("buy", "reinvest", "transfer-in", "sell"):
        assert not lots.kept_by_snapshots([Txn(d(2025, 9, 15), kind, D(-12), "VTI", D(1))], [])


@dataclass
class Acct:
    openingBalance: D | None = None
    openingDate: dt.date | None = None


@dataclass
class Anchor:
    date: dt.date
    balance: D
    source: str = "ofx"
    id: str = "An1"


def test_opening_balance_typed_or_worked_out():
    txns = [Txn(d(2026, 9, 1), "deposit", D(100)), Txn(d(2026, 9, 3), "withdrawal", D(-30))]
    o = balances.opening(Acct(D(500), d(2026, 8, 31)), txns, [])
    assert o.balance == D(500) and not o.standIn
    o = balances.opening(Acct(), txns, [Anchor(d(2026, 9, 3), D(1070))])
    assert o.balance == D(1000) and o.standIn
    assert balances.balance_on(d(2026, 9, 2), o, txns) == D(1100)
    days = balances.daily(o, txns, d(2026, 9, 1), d(2026, 9, 4))
    assert [b for _, b in days] == [D(1100), D(1100), D(1070), D(1070)]


def test_transfers_match_the_closest_and_refuse_ties():
    t = Txn(d(2026, 9, 15), "withdrawal", D(-500), accountId="A")
    near = Txn(d(2026, 9, 16), "deposit", D(500), accountId="B")
    far = Txn(d(2026, 9, 18), "deposit", D(500), accountId="C")
    same = Txn(d(2026, 9, 15), "deposit", D(500), accountId="A")
    assert transfers.best(t, [far, near, same]) is near
    tie = Txn(d(2026, 9, 14), "deposit", D(500), accountId="C")
    assert transfers.best(t, [near, tie]) is None
    assert transfers.best(t, [Txn(d(2026, 9, 25), "deposit", D(500), accountId="B")]) is None


@dataclass
class Imp:
    id: str
    coveredFrom: dt.date
    coveredTo: dt.date


def test_coverage_gaps_and_overlaps():
    c = reconcile.coverage(
        [
            Imp("I1", d(2026, 7, 1), d(2026, 8, 2)),
            Imp("I2", d(2026, 8, 15), d(2026, 9, 10)),
            Imp("I3", d(2026, 9, 5), d(2026, 9, 30)),
        ]
    )
    assert c.gaps == [(d(2026, 8, 3), d(2026, 8, 14))]
    assert c.overlaps == [(d(2026, 9, 5), d(2026, 9, 10))]
    assert [(p.start, p.end) for p in c.periods] == [
        (d(2026, 7, 1), d(2026, 8, 2)),
        (d(2026, 8, 15), d(2026, 9, 30)),
    ]


def test_checks_name_the_suspects_between_matching_balances():
    txns = [
        Txn(d(2026, 9, 1), "deposit", D(100), payee="Pay"),
        Txn(d(2026, 9, 5), "withdrawal", D(-20), payee="Cafe"),
        Txn(d(2026, 9, 5), "withdrawal", D(-20), payee="Cafe"),
        Txn(d(2026, 9, 7), "withdrawal", D(-55), payee="Shop", amountWas=D(-50)),
    ]
    start = balances.Opening(D(1000), None, False)
    anchors = [Anchor(d(2026, 9, 1), D(1100), id="a"), Anchor(d(2026, 9, 8), D(1025), id="b")]
    cks = reconcile.checks(start, txns, anchors, reconcile.Coverage([], [], []))
    assert cks[0].ok and not cks[1].ok
    assert cks[1].difference == D(20) and cks[1].windowFrom == d(2026, 9, 1)
    assert len(cks[1].suspects.duplicates) == 1
    assert cks[1].suspects.changed == [txns[3].id]
    txns[2].duplicateAnswer = txns[1].duplicateAnswer = "both-real"
    assert reconcile.duplicates(txns) == []


def test_first_parting_running_balance_row():
    txns = [
        Txn(d(2026, 9, 1), "deposit", D(100), runningBalance=D(1100)),
        Txn(d(2026, 9, 2), "withdrawal", D(-10), runningBalance=D(1080)),
        Txn(d(2026, 9, 3), "withdrawal", D(-10), runningBalance=D(1070)),
    ]
    start = balances.Opening(D(1000), None, False)
    assert reconcile.first_parting(start, txns) == txns[1].id


def test_needs_an_anchor_once_the_next_statement_is_overdue():
    # A monthly statement ending Aug 31 is overdue from Oct 15 (S1.11.7.3).
    acct = SimpleNamespace(type="checking", statementInterval=None, keptBy='["file"]')
    imports = [SimpleNamespace(coveredFrom=d(2026, 8, 1), coveredTo=d(2026, 8, 31))]
    assert reconcile.needs_anchor(acct, imports, d(2026, 10, 14)) is False
    assert reconcile.needs_anchor(acct, imports, d(2026, 10, 15)) is True
    assert reconcile.needs_anchor(acct, [], d(2027, 1, 1)) is False


def test_calculations_never_import_sqlalchemy():
    """Business logic stays apart from the tables (requirements S14.1.2)."""
    for folder in ("ledger",):
        for path in (paths.PACKAGE / folder).glob("*.py"):
            tree = ast.parse(Path(path).read_text())
            for node in ast.walk(tree):
                names = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else ([node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                )
                assert not any(n.startswith("sqlalchemy") for n in names), path
