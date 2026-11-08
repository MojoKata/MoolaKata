"""Tax dates (requirements S8.15.3): a due date that falls on a Saturday, a Sunday or a legal
holiday moves to the next day that is none of them (IRC §7503). Legal holidays are the federal
ones and, since the IRS is in Washington, the District of Columbia's Emancipation Day (April 16),
each on the day it is observed."""

import datetime as dt

DAY = dt.timedelta(days=1)


def _nth(year: int, month: int, weekday: int, n: int) -> dt.date:
    """The n-th weekday (0 Monday) of a month; n = -1 for the last."""
    if n == -1:
        last = dt.date(year + (month == 12), month % 12 + 1, 1) - DAY
        return last - dt.timedelta(days=(last.weekday() - weekday) % 7)
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _observed(d: dt.date) -> dt.date:
    """A fixed-date holiday on a Saturday is observed the Friday before, on a Sunday the
    Monday after."""
    if d.weekday() == 5:
        return d - DAY
    if d.weekday() == 6:
        return d + DAY
    return d


def legal_holidays(year: int) -> set[dt.date]:
    fixed = [(1, 1), (6, 19), (7, 4), (11, 11), (12, 25), (4, 16)]  # 4/16: Emancipation Day
    out = {_observed(dt.date(year, m, d)) for m, d in fixed}
    out |= {
        _nth(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth(year, 2, 0, 3),  # Washington's Birthday
        _nth(year, 5, 0, -1),  # Memorial Day
        _nth(year, 9, 0, 1),  # Labor Day
        _nth(year, 10, 0, 2),  # Columbus Day
        _nth(year, 11, 3, 4),  # Thanksgiving
    }
    # New Year's Day on a Saturday is observed on the last Friday of the year before.
    if dt.date(year + 1, 1, 1).weekday() == 5:
        out.add(dt.date(year, 12, 31))
    return out


def next_business_day(d: dt.date) -> dt.date:
    """The day itself, or the next that is neither a weekend nor a legal holiday."""
    while d.weekday() >= 5 or d in legal_holidays(d.year):
        d += DAY
    return d
