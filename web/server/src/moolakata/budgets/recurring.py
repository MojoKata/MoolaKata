"""Recurring transactions (requirements S7.5): rent, subscriptions, salary, found in the
history, each with its next expected date and amount. One that is late is flagged *missed*;
one whose last amount moved from its usual one is flagged *changed*, when its amounts are
otherwise fixed (a subscription, rent; a utility bill varies anyway).

A series is at least three transactions with the same payee and sign, spaced at one of the
usual intervals (weekly, every two weeks, twice a month, monthly, quarterly, yearly) give or
take a few days, with amounts within half of the usual one.

A series has a schedule on the calendar (S7.5.1), found from its history: a weekday every one or
two weeks, or days of the month (the 1st and the 15th, the 15th and the last day) every month,
quarter or year, a day past a short month's end falling on its last day. Its next date, and every
date after, come from the schedule, so a salary on the 15th is expected on the 15th.
"""

import calendar
import datetime as dt
import itertools
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal

INTERVALS = [  # (days, label, tolerance in days)
    (7, "week", 1),
    (14, "2 weeks", 1),
    (15.22, "twice a month", 3),
    (30.44, "month", 4),
    (91.3, "quarter", 8),
    (365.25, "year", 12),
]
CHANGED = Decimal("0.05")  # the last amount 5% or more from the usual
FIXED = Decimal("0.02")  # amounts this close to the usual are a fixed price, such as a plan
STEADY = Decimal("0.5")  # most amounts within half of the usual: a utility bill varies


LAST = 31  # a day of the month meaning its last day


def _on(year: int, month: int, day: int) -> dt.date:
    """The day of a month, a day past its end (the 31st, the last) falling on its last day."""
    return dt.date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _day_key(day: dt.date) -> int:
    """A date's day of the month, the last three days of a month read as its last day."""
    return LAST if day.day > calendar.monthrange(day.year, day.month)[1] - 3 else day.day


