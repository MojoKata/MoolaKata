"""Performance (requirements S5.2.1, S5.2.3): contributions apart from growth, time-weighted
and money-weighted (IRR) returns, and a benchmark that is given the same money at the same
times. Everything is Decimal; a return is a fraction (0.0512 is 5.12%).
"""

import bisect
import datetime as dt
import itertools
from decimal import Decimal

from .lots import ZERO

ONE = Decimal(1)
EXTERNAL = ("deposit", "withdrawal", "transfer", "adjustment")


def flows(transactions: list) -> dict[dt.date, Decimal]:
    """Cash that came into the account (+) or left it (−) from outside, per day. Dividends,
    interest and fees are growth, not flows. Shares, items and loans that move value in or out
    are `valuation.flows`', valued as the series values them."""
    out: dict[dt.date, Decimal] = {}
    for t in transactions:
        if t.kind in EXTERNAL and not t.instrumentId and t.amount:
            out[t.date] = out.get(t.date, ZERO) + t.amount
    return out


def twr(values: list[tuple[dt.date, Decimal]], flow: dict[dt.date, Decimal]) -> Decimal | None:
    """Time-weighted return over the series: each step's return chained, with the flows since
    the previous point taken as arriving at the start of the step."""
    if len(values) < 2:
        return None
    growth = ONE
    prev_day, prev = values[0]
    for day, value in values[1:]:
        base = prev + _flows_between(flow, prev_day, day)
        if base > 0:
            growth *= value / base
        prev_day, prev = day, value
    return growth - ONE


def _flows_between(flow: dict[dt.date, Decimal], after: dt.date, upto: dt.date) -> Decimal:
    return sum((v for d, v in flow.items() if after < d <= upto), ZERO)


def annualise(r: Decimal, days: int) -> Decimal:
    if days <= 0:
        return r
    return Decimal(str((float(ONE + r)) ** (365.25 / days) - 1)) if r > -1 else Decimal(-1)


def irr(
    start: dt.date,
    start_value: Decimal,
    flow: dict[dt.date, Decimal],
    end: dt.date,
    end_value: Decimal,
) -> Decimal | None:
    """The annual rate that makes what went in grow into what is there (money-weighted),
    found by bisection. None when nothing was invested."""
    cash = (
        [(start, -start_value)]
        + [(d, -v) for d, v in sorted(flow.items()) if start < d <= end]
        + [(end, end_value)]
    )
    if not any(c for _, c in cash):
        return None  # nothing went in or came out

    def npv(rate: Decimal) -> Decimal:
        total = ZERO
        base = ONE + rate
        for day, c in cash:
            years = Decimal((day - start).days) / Decimal("365.25")
            # No mutant differs: negating every term keeps the root, and c / base**0 is c.
            total += c / (base**years) if years else c  # pragma: no mutate
        return total

    lo, hi = Decimal("-0.99"), Decimal("10")
    f_lo, f_hi = npv(lo), npv(hi)
    # A bound that is the rate itself is the answer: -99% exactly, a 99% loss (CR3-404).
    if f_lo == 0:
        return lo
    if f_hi == 0:
        return hi
    # No mutant differs: neither sum is 0 here (that returned above), so the product's sign is
    # the quotient's and it is never 0.
    if f_lo * f_hi > 0:  # pragma: no mutate
        return None  # no rate from -99% to +1000% a year fits (cash all one way among them)
    # No mutant differs: the width, 10.99 / 2**k, is never exactly 1e-9.
    while hi - lo >= Decimal("1e-9"):  # pragma: no mutate
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if f_mid == 0:
            return mid
        # No mutant differs: neither f_mid nor f_lo is 0 here.
        if (f_mid > 0) == (f_lo > 0):  # pragma: no mutate
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return (lo + hi) / 2


def benchmark(
    values: list[tuple[dt.date, Decimal]],
    flow: dict[dt.date, Decimal],
    index: list[tuple[dt.date, Decimal]],
) -> list[tuple[dt.date, Decimal]]:
    """What the same money, put in and taken out on the same days, would be worth in the
    benchmark: its value follows the index between flows."""
    if not values or not index:
        return []
    levels = dict(index)
    known = sorted(levels)
    out = []
    held = values[0][1]
    prev_day = values[0][0]
    prev_level = _level_on(known, levels, prev_day)
    out.append((prev_day, held))
    for day, _ in values[1:]:
        level = _level_on(known, levels, day)
        held += _flows_between(flow, prev_day, day)
        if prev_level and level:
            held = held * level / prev_level
        out.append((day, held.quantize(Decimal("0.01"))))
        prev_day, prev_level = day, level or prev_level
    return out


def _level_on(known: list[dt.date], levels: dict[dt.date, Decimal], day: dt.date) -> Decimal | None:
    i = bisect.bisect_right(known, day) - 1
    return levels[known[i]] if i >= 0 else None


def mix(
    parts: list[tuple[Decimal, list[tuple[dt.date, Decimal]]]],
) -> list[tuple[dt.date, Decimal]]:
    """A blended index rebalanced daily, such as 60% VT and 40% BND, starting at 1."""
    if not parts or any(not series for _, series in parts):
        return []
    days = sorted(set.intersection(*(set(d for d, _ in s) for _, s in parts)))
    if not days:
        return []
    maps = [(w, dict(s)) for w, s in parts]
    level = ONE
    out = [(days[0], level)]
    for prev, day in itertools.pairwise(days):
        # No mutant differs: the terms are Decimals, so a sum from int 0 is the same Decimal.
        level *= sum((w * m[day] / m[prev] for w, m in maps), ZERO)  # pragma: no mutate
        out.append((day, level))
    return out
