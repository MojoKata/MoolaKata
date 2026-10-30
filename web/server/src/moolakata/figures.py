"""Figures that combine accounts: a portfolio's value, contributions, returns and benchmark
(requirements S5.2), and the Dashboard's net worth (S5.3, S12.2.1). The server does the money
arithmetic; the browser only draws (S5.4)."""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from . import clock, valuation
from .ledger import performance as perf
from .ledger import types as atypes
from .store.entities.accounts import Account, Instrument
from .store.repos import ledger as repo

ZERO = Decimal(0)
RANGE_DAYS = {"1M": 31, "3M": 92, "1Y": 366, "3Y": 3 * 366, "5Y": 1827}


def first_day(range_: str, today: dt.date, earliest: dt.date | None) -> dt.date:
    if range_ == "YTD":
        return dt.date(today.year, 1, 1)
    if range_ == "All":
        return earliest or today
    return today - dt.timedelta(days=RANGE_DAYS[range_])


def step_for(first: dt.date, last: dt.date) -> int:
    days = (last - first).days
    return 1 if days <= 400 else max(1, days // 365)


@dataclass
class Combined:
    values: list[tuple[dt.date, Decimal]]
    flow: dict[dt.date, Decimal]
    byAccount: dict[str, list[tuple[dt.date, Decimal]]]


def combine(
    s: Session, accounts: list[Account], first: dt.date, last: dt.date, step: int
) -> Combined:
    by: dict[str, list[tuple[dt.date, Decimal]]] = {}
    flow: dict[dt.date, Decimal] = {}
    for a in accounts:
        led = repo.load(s, a)
        series = valuation.series(s, led, atypes.investing(a.type), first, last, step)
        flows = perf.flows(led.transactions)
        gone = a.deletedAt.date() if getattr(a, "deletedAt", None) else None
        if gone is not None:
            # A deleted account counts up to its deletion (R3.10); its value then leaves as a
            # withdrawal would, so the portfolio's returns don't take it as a loss.
            before = [(d, v) for d, v in series if d < gone]
            series = before + [(d, ZERO) for d, v in series if d >= gone]
            flows = {d: v for d, v in flows.items() if d < gone}
            if before and before[-1][1] and first <= gone <= last:
                flows[gone] = flows.get(gone, ZERO) - before[-1][1]
        by[a.id] = series
        for d, v in flows.items():
            flow[d] = flow.get(d, ZERO) + v
    days = sorted({d for series in by.values() for d, _ in series})
    totals = {d: ZERO for d in days}
    for series in by.values():
        for d, v in series:
            totals[d] += v
    return Combined(sorted(totals.items()), flow, by)


def earliest(s: Session, accounts: list[Account]) -> dt.date | None:
    days = [t.date for a in accounts for t in repo.load(s, a).transactions[:1]]
    return min(days) if days else None


def contributions(
    values: list[tuple[dt.date, Decimal]], flow: dict[dt.date, Decimal]
) -> list[tuple[dt.date, Decimal]]:
    """Net contributions since the series began, starting from its first value."""
    if not values:
        return []
    total = values[0][1]
    out = [(values[0][0], total)]
    prev = values[0][0]
    for day, _ in values[1:]:
        total += sum((v for d, v in flow.items() if prev < d <= day), ZERO)
        out.append((day, total))
        prev = day
    return out


def benchmark_index(
    s: Session, name: str, first: dt.date, last: dt.date
) -> list[tuple[dt.date, Decimal]]:
    """VT, SPY, or 60% VT and 40% BND rebalanced daily. The benchmarks' instruments are made
    at start (ensure_benchmarks), so the daily refresh loads their closes."""

    def closes(symbol: str) -> list[tuple[dt.date, Decimal]]:
        inst = s.scalars(
            select(Instrument).where(
                Instrument.symbol == symbol,
                Instrument.deleted == false(),
                Instrument.instrumentClass != "crypto",
            )
        ).first()
        if inst is None:
            return []
        pts = valuation.price_points(s, [inst.id], first, last).get(inst.id, [])
        return [(d, p) for d, p in pts if d >= first - dt.timedelta(days=7)]

    if name == "60-40":
        return perf.mix([(Decimal("0.6"), closes("VT")), (Decimal("0.4"), closes("BND"))])
    return closes(name)


def ensure_benchmarks(s: Session) -> None:
    """The instruments Performance compares with (S5.2.1), so their closes are loaded."""
    for symbol, name in (
        ("VT", "Vanguard Total World Stock ETF"),
        ("SPY", "SPDR S&P 500 ETF Trust"),
        ("BND", "Vanguard Total Bond Market ETF"),
    ):
        repo.instrument(s, symbol, name, "etf")


def period_returns(
    values: list[tuple[dt.date, Decimal]], flow: dict[dt.date, Decimal], today: dt.date
) -> dict[str, Decimal | None]:
    """Time-weighted returns for 1M, 3M, YTD and 1Y, and annualised for 3Y and 5Y; none when
    the history doesn't reach back that far."""
    out: dict[str, Decimal | None] = {}
    if not values:
        return dict.fromkeys(("1M", "3M", "YTD", "1Y", "3Y", "5Y"))
    started = next((d for d, v in values if v), values[0][0])
    for key in ("1M", "3M", "YTD", "1Y", "3Y", "5Y"):
        first = first_day(key, today, None)
        if first < started and key in ("3Y", "5Y"):
            out[key] = None
            continue
        window = [(d, v) for d, v in values if d >= max(first, started)]
        r = perf.twr(window, flow)
        if r is not None and key in ("3Y", "5Y"):
            r = perf.annualise(r, (window[-1][0] - window[0][0]).days)
        out[key] = r
    return out


def fmt_rate(r: Decimal | None) -> str | None:
    """A return as a percentage string with two places: "5.12"."""
    return None if r is None else str((r * 100).quantize(Decimal("0.01")))


def net_worth_accounts(s: Session, user_id: str, counted: set[str]) -> list[Account]:
    """What counts in a user's totals: their own accounts that count in net worth, and shared
    accounts they ticked Count in my totals on (S10.7)."""
    from . import access

    out = []
    for a, lvl in access.visible_accounts(s, user_id):
        if (lvl == "owner" and a.countInNetWorth) or (lvl != "owner" and a.id in counted):
            out.append(a)
    return out


def today() -> dt.date:
    return clock.today()
