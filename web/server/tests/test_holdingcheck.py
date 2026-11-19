"""The holdings check (requirements S1.3.3.8.2), on plain objects: what the account holds at a
day's end, and each statement row against it, with a hint when the statement's own trades
account for a difference."""

import datetime as dt
from decimal import Decimal as D
from types import SimpleNamespace as NS

from test_ledger import Snap, Txn, buy
from test_lot_edges import W

from moolakata.ledger import holdingcheck as hc

d = dt.date
D1, D2, D3 = d(2026, 3, 2), d(2026, 3, 9), d(2026, 3, 16)


def ledger(txns, made, *, washes=(), sale_at=None, snaps=(), method="fifo", type_="brokerage",
           averaged=frozenset(), cash=D(0)):  # fmt: skip
    return NS(account=NS(lotMethod=method, type=type_), transactions=list(txns), lots=list(made),
              picks=[], snapshots=list(snaps), washes=list(washes), sale_at=sale_at or {},
              averaged=averaged, balance=lambda day: cash)  # fmt: skip


def washed(method="fifo", type_="brokerage"):
    """10 at $100, a replacement 10 at $90 a week later, and the first sold at $80 the week
    after: a $200 loss disallowed into the replacement."""
    a, la = buy(D1, 10, 1000)
    b, lb = buy(D2, 10, 900)
    sale = Txn(D3, "sell", D(800), "VTI", D(-10))
    w = W("W1", sale.id, b.id, D(10), D(200), D1, la.id)
    return ledger([a, b, sale], [la, lb], washes=[w], sale_at={sale.id: (D3, sale.createdAt)},
                  method=method, type_=type_)  # fmt: skip


def test_a_lot_bought_on_the_day_is_held_that_day_and_not_the_day_before():
    t, lot = buy(D2, 5, 500)
    assert hc.held_on(ledger([t], [lot]), D2) == {"VTI": (D(5), D(500))}
    assert hc.held_on(ledger([t], [lot]), D2 - dt.timedelta(days=1)) == {}


def test_a_wash_sale_counts_from_its_sale_on_and_never_in_an_ira():
    """S3.8.3: the replacement is a plain lot until the loss sale; from its day on, its basis
    carries the loss, except in an IRA, where the loss is lost."""
    assert hc.held_on(washed(), D2)["VTI"] == (D(20), D(1900))
    assert hc.held_on(washed(), D3)["VTI"] == (D(10), D(1100))
    assert hc.held_on(washed(type_="ira"), D3)["VTI"] == (D(10), D(900))


def test_a_replacement_takes_its_loss_only_after_the_sale_so_hifo_sells_the_dearer_lot():
    """S3.8.3: bought before the loss sale, the replacement isn't yet the dearer lot, so the
    sale takes the $100 shares and the $90 ones are held with the loss added."""
    assert hc.held_on(washed(method="hifo"), D3)["VTI"] == (D(10), D(1100))


def test_an_account_kept_by_trades_ignores_a_snapshot_even_before_its_first_trade():
    t, lot = buy(D3, 5, 500)
    snap = Snap("VTI", D1, D(7))
    assert hc.held_on(ledger([t], [lot], snaps=[snap]), D2) == {}


def test_average_cost_rebases_what_is_held_at_each_sale():
    a, la = buy(D1, 1, 10, inst="VFIAX")
    b, lb = buy(D2, 1, 20, inst="VFIAX")
    sale = Txn(D3, "sell", D(30), "VFIAX", D(-1))
    led = ledger([a, b, sale], [la, lb], method="average", averaged=frozenset({"VFIAX"}))
    assert hc.held_on(led, D3) == {"VFIAX": (D(1), D(15))}


def row(label, inst=None, qty=None, value=None, basis=None, cash=False):
    return NS(label=label, instrumentId=inst, quantity=qty, marketValue=value, costBasis=basis,
              cash=cash)  # fmt: skip


def test_each_row_against_what_is_held_the_cash_against_the_cash():
    """The cash row is held to the cash balance; a position to the lots, with both bases; a row
    of no known instrument has nothing to compare."""
    t, lot = buy(D1, 5, 500)
    led = ledger([t], [lot], cash=D("120.50"))
    lines = hc.compare(led, D2, [row("Cash", value=D("100.00"), cash=True),
                                 row("VTI", "VTI", D(5), basis=D(480)),
                                 row("Mystery", None, D(3))])  # fmt: skip
    got = [(x.label, x.instrumentId, x.statement, x.held, x.statementBasis, x.heldBasis, x.cash,
            x.difference) for x in lines]  # fmt: skip
    assert got == [
        ("Cash", None, D("100.00"), D("120.50"), None, None, True, D("-20.50")),
        ("VTI", "VTI", D(5), D(5), D(480), D(500), False, D(0)),
        ("Mystery", None, D(3), None, None, None, False, None),
    ]


def test_a_difference_the_statements_trades_explain_is_pointed_at():
    """One trade of the difference is named; several adding up to it are pointed at
    together; trades that don't add up to it leave no hint."""
    t, lot = buy(D1, 5, 500)
    led = ledger([t], [lot])

    def hint(qty, trades):
        (line,) = hc.compare(led, D2, [row("VTI", "VTI", D(qty))], trades)
        return line.hint

    assert hint(7, [(D2, "VTI", D(2), "buy")]) == "the Mar 9 buy of 2 isn't entered yet"
    both = [(D2, "VTI", D(1), "buy"), (D2, "VTI", D(1), "reinvestment")]
    assert hint(7, both) == "the statement's trades in it aren't entered yet"
    assert hint(9, both) is None
    assert hint(7, [(D2, "KO", D(2), "buy")]) is None
    assert hint(5, both) is None


def test_a_statement_value_is_held_to_the_accounts_value_on_its_day(monkeypatch):
    """S1.3.3.8.1: each statement's ending value, oldest first, against the account's value on
    the statement's day, its holdings counted when the account is an investing one; a cash
    balance reported is no value check."""
    from moolakata import valuation
    from moolakata.ledger import reconcile

    seen = []

    def value(s, led, investing, day):
        seen.append((investing, day))
        return D(7)

    monkeypatch.setattr(valuation, "account_value", value)
    anchors = [NS(date=D2, balance=D(9), source="statement-value"),
               NS(date=D1, balance=D(5), source="statement-value"),
               NS(date=D3, balance=D(1), source="typed")]  # fmt: skip
    for type_, investing in (("brokerage", True), ("checking", False)):
        seen.clear()
        got = reconcile.value_checks(None, NS(account=NS(type=type_)), anchors)
        assert [(v.date, v.reported, v.computed) for v in got] == [(D1, D(5), D(7)),
                                                                    (D2, D(9), D(7))]  # fmt: skip
        assert seen == [(investing, D1), (investing, D2)]
