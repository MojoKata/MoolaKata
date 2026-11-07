"""Properties of the pure parts, over drawn inputs (requirements S1.7, S1.9, S17.5): where the
generated worlds cover combinations of named values, these cover the ranges between them (any
rate, any amount, any day), where rounding and boundaries bite.

Drawn deterministically (`derandomize`), so a run is the same everywhere; no example database
is kept.
"""

import datetime as dt
from decimal import Decimal as D
from types import SimpleNamespace

from hypothesis import given, settings
from hypothesis import strategies as st

from moolakata import loans as L
from moolakata.ledger import transfers

PROPERTIES = settings(database=None, derandomize=True, deadline=None, max_examples=200)

cents = st.integers(min_value=1, max_value=50_000_000).map(lambda c: D(c) / 100)
rates = st.integers(min_value=0, max_value=15_000).map(lambda r: D(r) / 1000)
days = st.dates(min_value=dt.date(2015, 1, 1), max_value=dt.date(2030, 12, 31))


@st.composite
def loans(draw):
    """Terms of any shape, and payments made on them since the start."""
    start = draw(st.dates(min_value=dt.date(2016, 1, 1), max_value=dt.date(2026, 6, 1)))
    months = draw(st.integers(min_value=6, max_value=360))
    principal = draw(st.integers(min_value=500, max_value=600_000).map(D))
    draw_months = draw(st.sampled_from([0, 0, 0, 24, 120])) if months > 120 else 0
    t = L.Terms(
        principal=D(0) if draw_months and draw(st.booleans()) else principal,
        start=start,
        months=months,
        rate=draw(rates),
        method=draw(st.sampled_from(["amortized", "daily"])),
        drawMonths=draw_months,
    )
    today = start + dt.timedelta(days=draw(st.integers(min_value=0, max_value=3000)))
    draws = []
    if draw_months:
        draws.append((start + dt.timedelta(days=10), draw(st.integers(1000, 90_000).map(D))))
    payments = []
    n = draw(st.integers(min_value=0, max_value=8))
    for k in range(n):
        day = L.add_months(start, k + 1)
        if day > today:
            break
        amount = draw(st.integers(min_value=10, max_value=12_000).map(D))
        payments.append(L.split_for(t, payments, draws, day, amount))
    return t, payments, draws, today


@PROPERTIES
@given(loans())
def test_a_loans_payment_is_its_schedules_next_row_and_the_rows_pay_what_is_owed(case):
    """The summary's payment is the next row's (CR3-21); no balance goes below zero; the rows
    ahead pay off exactly what is owed today."""
    t, payments, draws, today = case
    sm, rows = L.summary(t, payments, draws, today)
    ahead = [r for r in rows if not r.past]
    assert all(r.balance >= 0 for r in rows)
    if not ahead:
        assert sm.payment == sm.total == 0
        return
    nxt = ahead[0]
    assert (sm.payment, sm.total) == (nxt.principal + nxt.interest, nxt.payment)
    assert sum((r.principal for r in ahead), D(0)) == sm.balance
    assert ahead[-1].balance == 0


@PROPERTIES
@given(
    principal=st.integers(min_value=1_000, max_value=900_000).map(D),
    rate=rates,
    escrow=st.integers(min_value=0, max_value=800).map(D),
    first=st.integers(min_value=1, max_value=99).map(lambda x: D(x) / 100),
    later=st.integers(min_value=0, max_value=14),
    extra=cents,
)
def test_one_payment_days_dues_are_paid_once_however_the_payment_is_split(
    principal, rate, escrow, first, later, extra
):
    """CR3-417: a payment day's interest and escrow are due once: paying it in two parts within
    its grace pays the same interest, escrow and principal as paying it in one."""
    t = L.Terms(principal=principal, start=dt.date(2026, 1, 1), months=360, rate=rate,
                escrowTax=escrow)  # fmt: skip
    day = dt.date(2026, 2, 1)
    due = L.cents(principal * rate / 1200) + escrow
    whole = due + extra
    a = L.split_for(t, [], [], day, (whole * first).quantize(D("0.01")))
    b = L.split_for(t, [a], [], day + dt.timedelta(days=later), whole - a.total)
    one = L.split_for(t, [], [], day, whole)
    assert a.interest + b.interest == one.interest
    assert a.escrowTax + b.escrowTax == one.escrowTax
    assert a.principal + b.principal == one.principal


