"""The daily refresh and stored closes (requirements S4.4–S4.7).

Once a day after the US close (Settings › Prices), and on demand, every held or watched
instrument's close is loaded; history is backfilled when an instrument is first held. A source
that fails falls back to the next one for that class. Charts and screens read only the stored
closes, through `stored_closes`, never a source during a request.
"""

import datetime as dt
import json
import logging
from decimal import Decimal

from sqlalchemy import and_, false, func, insert, select
from sqlalchemy.orm import Session

from .. import clock, ids, options, valuation
from ..projections import taxtables
from ..store.entities.accounts import Account, Holding, Instrument, Transaction
from ..store.entities.assets import Item
from ..store.entities.prices import Price, PriceSource
from ..store.repos import secrets as secret_repo
from ..store.tables import prices as prices_table
from ..tasks import Stopping, TaskContext
from .base import SOURCES, Ref, SourceError, TickerSource

log = logging.getLogger("moolakata.prices")
BENCHMARKS = ("SPY", "VT", "BND")
BACKFILL_DAYS = 5 * 366
STALE_DAYS = {"crypto": 2}
STATEMENT_STALE_DAYS = 90


def trading_days_between(a: dt.date, b: dt.date) -> int:
    """Weekdays after a up to b: close enough to the US market's trading days to mark a
    price stale (S4.7)."""
    n, day = 0, a
    while day < b:
        day += dt.timedelta(days=1)
        if day.weekday() < 5:
            n += 1
    return n


def is_stale(cls: str, source: str, as_of: dt.date, today: dt.date) -> bool:
    if source in ("manual", "statement"):
        return (today - as_of).days > STATEMENT_STALE_DAYS
    if cls in STALE_DAYS:
        return (today - as_of).days > STALE_DAYS[cls]
    # An option's close older than the last trading day (S4.5); a stock's after two (S4.7).
    return trading_days_between(as_of, today) > (1 if cls == "option" else 2)


def stored_closes(
    s: Session, instrument_ids: list[str], day: dt.date
) -> dict[str, valuation.Price]:
    """The latest stored close on or before the day for each instrument."""
    if not instrument_ids:
        return {}
    latest = (
        select(Price.instrumentId, func.max(Price.date).label("d"))
        .where(Price.instrumentId.in_(instrument_ids), Price.date <= day, Price.deleted == false())
        .group_by(Price.instrumentId)
        .subquery()
    )
    rows = s.execute(
        select(Price, Instrument.instrumentClass)
        .join(latest, and_(latest.c.instrumentId == Price.instrumentId, latest.c.d == Price.date))
        .join(Instrument, Instrument.id == Price.instrumentId)
    ).all()
    today = clock.today()
    return {
        p.instrumentId: valuation.Price(
            p.close,
            p.date,
            "manual" if p.source == "manual" else "close",
            is_stale(cls, p.source, p.date, min(day, today)),
        )
        for p, cls in rows
    }


def close_history(
    s: Session, instrument_ids: list[str], first: dt.date, last: dt.date
) -> dict[str, list[tuple[dt.date, Decimal]]]:
    out: dict[str, list[tuple[dt.date, Decimal]]] = {}
    for p in s.scalars(
        select(Price)
        .where(
            Price.instrumentId.in_(instrument_ids),
            Price.date > first,
            Price.date <= last,
            Price.deleted == false(),
        )
        .order_by(Price.date)
    ):
        out.setdefault(p.instrumentId, []).append((p.date, p.close))
    return out


# Metal spot (instruments XAU, XAG, XPT, XPD), when no source serves metals itself: a proxy's
# symbol, its class, and the tax-table figure of metal per share (none: one ounce a token).
METAL_PROXIES = {
    "XAU": ("PAXG", "crypto", None),
    "XAG": ("SLV", "etf", "slvOzPerShare"),
    "XPT": ("PPLT", "etf", "ppltOzPerShare"),
    "XPD": ("PALL", "etf", "pallOzPerShare"),
}


def install() -> None:
    valuation.use_closes(stored_closes, close_history)


# ---------- the sources in use ----------


def preference(src: PriceSource) -> dict[str, int]:
    return json.loads(src.preference or "{}")


def enabled(s: Session, dev: bool) -> list[PriceSource]:
    rows = s.scalars(
        select(PriceSource).where(PriceSource.deleted == false(), PriceSource.enabled)
    ).all()
    return [r for r in rows if r.name in SOURCES and (dev or not SOURCES[r.name].dev_only)]


def hosts(s: Session, dev: bool) -> list[str]:
    return sorted({h for r in enabled(s, dev) for h in SOURCES[r.name].hosts})


def for_class(sources: list[PriceSource], cls: str) -> list[PriceSource]:
    """The sources that serve a class, in its order of preference."""
    serving = [r for r in sources if cls in SOURCES[r.name].classes and SOURCES[r.name].fetches]
    return sorted(serving, key=lambda r: (preference(r).get(cls, 999), r.createdAt))


