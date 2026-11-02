"""A recurring series' schedule on the calendar (requirements S7.5.1) and *Cash before payday*
as a running balance (S7.6.1)."""

import calendar
import datetime as dt
import random
from decimal import Decimal
from types import SimpleNamespace

import pytest

from moolakata.alerts import _dips
from moolakata.budgets import recurring
from moolakata.budgets.recurring import LAST, Schedule

d = dt.date


def _t(day, amount, payee):
    return SimpleNamespace(date=day, amount=Decimal(amount), payee=payee, accountId="a",
                           transferId=None, instrumentId=None, categoryId=None)  # fmt: skip


# ---------- the generator ----------


def test_a_day_past_a_months_end_falls_on_its_last_day():
    s = Schedule(d(2026, 1, 31), months=1, days=(31,))
    assert s.between(d(2026, 1, 1), d(2026, 4, 30)) == [
        d(2026, 1, 31), d(2026, 2, 28), d(2026, 3, 31), d(2026, 4, 30),
    ]  # fmt: skip
    leap = Schedule(d(2028, 1, 31), months=1, days=(LAST,))
    assert d(2028, 2, 29) in leap.between(d(2028, 2, 1), d(2028, 2, 29))


def test_twice_a_month_on_the_15th_and_the_last_day():
    s = Schedule(d(2026, 1, 15), months=1, days=(15, LAST))
    assert s.between(d(2026, 2, 1), d(2026, 3, 31)) == [
        d(2026, 2, 15), d(2026, 2, 28), d(2026, 3, 15), d(2026, 3, 31),
    ]  # fmt: skip


def test_quarterly_and_yearly_keep_their_month():
    q = Schedule(d(2026, 2, 10), months=3, days=(10,))
    assert q.between(d(2026, 1, 1), d(2026, 12, 31)) == [
        d(2026, 2, 10), d(2026, 5, 10), d(2026, 8, 10), d(2026, 11, 10),
    ]  # fmt: skip
    y = Schedule(d(2028, 2, 29), months=12, days=(29,))
    assert y.between(d(2029, 1, 1), d(2029, 12, 31)) == [d(2029, 2, 28)]


def test_weekly_steps_by_seven_days_either_side_of_its_anchor():
    s = Schedule(d(2026, 10, 7), step=7)
    assert s.between(d(2026, 9, 28), d(2026, 10, 22)) == [
        d(2026, 9, 30), d(2026, 10, 7), d(2026, 10, 14), d(2026, 10, 21),
    ]  # fmt: skip


@pytest.mark.parametrize("seed", range(20))
def test_dates_are_in_order_within_the_range_and_on_the_days(seed):
    rnd = random.Random(seed)
    months = rnd.choice([1, 3, 12])
    days = tuple(sorted(rnd.sample([1, 5, 15, 28, 30, LAST], rnd.choice([1, 2]))))
    s = Schedule(d(2026, rnd.randint(1, 12), 1), months=months, days=days)
    first = d(2026, 1, 1) + dt.timedelta(days=rnd.randint(0, 200))
    last = first + dt.timedelta(days=rnd.randint(30, 900))
    got = s.between(first, last)
    assert got == sorted(set(got)) and all(first <= x <= last for x in got)
    for x in got:
        end = calendar.monthrange(x.year, x.month)[1]
        assert x.day in {min(k, end) for k in days}


# ---------- found from history, round trip ----------