@PROPERTIES
@given(
    months=st.integers(min_value=13, max_value=480),
    share=st.integers(min_value=1, max_value=95),
    rate=rates,
    drawn=st.integers(min_value=1_000, max_value=500_000).map(D),
)
def test_a_helocs_repayment_ends_on_its_terms_last_payment_day(months, share, rate, drawn):
    """CR3-418: drawn in its draw period and repaid as scheduled, a HELOC's last payment falls
    on the term's end, its repayment level to the last."""
    draw_months = max(1, months * share // 100)
    t = L.Terms(principal=D(0), start=dt.date(2026, 1, 1), months=months, rate=rate,
                drawMonths=draw_months)  # fmt: skip
    _, rows = L.summary(t, [], [(dt.date(2026, 1, 10), drawn)], dt.date(2026, 1, 20))
    repay = [r for r in rows if not L._in_draw(t, r.date)]
    assert rows[-1].date == t.end and repay[0].date == L.draw_ends(t)
    assert len(repay) == months - draw_months + 1
    level = repay[0].principal + repay[0].interest
    assert all(r.principal + r.interest == level for r in repay[:-1])


@PROPERTIES
@given(
    start=st.dates(min_value=dt.date(2010, 1, 1), max_value=dt.date(2020, 12, 31)),
    rate=rates,
    reset_after=st.integers(min_value=1, max_value=60),
    new_rate=rates,
    recast=st.booleans(),
)
def test_the_level_payment_holds_between_the_days_that_change_it(
    start, rate, reset_after, new_rate, recast
):
    """CR3-419, S1.9.2: assumed as scheduled, every row from the first payment day after a
    reset or recast to the last but one pays the same principal and interest, the rows passed
    and those ahead alike."""
    when = start + dt.timedelta(days=30 * reset_after + 10)
    t = L.Terms(principal=D(250000), start=start, months=360, rate=rate)
    if recast:
        t.recasts = [(when, D(250))]
    else:
        t.resets = [(when, new_rate)]
    _, rows = L.summary(t, [], [], dt.date(2026, 10, 13))
    after = [r for r in rows[:-1] if r.date > when]
    assert len({r.principal + r.interest for r in after}) == 1


def _txn(i, account, amount, day, paired=False):
    return SimpleNamespace(id=f"t{i}", accountId=account, amount=amount, date=day,
                           transferId="x" if paired else None)  # fmt: skip


@st.composite
def ledgers(draw):
    """Rows over three accounts, some of them already paired."""
    n = draw(st.integers(min_value=1, max_value=12))
    base = draw(days)
    rows = []
    for i in range(n):
        amount = draw(st.sampled_from([D("100.00"), D("-100.00"), D("250.10"), D("-250.10")]))
        day = base + dt.timedelta(days=draw(st.integers(min_value=-6, max_value=6)))
        rows.append(_txn(i, draw(st.sampled_from("abc")), amount, day, draw(st.booleans())))
    return rows


@PROPERTIES
@given(ledgers())
def test_transfer_matching_is_symmetric_and_never_takes_a_paired_row(rows):
    """S1.7's rule pairs two rows or neither, whichever is asked; a row already a transfer's
    is never a candidate; the best is the one closest in days, none on a tie."""
    for t in rows:
        found = transfers.candidates(t, rows)
        assert all(o.transferId is None for o in found)
        for o in found:
            if t.transferId is None:
                assert t in transfers.candidates(o, rows)
        best = transfers.best(t, rows)
        if best is not None:
            gaps = sorted(abs((o.date - t.date).days) for o in found)
            assert abs((best.date - t.date).days) == gaps[0]
            assert len(gaps) == 1 or gaps[0] != gaps[1]


@st.composite
def histories(draw):
    """Buys of one share over the years, some sold, then shares moved out to another account."""
    from test_ledger import Lot, Txn

    txns, made = [], []
    day = dt.date(2018, 1, 2)
    held = D(0)
    for _ in range(draw(st.integers(min_value=1, max_value=6))):
        day += dt.timedelta(days=draw(st.integers(min_value=1, max_value=400)))
        qty = D(draw(st.integers(min_value=1, max_value=50)))
        cost = D(draw(st.integers(min_value=100, max_value=90_000))) / 100
        t = Txn(day, "buy", -cost, "VTI", qty)
        txns.append(t)
        made.append(Lot(f"L{t.id}", "VTI", day, qty, cost, t.id))
        held += qty
        if draw(st.booleans()) and held > 1:
            day += dt.timedelta(days=draw(st.integers(min_value=1, max_value=200)))
            sold = D(draw(st.integers(min_value=1, max_value=int(held) - 1)))
            txns.append(Txn(day, "sell", sold * 10, "VTI", -sold))
            held -= sold
    moved = D(draw(st.integers(min_value=1, max_value=int(held))))
    day += dt.timedelta(days=draw(st.integers(min_value=1, max_value=30)))
    out = Txn(day, "transfer-out", D(0), "VTI", -moved)
    txns.append(out)
    return txns, made, out, moved


@PROPERTIES
@given(histories())
def test_shares_moved_out_carry_their_lots_whole(case):
    """CR3-73: what a transfer out takes, its pair opens: the same shares, the same basis, on
    the days they were bought; nothing is lost or made between the two accounts."""
    from test_ledger import Txn, replay

    txns, made, out, moved = case
    src = replay("fifo", txns, made, [], [])
    taken = src.moved[out.id]
    assert sum((x.quantity for x in taken), D(0)) == moved
    into = Txn(out.date, "transfer-in", D(0), "VTI", moved, accountId="B", transferId=out.id)
    dst = replay("fifo", [into], [], [], [], carried_in={into.id: taken})
    assert sorted((x.acquiredOn, x.quantity, x.basis) for x in dst.open) == sorted(
        (x.acquiredOn, x.quantity, x.basis) for x in taken
    )
    bought = {lot.acquiredOn for lot in made}
    assert all(x.acquiredOn in bought for x in dst.open)
    cost = sum((lot.costBasis for lot in made), D(0))
    kept = sum((x.basis for x in src.open), D(0))
    sold = sum((x.basis for x in src.disposals), D(0))
    assert kept + sold + sum((x.basis for x in taken), D(0)) == cost


@PROPERTIES
@given(
    st.lists(st.integers(min_value=-5_000_00, max_value=5_000_00), min_size=1, max_size=20),
    st.integers(min_value=1_000_00, max_value=100_000_00),
)
def test_money_moved_alone_is_no_return(moves, start):
    """CR3-28: a value that changes only by money moved in or out has a time-weighted return
    of nothing, however the moves fall."""
    from moolakata.ledger import performance as perf

    day = dt.date(2026, 1, 1)
    value = D(start) / 100
    values, flow = [(day, value)], {}
    for m in moves:
        day += dt.timedelta(days=7)
        amount = D(m) / 100
        if value + amount <= 0:
            continue
        value += amount
        flow[day] = amount
        values.append((day, value))
    twr = perf.twr(values, flow)
    assert twr is None or abs(twr) < D("0.000001")


_FACTS = st.sampled_from([
    {}, {"basis": None}, {"acquiredMissing": True}, {"standIn": True},
    {"heldFrom": dt.date(2023, 1, 1)},
])  # fmt: skip


@st.composite
def lot_histories(draw):
    """Two lots moved in, each with something known of it, then sales, moves out, splits and
    returns of capital in any order and size (more than held included)."""
    from test_lot_rules import T, at

    from moolakata.ledger import lots

    held = []
    for i in range(2):
        fact = {"basis": D(draw(st.integers(1, 5000))), **draw(_FACTS)}
        qty = D(draw(st.integers(1, 20)))
        held.append(lots.OpenLot(None, "VTI", dt.date(2024, 1, 2 + i), qty, **fact))
    ops = []
    for n in range(draw(st.integers(1, 6))):
        day, made = dt.date(2025, 1, 10 + n), at(10 + n)
        kind = draw(st.sampled_from(["sell", "transfer-out", "split", "return-of-capital"]))
        if kind == "split":
            ops.append(T(day, "split", D(0), "VTI", splitRatio=D(draw(st.sampled_from([2, 3]))),
                         createdAt=made))  # fmt: skip
        elif kind == "return-of-capital":
            ops.append(T(day, kind, D(draw(st.integers(1, 3000))), "VTI", createdAt=made))
        else:
            q = D(draw(st.integers(1, 30)))
            ops.append(
                T(day, kind, D(10) * q if kind == "sell" else D(0), "VTI", -q, createdAt=made)
            )
    return held, ops


@PROPERTIES
@given(lot_histories())
def test_what_is_known_of_a_lot_is_never_lost_or_made_up(case):
    """S2.2, CR3-398/399: whatever happens to a lot, every lot and sale part that comes of it
    carries what was known of the lot it came from, and nothing else; and the shares held are
    what a plain count says (a split multiplies, a sale or move takes what is there)."""
    from test_ledger import replay
    from test_lot_rules import T, at

    from moolakata.ledger import lots

    held, ops = case
    into = T(dt.date(2025, 1, 2), "transfer-in", D(0), "VTI", sum(x.quantity for x in held),
             createdAt=at(1))  # fmt: skip
    r = replay("fifo", [into, *ops], [], [], [], by_snapshots=False,
                    carried_in={into.id: [lots.OpenLot(**vars(x)) for x in held]})  # fmt: skip
    known = {(x.standIn, x.heldFrom, x.acquiredMissing, x.basis is None) for x in held}
    moved = [x for v in r.moved.values() for x in v]
    # A sale past what is held is a part with no lot, bought the day it is sold (S8.4).
    from_lots = [y for y in r.disposals if y.acquiredOn != y.soldOn]
    for x in [*r.open, *moved, *from_lots]:
        assert (x.standIn, x.heldFrom, x.acquiredMissing, x.basis is None) in known, x
    count = sum(x.quantity for x in held)
    for t in ops:
        if t.kind == "split":
            count *= t.splitRatio
        elif t.kind in ("sell", "transfer-out"):
            count = max(count + t.quantity, D(0))
    assert r.quantity("VTI") == count
    assert all(x.basis is None or x.basis >= 0 for x in r.open)