# ---------- what needs a price ----------


def held(s: Session) -> set[str]:
    """The instruments an open lot holds, long or short, in a live account (S4.4): one sold
    or expired is no longer fetched."""
    from ..store.repos import ledger as repo

    accounts = s.scalars(
        select(Account).where(
            Account.deleted == false(),
            Account.id.in_(
                select(Transaction.accountId).where(
                    Transaction.instrumentId.is_not(None), Transaction.deleted == false()
                )
            )
            | Account.id.in_(select(Holding.accountId).where(Holding.deleted == false())),
        )
    ).all()
    return {
        lot.instrumentId for a in accounts for lot in repo.load(s, a).replay().open if lot.quantity
    }


def _held_by(s: Session, viewer: str) -> list[str]:
    """What the accounts the viewer can see hold, but cash."""
    from .. import access
    from ..store.repos import ledger as repo

    ids = {
        lot.instrumentId
        for a, _ in access.visible_accounts(s, viewer)
        for lot in repo.load(s, a).replay().open
        if lot.quantity
    }
    if not ids:
        return []
    return [
        i.id
        for i in s.scalars(select(Instrument).where(Instrument.id.in_(ids)))
        if i.instrumentClass not in ("cash", "money-market")
    ]


def priced(s: Session, benchmarks: bool = True) -> list[tuple[Instrument, dt.date]]:
    """Every instrument held in a live account, or used as a benchmark, with the first day
    its history is wanted. Without benchmarks: only what is held."""
    holding = held(s)
    firsts: dict[str, dt.date] = {}
    for iid, day in s.execute(
        select(Transaction.instrumentId, func.min(Transaction.date))
        .join(Account, Account.id == Transaction.accountId)
        .where(
            Transaction.instrumentId.is_not(None),
            Transaction.deleted == false(),
            Account.deleted == false(),
        )
        .group_by(Transaction.instrumentId)
    ):
        if iid in holding:
            firsts[iid] = day
    for iid, day in s.execute(
        select(Holding.instrumentId, func.min(Holding.asOf))
        .join(Account, Account.id == Holding.accountId)
        .where(Holding.deleted == false(), Account.deleted == false())
        .group_by(Holding.instrumentId)
    ):
        if iid in holding:
            firsts[iid] = min(day, firsts.get(iid, day))
    # Metals valued at spot (S1.10.2): their metal's spot, from the first one acquired.
    from ..assets import METAL_SYMBOLS

    for metal, day in s.execute(
        select(Item.metal, func.min(Item.acquiredOn))
        .join(Account, Account.id == Item.accountId)
        .where(Item.valuation == "spot", Item.deleted == false(), Account.deleted == false())
        .group_by(Item.metal)
    ):
        inst = s.scalars(
            select(Instrument).where(
                Instrument.symbol == METAL_SYMBOLS[metal], Instrument.deleted == false()
            )
        ).first()
        if inst is not None:
            firsts[inst.id] = min(day, firsts.get(inst.id, day))
    today = clock.today()
    for inst in s.scalars(
        select(Instrument).where(
            Instrument.symbol.in_(BENCHMARKS if benchmarks else ()), Instrument.deleted == false()
        )
    ):
        firsts.setdefault(inst.id, today - dt.timedelta(days=BACKFILL_DAYS))
    insts = {i.id: i for i in s.scalars(select(Instrument).where(Instrument.id.in_(firsts)))}
    return [
        (insts[i], firsts[i])
        for i in firsts
        if i in insts and insts[i].instrumentClass not in ("cash", "money-market")
    ]


def last_stored(s: Session) -> dict[str, dt.date]:
    return dict(
        s.execute(
            select(Price.instrumentId, func.max(Price.date))
            .where(Price.deleted == false(), Price.source != "manual")
            .group_by(Price.instrumentId)
        ).all()
    )


def store(
    s: Session, instrument_id: str, closes: list[tuple[dt.date, Decimal]], source: str
) -> int:
    """New closes are inserted in bulk; a fetched close that changed replaces the old one, but
    never a typed price."""
    if not closes:
        return 0
    have = {
        p.date: p
        for p in s.scalars(
            select(Price).where(
                Price.instrumentId == instrument_id, Price.date.in_([d for d, _ in closes])
            )
        )
    }
    now = clock.now()
    fresh = [
        {
            "id": ids.new_id("Price"),
            "instrumentId": instrument_id,
            "date": day,
            "close": close,
            "source": source,
            "fetchedAt": now,
            "createdAt": now,
            "updatedAt": now,
        }
        for day, close in closes
        if day not in have
    ]
    if fresh:
        s.execute(insert(prices_table.Price), fresh)
    n = len(fresh)
    for day, close in closes:
        old = have.get(day)
        if old is not None and old.source != "manual" and old.close != close:
            old.close, old.source, old.fetchedAt = close, source, now
            n += 1
    return n


# ---------- the refresh ----------


