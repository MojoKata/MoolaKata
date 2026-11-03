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
