"""Statements expected (requirements S1.11.7): how often an account's institution issues
statements, set per account or following its type, learned from when its statements and
imports arrive, and when the next one is overdue."""

import calendar
import datetime as dt
import itertools
import json
from dataclasses import dataclass
from statistics import median

from . import types as atypes

INTERVALS = ("monthly", "quarterly", "yearly", "none")
MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12}
GRACE_DAYS = {"monthly": 15, "quarterly": 30, "yearly": 60}
QUARTERLY = ("401k", "403b", "457b", "529", "daf")
NEVER = ("crypto-wallet", "cash")
LEARN_FROM = 3  # statements or imports before an interval is learned


def default_interval(account_type: str, kept_by: list[str]) -> str:
    """Monthly for banking, cards, brokerage, IRAs, HSAs and loans; quarterly for workplace
    plans, 529s and donor-advised funds; none for cash on hand and other accounts kept by hand,
    watched wallets and physical assets."""
    if account_type in NEVER or atypes.GROUPS[account_type] == "physical-assets":
        return "none"
    if "file" not in kept_by:
        return "none"
    return "quarterly" if account_type in QUARTERLY else "monthly"


def kept_by(account) -> list[str]:
    try:
        return list(json.loads(account.keptBy or "[]"))
    except ValueError:
        return []


def interval(account) -> str:
    return account.statementInterval or default_interval(account.type, kept_by(account))


def add_months(day: dt.date, months: int) -> dt.date:
    """The same day so many months on; a month's last day stays its month's last day."""
    y, m = divmod(day.month - 1 + months, 12)
    year, month = day.year + y, m + 1
    last = calendar.monthrange(year, month)[1]
    if day.day == calendar.monthrange(day.year, day.month)[1]:
        return dt.date(year, month, last)
    return dt.date(year, month, min(day.day, last))


def _ends(imports) -> list[dt.date]:
    return sorted({i.coveredTo for i in imports if i.coveredTo is not None})


def learned(imports) -> str | None:
    """The interval the statements and imports arrive at, from three or more: the typical gap
    between the ends of what they cover."""
    ends = _ends(imports)
    if len(ends) < LEARN_FROM:
        return None
    gap = median((b - a).days for a, b in itertools.pairwise(ends))
    if gap < 20:
        return None  # downloads at odd times, not statements
    if gap <= 45:
        return "monthly"
    if gap <= 135:
        return "quarterly"
    return "yearly"


def proposal(account, imports) -> str | None:
    """A learned interval that differs from the one in force and wasn't dismissed."""
    seen = learned(imports)
    if seen is None or seen == interval(account) or seen == account.statementIntervalDismissed:
        return None
    return seen


@dataclass
class Overdue:
    periodStart: dt.date
    periodEnd: dt.date
    due: dt.date  # overdue from this day
    name: str  # the September statement


def name_of(every: str, start: dt.date, end: dt.date) -> str:
    if every == "monthly":
        return f"the {end:%B} statement"
    if every == "quarterly":
        return f"the {start:%B}–{end:%B} statement"
    return f"the {end.year} statement" if end.month == 12 else f"the year to {end:%B %Y} statement"


def due_after(every: str, last: dt.date) -> dt.date:
    """When the statement after one ending `last` is overdue: its interval, then its grace."""
    return add_months(last, MONTHS[every]) + dt.timedelta(days=GRACE_DAYS[every])


def stale_from(account, as_of: dt.date) -> dt.date:
    """The day a value read from a statement ending `as_of` is stale (S4.3): the day the
    statement after it is overdue (S1.11.7.3), so a quarterly plan's Mar 31 value is stale from
    Jul 30. An account that expects none counts as yearly: a value read long ago still is."""
    every = interval(account)
    return due_after("yearly" if every == "none" else every, as_of)


def overdue(account, imports, today: dt.date) -> Overdue | None:
    """The next statement after the last one covered, once its period and the grace after it
    have passed: a monthly statement ending Aug 31 is overdue from Oct 15."""
    every = interval(account)
    ends = _ends(imports)
    if every == "none" or not ends:
        return None
    last = ends[-1]
    end = add_months(last, MONTHS[every])
    due = due_after(every, last)
    if today < due:
        return None
    start = last + dt.timedelta(days=1)
    return Overdue(start, end, due, name_of(every, start, end))