def build(server, src: PriceSource, ctx: TaskContext | None) -> TickerSource:
    cls = SOURCES[src.name]
    key = None
    if cls.needs_key:
        with server.db.read() as s:
            key = secret_repo.use(s, server.keys.secrets, "PriceSource", src.id, "apiKey")
    if ctx is not None:
        ctx.limits.set(src.name, cls.limits)
        wait = lambda: ctx.wait_for(src.name)  # noqa: E731
    else:
        wait = lambda: None  # noqa: E731
    return cls(server.http() if cls.hosts else None, key, wait)


def refresh(server, ctx: TaskContext | None = None) -> dict:
    """Load what is missing up to today for every priced instrument."""
    dev = server.config.dev
    today = clock.today()
    with server.db.read() as s:
        sources = enabled(s, dev)
        wanted = priced(s)
        last = last_stored(s)
    runs: dict[str, dict] = {r.id: {"ok": False, "error": None, "used": False} for r in sources}
    built: dict[str, TickerSource] = {}
    stored = missing = 0
    for inst, first in wanted:
        if ctx:
            ctx.check()
        start = (
            last[inst.id] + dt.timedelta(days=1)
            if inst.id in last
            else max(first - dt.timedelta(days=7), today - dt.timedelta(days=BACKFILL_DAYS))
        )
        if start > today:
            continue
        candidates = for_class(sources, inst.instrumentClass)
        ref = Ref(inst.id, inst.symbol, inst.instrumentClass)
        end = today
        if inst.instrumentClass == "option":
            # An option is fetched by its OCC ticker, and only until it expires (S4.4).
            with server.db.read() as s:
                c = options.contract_of(s, inst.id)
                under = s.get(Instrument, c.underlyingId) if c else None
            if c is None or under is None or c.expiry < start:
                continue
            ref = Ref(inst.id, options.occ(c.root or under.symbol, c), "option")
            end = min(today, c.expiry)
        per_share = None
        if not candidates and inst.symbol in METAL_PROXIES:
            # Metal spot from a proxy's closes, divided by the metal each share holds (S4.3).
            symbol, cls, figure = METAL_PROXIES[inst.symbol]
            candidates = for_class(sources, cls)
            ref = Ref(inst.id, symbol, cls)
            per_share = Decimal(1)
            if figure:
                with server.db.read() as s:
                    per_share = Decimal(str(taxtables.figures(s)[figure]))
        if not candidates:
            missing += 1
            continue
        for src in candidates:
            run = runs[src.id]
            run["used"] = True
            try:
                if src.id not in built:
                    built[src.id] = build(server, src, ctx)
                closes = built[src.id].history(ref, start, end)
            except Stopping:
                raise
            except Exception as e:
                # A bad answer fails that source for this instrument, never the refresh (S4.4).
                if not isinstance(e, SourceError):
                    log.warning("%s failed for %s: %r", src.name, inst.symbol, e)
                run["error"] = (
                    str(e) if isinstance(e, SourceError) else "an answer it couldn't read"
                )
                continue
            run["ok"] = True
            if per_share:
                closes = [(d, (c / per_share).quantize(Decimal("0.01"))) for d, c in closes]
            with server.db.tx() as s:
                stored += store(s, inst.id, closes, src.name)
            break
    now = clock.now()
    with server.db.tx() as s:
        for src in s.scalars(select(PriceSource).where(PriceSource.id.in_(list(runs)))):
            run = runs[src.id]
            if not run["used"]:
                continue
            src.lastRunAt = now
            if run["ok"]:
                src.lastOkAt = now
            src.lastError = run["error"] if not run["ok"] else None
    server.events.publish("prices", {"asOf": now.isoformat(), "stored": stored})
    used = [r for r in runs.values() if r["used"]]
    if used and not any(r["ok"] for r in used):
        raise SourceError(next(r["error"] for r in used if r["error"]))
    return {"stored": stored, "unpriced": missing}


def status(s: Session, dev: bool, viewer: str | None = None) -> dict:
    """The header's last refresh and whether held prices are stale (S12.5): what the viewer's
    accounts hold, with the prices they typed (S4.10); without a viewer, what is held."""
    rows = enabled(s, dev)
    last = max((r.lastOkAt for r in rows if r.lastOkAt), default=None)
    # Held prices only: the benchmarks every server watches leave a new server, which holds
    # nothing, with nothing to be stale.
    ids = [i.id for i, _ in priced(s, benchmarks=False)] if viewer is None else _held_by(s, viewer)
    today = clock.today()
    closes = stored_closes(s, ids, today)
    if viewer is not None:
        for t in valuation.typed(s, viewer, ids, None, today):
            if t.instrumentId not in closes or t.date >= closes[t.instrumentId].asOf:
                stale = is_stale("", "manual", t.date, today)
                closes[t.instrumentId] = valuation.Price(t.close, t.date, "manual", stale)
    stale = any(p.stale for p in closes.values()) or (bool(ids) and len(closes) < len(ids))
    return {"lastRefresh": last, "stale": stale and bool(ids), "sources": len(rows)}