@pytest.mark.parametrize("seed", range(12))
def test_a_schedule_found_from_its_history_never_drifts(seed):
    """Generated: a schedule makes a history, its dates paid up to a day early (a weekend);
    the schedule found from it keeps to the true one for a year ahead, date for date, within
    that day, where stepping by an average gap drifts further each month."""
    rnd = random.Random(seed)
    kind = rnd.choice(["month", "twice", "week", "2 weeks"])
    if kind == "month":
        s = Schedule(d(2026, 1, 1), months=1, days=(rnd.choice([1, 5, 15, 20, LAST]),))
    elif kind == "twice":
        s = Schedule(d(2026, 1, 1), months=1, days=rnd.choice([(1, 15), (15, LAST)]))
    else:
        s = Schedule(d(2026, 1, 5) + dt.timedelta(days=rnd.randint(0, 6)),
                     step=7 if kind == "week" else 14)  # fmt: skip
    due = s.between(d(2026, 2, 1), d(2026, 9, 30))
    jitter = 0 if s.step == 7 else 1
    paid = [x - dt.timedelta(days=rnd.randint(0, jitter)) for x in due]
    (found,) = recurring.detect([_t(x, "-120.00", "Daycare") for x in paid], d(2026, 10, 1))
    truth = s.between(due[-1] + dt.timedelta(days=1), d(2027, 9, 30))
    ahead = found.schedule.between(found.next, d(2027, 9, 30) + dt.timedelta(days=jitter))
    assert len(ahead) >= len(truth), (kind, found.schedule)
    for want, got in zip(truth, ahead, strict=False):
        assert abs((got - want).days) <= jitter, (kind, found.schedule, want, got)


# ---------- cash before payday ----------


def _series(txns, today):
    return recurring.detect(txns, today)


def test_a_weekly_payment_counts_every_week_before_payday():
    """The claim (CR3-44): $700 on the 2nd, payday the 15th, daycare $400 every week (the 4th
    and the 11th): the account dips below zero on the 11th."""
    today = d(2026, 11, 2)
    txns = [_t(d(2026, m, 15), "3000.00", "Payroll") for m in range(6, 11)]
    txns += [_t(d(2026, 10, 7) - dt.timedelta(days=7 * i), "-400.00", "Daycare") for i in range(8)]
    txns += [_t(d(2026, 10, 28), "-400.00", "Daycare"), _t(d(2026, 10, 21), "-400.00", "Daycare"),
             _t(d(2026, 10, 14), "-400.00", "Daycare")]  # fmt: skip
    dip, horizon, paid = _dips(_series(txns, today), Decimal("700.00"), today)
    assert (dip, horizon, paid) == (d(2026, 11, 11), d(2026, 11, 15), True)


def test_a_payment_due_today_counts():
    today = d(2026, 11, 5)
    txns = [_t(d(2026, m, 5), "-600.00", "Rent") for m in range(5, 11)]
    txns += [_t(d(2026, m, 20), "2000.00", "Payroll") for m in range(5, 11)]
    dip, _, _ = _dips(_series(txns, today), Decimal("500.00"), today)
    assert dip == today


def test_a_payment_a_few_days_late_counts_today_and_a_missed_one_doesnt():
    txns = [_t(d(2026, m, 1), "-600.00", "Rent") for m in range(4, 11)]
    txns += [_t(d(2026, m, 20), "2000.00", "Payroll") for m in range(4, 11)]
    late = _dips(_series(txns, d(2026, 11, 3)), Decimal("500.00"), d(2026, 11, 3))
    assert late is not None and late[0] == d(2026, 11, 3)
    missed = _dips(_series(txns, d(2026, 11, 12)), Decimal("500.00"), d(2026, 11, 12))
    assert missed is None


def test_a_twice_monthly_payment_before_a_monthly_payday():
    today = d(2026, 11, 2)
    txns = [_t(d(2026, m, day), "-300.00", "Loan") for m in range(5, 11) for day in (1, 15)]
    txns += [_t(d(2026, m, 28), "3000.00", "Payroll") for m in range(5, 11)]
    dip, horizon, _ = _dips(_series(txns, today), Decimal("500.00"), today)
    assert (dip, horizon) == (d(2026, 11, 15), d(2026, 11, 28))


def test_with_no_money_in_the_horizon_is_a_month():
    today = d(2026, 11, 2)
    txns = [_t(d(2026, 10, 7) - dt.timedelta(days=7 * i), "-100.00", "Daycare") for i in range(8)]
    found = _dips(_series(txns, today), Decimal("350.00"), today)
    assert found is not None and found[2] is False
    assert found[0] == d(2026, 11, 25)  # the 4th, 11th, 18th, 25th: $350 lasts three
