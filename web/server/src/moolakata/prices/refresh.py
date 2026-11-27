"""The daily refresh and stored closes (requirements S4.4–S4.7).

Once a day after the US close (Settings › Prices), and on demand, every held or watched
instrument's close is loaded; history is backfilled when an instrument is first held. A source
that fails falls back to the next one for that class. Charts and screens read only the stored
closes, through `stored_closes`, never a source during a request.
"""

import datetime as dt
import json
import logging
import math
from decimal import Decimal

from sqlalchemy import and_, false, func, insert, select, update
from sqlalchemy.orm import Session

from .. import clock, ids, options, valuation
from ..projections import taxtables
from ..store.entities.accounts import Account, Holding, Instrument, OptionContract, Transaction
from ..store.entities.assets import Item
from ..store.entities.prices import Price, PriceSource
from ..store.repos import secrets as secret_repo
from ..store.tables import prices as prices_table
from ..tasks import Stopping, TaskContext
from .base import SOURCES, NotListed, Ref, SourceError, TickerSource

log = logging.getLogger("moolakata.prices")
BENCHMARKS = ("SPY", "VT", "BND")
BACKFILL_DAYS = 5 * 366
STALE_DAYS = {"crypto": 2}


def trading_days_between(a: dt.date, b: dt.date) -> int:
    """Weekdays after a up to b: close enough to the US market's trading days to mark a
    price stale (S4.7)."""
    n, day = 0, a
    while day < b:
        day += dt.timedelta(days=1)
        if day.weekday() < 5:
            n += 1
    return n


