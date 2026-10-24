"""Recurring transactions (requirements S7.5): rent, subscriptions, salary, found in the
history, each with its next expected date and amount. One that is late is flagged *missed*;
one whose last amount moved from its usual one is flagged *changed*, when its amounts are
otherwise fixed (a subscription, rent; a utility bill varies anyway).

A series is at least three transactions with the same payee and sign, spaced at one of the
usual intervals (weekly, every two weeks, twice a month, monthly, quarterly, yearly) give or
take a few days, with amounts within half of the usual one.
"""

import datetime as dt
import itertools
import re
import statistics
from collections import defaultdict
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
    nxt = last.date + dt.timedelta(days=round(days))
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
    )


def _fixed(amounts: list[Decimal], usual: Decimal) -> bool:
    if not amounts or usual == 0:
        return False
    spread = statistics.median(abs(a - usual) for a in amounts)
    return spread <= usual * FIXED
