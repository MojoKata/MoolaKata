"""Reconciliation (requirements S1.11): quiet, automatic checks for an account kept from files.

Coverage shows the periods the imports cover and flags gaps and overlaps; each balance the
institution reported is compared with MoolaKata's balance that day; a mismatch shows what is
suspect between the last matching balance and this one.
"""

import datetime as dt
import itertools
from dataclasses import dataclass, field
from decimal import Decimal

from . import balances, expected

ZERO = Decimal(0)


@dataclass
class Period:
    start: dt.date
    end: dt.date
    importIds: list[str]


@dataclass
class Coverage:
    periods: list[Period]
    gaps: list[tuple[dt.date, dt.date]]
    overlaps: list[tuple[dt.date, dt.date]]


def coverage(imports: list) -> Coverage:
    # A statement kept without reading covers nothing: its lines were never added (S1.3.3.6).
    spans = sorted(
        (i.coveredFrom, i.coveredTo, i.id)
        for i in imports
        if i.coveredFrom and i.coveredTo and getattr(i, "format", None) != "kept"
    )
    periods: list[Period] = []
    overlaps = []
    for start, end, iid in spans:
        if periods and start <= periods[-1].end + dt.timedelta(days=1):
            last = periods[-1]
            if start <= last.end:
                overlaps.append((start, min(end, last.end)))
            last.end = max(last.end, end)
            last.importIds.append(iid)
        else:
            periods.append(Period(start, end, [iid]))
    gaps = [
        (a.end + dt.timedelta(days=1), b.start - dt.timedelta(days=1))
        for a, b in itertools.pairwise(periods)
    ]
    return Coverage(periods, gaps, overlaps)


@dataclass
class Suspects:
    duplicates: list[list[str]] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    gaps: list[tuple[dt.date, dt.date]] = field(default_factory=list)
    firstParting: str | None = None


@dataclass
class Check:
    date: dt.date
    reported: Decimal
    computed: Decimal
    source: str
    ref: str | None
    windowFrom: dt.date | None = None
    suspects: Suspects | None = None

    @property
    def difference(self) -> Decimal:
        return self.reported - self.computed

    @property
    def ok(self) -> bool:
        return self.difference == 0


def duplicates(transactions: list) -> list[list[str]]:
    """Identical rows on one day, and rows a file gave the same id (a FITID it repeated), not
    yet answered *both real* (S1.11.5)."""
    groups: dict[tuple, list] = {}
    for t in transactions:
        if t.duplicateAnswer == "both-real":
            continue
        key = (t.date, t.amount, (t.payee or t.payeeRaw or "").casefold(), t.instrumentId)
        groups.setdefault(key, []).append(t.id)
        fit = t.fitId
        if fit:
            base, _, n = fit.rpartition("#")
            groups.setdefault(("fitId", base if base and n.isdigit() else fit), []).append(t.id)
    out: list[list[str]] = []
    for ids in groups.values():
        if len(ids) > 1 and ids not in out:
            out.append(ids)
    return out


def first_parting(start: balances.Opening, transactions: list) -> str | None:
    """With a running-balance column, the first row where the balances part (S1.11.3)."""
    running = start.balance
    for t in sorted(transactions, key=lambda t: (t.date, t.createdAt, t.id)):
        running += t.amount
        if t.runningBalance is not None and t.runningBalance != running:
            return t.id
    return None


def checks(
    start: balances.Opening, transactions: list, anchors: list, cover: Coverage
) -> list[Check]:
    out = []
    last_ok: dt.date | None = None
    for day, reported, source, ref in balances.points(anchors, transactions):
        computed = balances.balance_on(day, start, transactions)
        c = Check(day, reported, computed, source, ref)
        if c.ok:
            last_ok = day
        else:
            c.windowFrom = last_ok
            inside = [
                t for t in transactions if (last_ok is None or t.date > last_ok) and t.date <= day
            ]
            c.suspects = Suspects(
                duplicates=duplicates(inside),
                changed=[t.id for t in inside if t.amountWas is not None],
                gaps=[g for g in cover.gaps if (last_ok is None or g[1] > last_ok) and g[0] <= day],
                firstParting=first_parting(start, transactions)
                if source == "running-balance"
                else None,
            )
        out.append(c)
    return out


def needs_anchor(account, imports: list, today: dt.date) -> bool:
    """The account's next statement or import is overdue (S1.11.7.3): the Reconcile tab asks
    for one, or for a balance typed from the institution's site (S1.11.2)."""
    return expected.overdue(account, imports, today) is not None


VALUE_TOLERANCE = Decimal("0.005")  # half a percent: prices a day apart, rounding


@dataclass
class ValueCheck:
    """A statement's ending value against what the account was worth that day."""

    date: dt.date
    reported: Decimal
    computed: Decimal

    @property
    def difference(self) -> Decimal:
        return self.reported - self.computed

    @property
    def ok(self) -> bool:
        return abs(self.difference) <= max(Decimal(1), abs(self.reported) * VALUE_TOLERANCE)


def value_checks(s, ledger, anchors: list) -> list[ValueCheck]:
    from .. import valuation
    from . import types as atypes

    investing = atypes.investing(ledger.account.type)
    return [
        ValueCheck(a.date, a.balance, valuation.account_value(s, ledger, investing, a.date))
        for a in sorted(anchors, key=lambda a: a.date)
        if a.source == "statement-value"
    ]