def is_stale(cls: str, as_of: dt.date, today: dt.date) -> bool:
    """A fetched close's staleness by its class (S4.7). Only a fetching source stores closes; a
    typed price is a TypedPrice, stale after 90 days (`valuation.TYPED_STALE_DAYS`)."""
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
        .join(Instrument)
    ).all()
    today = clock.today()
    return {
        p.instrumentId: valuation.Price(
            p.close,
            p.date,
            "close",
            is_stale(cls, p.date, min(day, today)),
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
    return json.loads(src.preference)


def enabled(s: Session, dev: bool) -> list[PriceSource]:
    rows = s.scalars(
        select(PriceSource).where(PriceSource.deleted == false(), PriceSource.enabled)
    ).all()
    return [r for r in rows if r.name in SOURCES and (dev or not SOURCES[r.name].dev_only)]


def hosts(s: Session, dev: bool) -> list[str]:
    return sorted({h for r in enabled(s, dev) for h in SOURCES[r.name].hosts})


def for_class(sources: list[PriceSource], cls: str) -> list[PriceSource]:
    """The sources that serve a class, in its order of preference: those not ranked for it
    after every one ranked, oldest first."""
    serving = [r for r in sources if cls in SOURCES[r.name].classes and SOURCES[r.name].fetches]
    return sorted(serving, key=lambda r: (preference(r).get(cls, math.inf), r.createdAt))


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


def _held_by(s: Session, viewer: str) -> dict[str, list[str]]:
    """What the accounts the viewer can see hold, but cash, by each account's owner: whose
    prices value it (S4.10)."""
    from .. import access
    from ..store.repos import ledger as repo

    by: dict[str, set[str]] = {}
    for a, _ in access.accounts(s, viewer):
        held = {lot.instrumentId for lot in repo.load(s, a).replay().open if lot.quantity}
        if held:
            by.setdefault(a.ownerId, set()).update(held)
    if not by:
        return {}
    cash = set(
        s.scalars(
            select(Instrument.id).where(
                Instrument.id.in_(set().union(*by.values())),
                Instrument.instrumentClass.in_(("cash", "money-market")),
            )
        )
    )
    return {owner: sorted(ids - cash) for owner, ids in by.items() if ids - cash}


def priced(s: Session) -> list[tuple[Instrument, dt.date]]:
    """Every instrument held in a live account, or used as a benchmark, with the first day
    its history is wanted."""
    holding = held(s)
    firsts: dict[str, dt.date] = {}
    for iid, day in s.execute(
        select(Transaction.instrumentId, func.min(Transaction.date))
        .join(Account)
        .where(Transaction.deleted == false(), Account.deleted == false())
        .group_by(Transaction.instrumentId)
    ):
        # Cash moves, of no instrument, come as one row of none: never held.
        if iid in holding:
            firsts[iid] = day
    for iid, day in s.execute(
        select(Holding.instrumentId, func.min(Holding.asOf))
        .join(Account)
        .where(Holding.deleted == false(), Account.deleted == false())
        .group_by(Holding.instrumentId)
    ):
        if iid in holding:
            firsts[iid] = min(day, firsts.get(iid, day))
    # What an open option needs priced (S4.4's "watched"): its underlying, or an
    # adjusted contract's deliverable parts, from the option's first trade, so its expiry is
    # decided by a close and its intrinsic value has one, held or not.
    for c in s.scalars(
        select(OptionContract).where(
            OptionContract.instrumentId.in_([i for i in holding if i in firsts]),
            OptionContract.deleted == false(),
        )
    ):
        day = firsts[c.instrumentId]
        parts = [x["instrumentId"] for x in json.loads(c.deliverable)] if c.deliverable else []
        for iid in parts or [c.underlyingId]:
            firsts[iid] = min(day, firsts.get(iid, day))
    # Metals valued at spot (S1.10.2): their metal's spot, from the first one acquired.
    from ..assets import METAL_SYMBOLS

    for metal, day in s.execute(
        select(Item.metal, func.min(Item.acquiredOn))
        .join(Account)
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
        select(Instrument).where(Instrument.symbol.in_(BENCHMARKS), Instrument.deleted == false())
    ):
        firsts.setdefault(inst.id, today - dt.timedelta(days=BACKFILL_DAYS))
    # Every id here is an instrument's: a key, or a contract's part, and none is ever removed.
    insts = {i.id: i for i in s.scalars(select(Instrument).where(Instrument.id.in_(firsts)))}
    return [
        (insts[i], firsts[i])
        for i in firsts
        if insts[i].instrumentClass not in ("cash", "money-market")
    ]


def last_stored(s: Session) -> dict[str, dt.date]:
    return dict(
        s.execute(
            select(Price.instrumentId, func.max(Price.date))
            .where(Price.deleted == false())
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
        if old is not None and old.close != close:
            old.close, old.source, old.fetchedAt = close, source, now
            n += 1
    return n


# ---------- the refresh ----------


def build(server, src: PriceSource, ctx: TaskContext | None) -> TickerSource:
    """A source ready to call: its key, a client if it calls out, and its limits kept by the
    task it runs in (a call outside a task waits for nothing)."""
    cls = SOURCES[src.name]
    key = None
    if cls.needs_key:
        # Secrets have no access view: named or not, the reason changes nothing read.
        with server.db.read(unscoped="prices.refresh: build") as s:  # pragma: no mutate
            key = secret_repo.use(s, server.keys.secrets, "PriceSource", src.id, "apiKey")
    client = server.http() if cls.hosts else None
    if ctx is None:
        return cls(client, key)
    ctx.limits.set(src.name, cls.limits)
    return cls(client, key, lambda: ctx.wait_for(src.name))


def refresh(server, ctx: TaskContext | None = None) -> dict:
    """Load what is missing up to today for every priced instrument."""
    dev = server.config.dev
    today = clock.today()
    with server.db.read(unscoped="prices.refresh: refresh") as s:
        sources = enabled(s, dev)
        wanted = priced(s)
        last = last_stored(s)
    # A source tried either answers ("ok") or fails, and then has its "error".
    runs: dict[str, dict] = {r.id: {"ok": False, "used": False} for r in sources}
    built: dict[str, TickerSource] = {}
    stored = missing = 0
    # Instruments no source knows (S4.2.2), and those a failure leaves unknown either way.
    misses: set[str] = set()
    unsure: set[str] = set()
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
            # An option is fetched by its OCC ticker, and only until it expires (S4.4); one a
            # file named without a contract MoolaKata could read is not fetched at all.
            # Contracts and instruments have no access view: named or not, the reason changes
            # nothing read.
            with server.db.read(unscoped="prices.refresh: refresh") as s:  # pragma: no mutate
                c = options.contract_of(s, inst.id)
                root = (c.root or s.get(Instrument, c.underlyingId).symbol) if c else None
            if c is None or c.expiry < start:
                continue
            ref = Ref(inst.id, options.occ(root, c), "option")
            end = min(today, c.expiry)
        # Only tested for truth: None and "" alike leave the closes undivided.
        per_share = None  # pragma: no mutate
        if not candidates and inst.symbol in METAL_PROXIES:
            # Metal spot from a proxy's closes, divided by the metal each share holds (S4.3).
            symbol, cls, figure = METAL_PROXIES[inst.symbol]
            candidates = for_class(sources, cls)
            ref = Ref(inst.id, symbol, cls)
            per_share = Decimal(1)
            if figure:
                # Tax figures have no access view: named or not, the reason changes nothing read.
                with server.db.read(unscoped="prices.refresh: refresh") as s:  # pragma: no mutate
                    per_share = Decimal(str(taxtables.figures(s)[figure]))
        if not candidates:
            missing += 1
            continue
        # Whether a source gave a close; whether every one asked said it doesn't know the
        # symbol, or knew no close of it.
        known, unknown = False, True
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
                unknown = unknown and isinstance(e, NotListed)
                continue
            run["ok"] = True
            known, unknown = bool(closes), unknown and not closes
            if per_share:
                closes = [(d, (c / per_share).quantize(Decimal("0.01"))) for d, c in closes]
            # Closes have no access view: named or not, the reason changes nothing written.
            with server.db.tx(unscoped="prices.refresh: refresh") as s:  # pragma: no mutate
                stored += store(s, inst.id, closes, src.name)
            break
        # A symbol someone typed that no source knows (S4.2.2): an option's ticker and a metal's
        # proxy are MoolaKata's own, and one with a close stored, then or before, is known.
        if inst.instrumentClass == "option" or per_share is not None or known or inst.id in last:
            continue
        (misses if unknown else unsure).add(inst.id)
    now = clock.now()
    with server.db.tx(unscoped="prices.refresh: refresh") as s:
        for src in s.scalars(select(PriceSource).where(PriceSource.id.in_(list(runs)))):
            run = runs[src.id]
            if not run["used"]:
                continue
            src.lastRunAt = now
            if run["ok"]:
                src.lastOkAt = now
            src.lastError = run["error"] if not run["ok"] else None
        # A miss is kept from the first refresh of a run of them: cleared by a close, by its
        # being no longer held, or by a refresh with no source to ask; one a failure left
        # unknown keeps what it had.
        s.execute(
            update(Instrument)
            .where(Instrument.id.in_(misses), Instrument.priceMissedAt.is_(None))
            .values(priceMissedAt=now)
            .execution_options(synchronize_session=False)
        )
        s.execute(
            update(Instrument)
            .where(Instrument.priceMissedAt.is_not(None), Instrument.id.not_in(misses | unsure))
            .values(priceMissedAt=None)
            .execution_options(synchronize_session=False)
        )
    server.events.publish("prices", {"asOf": now.isoformat(), "stored": stored})
    used = [r for r in runs.values() if r["used"]]
    if used and not any(r["ok"] for r in used):
        raise SourceError(next(r["error"] for r in used if r["error"]))
    return {"stored": stored, "unpriced": missing, "unknown": len(misses)}


def status(s: Session, dev: bool, viewer: str) -> dict:
    """The header's last refresh and whether held prices are stale (S12.5): each holding the
    viewer can see judged by the price that values it for its account's owner (S4.10), stale by
    that price's own rule (S4.3, S4.7), an option at intrinsic value by its underlying's (S3.7).
    Held prices only: the benchmarks every server watches leave a new server, which holds
    nothing, with nothing to be stale."""
    rows = enabled(s, dev)
    last = max((r.lastOkAt for r in rows if r.lastOkAt), default=None)
    today = clock.today()
    stale = False
    for owner, held_ids in _held_by(s, viewer).items():
        found = valuation.prices(s, held_ids, today, owner=owner)
        for iid in held_ids:
            p = found.get(iid) or valuation.intrinsic(s, iid, today, owner)
            # One held with no price at all is stale too.
            stale = stale or p is None or p.stale
    return {"lastRefresh": last, "stale": stale, "sources": len(rows)}