@dataclass(frozen=True)
class Schedule:
    """When a series comes (S7.5.1): every `step` days from `anchor` (weekly, two-weekly), or on
    `days` of every `months`-th month counted from `anchor`'s month."""

    anchor: dt.date
    step: int | None = None
    months: int | None = None
    days: tuple[int, ...] = ()

    def between(self, first: dt.date, last: dt.date) -> list[dt.date]:
        """Its dates from `first` to `last`, both included, in order."""
        if self.step:
            k = -((self.anchor - first).days // self.step)
            out, d = [], self.anchor + dt.timedelta(days=self.step * k)
            while d <= last:
                if d >= first:
                    out.append(d)
                d += dt.timedelta(days=self.step)
            return out
        out = []
        y, m = first.year, first.month
        while (y, m) <= (last.year, last.month):
            offset = (y - self.anchor.year) * 12 + m - self.anchor.month
            if offset % (self.months or 1) == 0:
                out += [d for d in sorted({_on(y, m, k) for k in self.days}) if first <= d <= last]
            m += 1
            if m > 12:
                y, m = y + 1, 1
        return out

    def following(self, day: dt.date) -> dt.date:
        """The date after the one `day` stands for: a payment a few days early or late is the
        one it was due on, and the next is the one after that."""
        near = self.between(day - dt.timedelta(days=40), day + dt.timedelta(days=400))
        due = min(near, key=lambda d: abs((d - day).days))
        return next(d for d in near if d > max(due, day))


def schedule_of(dates: list[dt.date], days: float) -> Schedule:
    """The schedule a series' dates keep: its interval's, on the days of the month they mostly
    fall on (the most recent dates count, a tie going to the latest)."""
    last = dates[-1]
    if days < 15:
        return Schedule(last, step=round(days))
    recent = dates[-6:]
    common = Counter(_day_key(d) for d in recent)
    ranked = sorted(common, key=lambda k: (-common[k], -max(i for i, d in enumerate(recent)
                                                             if _day_key(d) == k)))  # fmt: skip
    if days < 20:  # twice a month
        pair = ranked[:2] if len(ranked) > 1 else [ranked[0], _day_key(dates[-2])]
        return Schedule(last, months=1, days=tuple(sorted(set(pair))))
    months = 1 if days < 60 else 3 if days < 200 else 12
    return Schedule(last, months=months, days=(ranked[0],))


@dataclass
class Series:
    payee: str
    accountId: str
    every: str
    days: float
    last: dt.date
    next: dt.date
    usual: Decimal
    lastAmount: Decimal
    count: int
    missed: bool
    changed: bool
    categoryId: str | None = None  # its latest transaction's, for a plan from history
    schedule: Schedule | None = None
    tolerance: int = 0  # days early or late a payment still comes on its date

    def due(self, today: dt.date, until: dt.date) -> list[dt.date]:
        """Its payments expected from today to `until`: each date of the schedule after its last
        payment; one already past but still within its tolerance is expected today, one past
        that is missed and not expected (S7.6.1)."""
        assert self.schedule is not None
        out = []
        for d in self.schedule.between(self.next, until):
            if d >= today:
                out.append(d)
            elif today <= d + dt.timedelta(days=self.tolerance + 2):
                out.append(today)
        return out


def _key(payee: str) -> str:
    """Payees that differ only in reference numbers are one: `NETFLIX.COM 8843` is Netflix."""
    text = re.sub(r"[#*]?\d[\d\-/]*", " ", payee.lower())
    return " ".join(w for w in re.split(r"[^a-z&]+", text) if w)


def detect(transactions, today: dt.date) -> list[Series]:
    groups: dict[tuple[str, str, bool], list] = defaultdict(list)
    for t in transactions:
        if not t.payee or t.amount == 0 or t.transferId or getattr(t, "instrumentId", None):
            continue
        groups[(t.accountId, _key(t.payee), t.amount > 0)].append(t)
    out = []
    for txns in groups.values():
        if len(txns) < 3:
            continue
        txns.sort(key=lambda t: t.date)
        found = _series(txns, today)
        if found:
            out.append(found)
    return sorted(out, key=lambda x: x.next)


def _series(txns, today: dt.date) -> Series | None:
    gaps = [(b.date - a.date).days for a, b in itertools.pairwise(txns)]
    # The usual gap, leaving out the long ones a skipped payment makes: twice a month (14 to
    # 17 days) averages a little over 15, which a median would take for two weeks.
    middle = statistics.median(gaps)
    gap = statistics.mean([g for g in gaps if g <= middle * 1.5])
    fits = [(d, label, tol) for d, label, tol in INTERVALS if abs(gap - d) <= tol]
    match = min(fits, key=lambda x: abs(gap - x[0]), default=None)
    if match is None:
        return None
    days, label, tol = match
    # Most gaps near the interval; a month off here and there (a skipped bill) is allowed.
    near = sum(1 for g in gaps if abs(g - days) <= tol or abs(g - 2 * days) <= tol)
    if near < max(2, int(len(gaps) * 0.75)):
        return None
    amounts = [abs(t.amount) for t in txns]
    usual = Decimal(statistics.median(amounts))
    steady = sum(1 for a in amounts if abs(a - usual) <= usual * STEADY)
    if steady < max(3, int(len(amounts) * 0.75)):
        return None
    last = txns[-1]
    when = schedule_of([t.date for t in txns], days)
    nxt = when.following(last.date)
    sign = 1 if last.amount > 0 else -1
    return Series(
        payee=last.payee,
        accountId=last.accountId,
        every=label,
        days=days,
        last=last.date,
        next=nxt,
        usual=usual * sign,
        lastAmount=last.amount,
        count=len(txns),
        missed=today > nxt + dt.timedelta(days=tol + 2),
        # Only a fixed amount (a subscription, rent) has a change worth flagging.
        changed=_fixed(amounts[:-1], usual) and abs(abs(last.amount) - usual) >= usual * CHANGED,
        categoryId=getattr(last, "categoryId", None),
        schedule=when,
        tolerance=tol,
    )


def _fixed(amounts: list[Decimal], usual: Decimal) -> bool:
    if not amounts or usual == 0:
        return False
    spread = statistics.median(abs(a - usual) for a in amounts)
    return spread <= usual * FIXED
