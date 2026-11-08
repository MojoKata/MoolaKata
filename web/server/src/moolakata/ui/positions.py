"""Positions (requirements S3.1, S3.9): every instrument held in an account the user can see,
open while any lot is open and closed when none is, with its lots' holding periods; each
closing trade with what it realized; and realized and unrealized gains grouped by year, month,
account, instrument or term."""

import datetime as dt
from collections import defaultdict
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request

from .. import access, clock, options, valuation
from ..ledger import types as atypes
from ..store.entities.accounts import Instrument, Transaction
from ..store.repos import ledger as repo
from .conventions import ExactRoute, Model, Money, Quantity, Ratio
from .deps import Caller, caller, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["positions"])
ZERO = Decimal(0)
KINDS = {
    "stocks": ("equity", "etf", "mutual-fund", "bond", "money-market", "other"),
    "options": ("option",),
    "crypto": ("crypto",),
}


class LotOut(Model):
    acquiredOn: dt.date  # the day bought
    # A wash sale's replacement: held from the sold shares' purchase, for the term (S3.8.4).
    heldFrom: dt.date | None
    quantity: Quantity
    basis: Money | None
    days: int
    longTerm: bool | None  # None: shares moved in, the day bought missing (S2.2)


class OpenRow(Model):
    accountId: str
    accountName: str
    instrumentId: str
    symbol: str
    name: str | None
    instrumentClass: str
    side: str  # long or short
    quantity: Quantity
    cost: Money | None  # the basis, or for a short position the credit
    averageCost: Quantity | None
    value: Money | None
    priceSource: str | None  # close, manual, intrinsic, statement, trade
    unrealized: Money | None
    unrealizedPct: Ratio | None
    realized: Money  # all its closes so far
    term: str  # short, long, mixed, or unknown (a lot whose day bought is missing)
    days: int  # since the oldest open lot
    lots: list[LotOut]
    expiry: dt.date | None = None  # an option's
    daysToExpiry: int | None = None
    inTheMoney: bool | None = None  # by the underlying's latest close


class ClosedRow(Model):
    saleId: str | None
    accountId: str
    accountName: str
    instrumentId: str
    symbol: str
    instrumentClass: str
    side: str
    quantity: Quantity
    opened: dt.date | None  # None: a part's day bought is missing (moved in, or no lot)
    closed: dt.date
    how: str  # sold, moved out, expired, assigned, exercised
    proceeds: Money
    cost: Money | None
    realized: Money | None
    washDisallowed: Money  # a wash sale's loss moved to its replacement (S3.8)
    term: str


class Expiring(Model):
    symbol: str
    days: int
    inTheMoney: bool | None


class Summary(Model):
    unrealized: Money
    expiringSoon: list[Expiring]  # options expiring within 7 days
    realizedThisYear: Money
    realizedShort: Money
    realizedLong: Money


class PositionsView(Model):
    summary: Summary
    open: list[OpenRow]
    closed: list[ClosedRow]


def _long_term(acquired: dt.date, day: dt.date) -> bool:
    from ..ledger.lots import long_term

    return long_term(acquired, day)


def _term(flags: list[bool | None]) -> str:
    if any(f is None for f in flags):
        return "unknown"  # a lot whose day bought is missing (CR3-73, CR3-415)
    if all(flags):
        return "long"
    if not any(flags):
        return "short"
    return "mixed"


def _how(t: Transaction) -> str:
    """How a closing trade closed: in words, or its kind."""
    return {
        "sell": "sold",
        "sell-to-close": "sold",
        "buy-to-close": "bought back",
        "expire": "expired",
        "assign": "assigned",
        "exercise": "exercised",
        "option-adjust": "adjusted",
        "transfer-out": "moved out",
    }.get(t.kind, t.kind)


def gather(s, c: Caller, classes: tuple[str, ...] | None = None):
    """The open rows, the closing trades, and every disposal, for the user's investing
    accounts; with `classes`, only those of instruments of these classes."""
    today = clock.today()
    accts = [a for a, _ in access.accounts(s, c.id) if atypes.investing(a.type)]
    open_rows, closed_rows, disposals = [], [], []
    insts: dict[str, Instrument] = {}
    for a in accts:
        led = repo.load(s, a)
        rp = led.replay()
        realized: dict[str, Decimal] = defaultdict(lambda: ZERO)
        by_sale: dict[tuple, list] = defaultdict(list)
        for d in rp.disposals:
            if d.gain is not None:
                realized[d.instrumentId] += d.gain
            by_sale[(d.saleId, d.instrumentId)].append(d)
            disposals.append((a, d))
        ids = {lot.instrumentId for lot in rp.open} | {d.instrumentId for d in rp.disposals}
        for iid in ids:
            if iid not in insts:
                insts[iid] = s.get(Instrument, iid)
        # Each instrument with a lot open is a position, valued, in the order its first lot
        # opened: its quantity and cost are its lots' (no cost when a basis is missing).
        for p in valuation.positions(s, led):
            iid, qty, cost, value = p.instrumentId, p.quantity, p.costBasis, p.value
            inst = insts[iid]
            if classes and inst.instrumentClass not in classes:
                continue
            if not qty:
                continue
            lots = sorted(
                (lot for lot in rp.open if lot.instrumentId == iid), key=lambda x: x.acquiredOn
            )
            gain = value - cost if value is not None and cost is not None else None
            lots_out = [
                LotOut(
                    acquiredOn=lot.acquiredOn,
                    heldFrom=lot.heldFrom,
                    quantity=lot.quantity,
                    basis=lot.basis,
                    days=(today - (lot.heldFrom or lot.acquiredOn)).days,
                    longTerm=None
                    if lot.acquiredMissing
                    else _long_term(lot.heldFrom or lot.acquiredOn, today),
                )
                for lot in lots
            ]
            extra = {}
            oc = options.contract_of(s, iid)  # none for an instrument that isn't an option
            if oc is not None:
                under = options.per_share(s, oc, today, led.account.ownerId)
                extra = {
                    "expiry": oc.expiry,
                    "daysToExpiry": (oc.expiry - today).days,
                    "inTheMoney": options.in_the_money(oc, under[0]) if under else None,
                }
            open_rows.append(
                OpenRow(
                    accountId=a.id,
                    accountName=a.name,
                    instrumentId=iid,
                    symbol=inst.symbol,
                    name=inst.name,
                    instrumentClass=inst.instrumentClass,
                    side="short" if qty < 0 else "long",
                    quantity=qty,
                    cost=cost,
                    averageCost=(cost / qty).quantize(Decimal("0.0001")) if cost and qty else None,
                    value=value,
                    priceSource=p.price.source if p.price else None,
                    unrealized=gain,
                    unrealizedPct=round(float(gain / abs(cost) * 100), 2)
                    if gain is not None and cost
                    else None,
                    realized=realized[iid],
                    term=_term([x.longTerm for x in lots_out]),
                    days=(today - (lots[0].heldFrom or lots[0].acquiredOn)).days,
                    lots=lots_out,
                    **extra,
                )
            )
        for (sale, iid), ds in by_sale.items():
            inst = insts[iid]
            if classes and inst.instrumentClass not in classes:
                continue
            # Every disposal is a transaction's: its sale, close, expiry or action.
            t = s.get(Transaction, sale)
            known = [d.basis for d in ds if d.basis is not None]
            cost = sum(known, ZERO) if len(known) == len(ds) else None
            proceeds = sum((d.proceeds for d in ds), ZERO)
            unknown = any(d.acquiredMissing or d.lotMissing for d in ds)
            closed_rows.append(
                ClosedRow(
                    saleId=sale,
                    accountId=a.id,
                    accountName=a.name,
                    instrumentId=iid,
                    symbol=inst.symbol,
                    instrumentClass=inst.instrumentClass,
                    side="short" if any((d.basis or ZERO) < 0 for d in ds) else "long",
                    quantity=sum((d.quantity for d in ds), ZERO),
                    # A part without its day bought leaves the day opened unknown, as its
                    # term is, never the sale's own day (CR3-435).
                    opened=None if unknown else min(d.acquiredOn for d in ds),
                    closed=ds[0].soldOn,
                    how=_how(t),
                    proceeds=proceeds,
                    cost=cost,
                    realized=(sum((d.gain for d in ds), ZERO) if cost is not None else None),
                    washDisallowed=sum((d.adjustment for d in ds), ZERO),
                    # A sale without a lot to match has no day bought, as shares moved in
                    # without one: its term is unknown (CR3-415).
                    term=_term(
                        [None if d.acquiredMissing or d.lotMissing else d.longTerm for d in ds]
                    ),
                )
            )
    open_rows.sort(key=lambda r: -(abs(r.value) if r.value is not None else ZERO))
    closed_rows.sort(key=lambda r: r.closed, reverse=True)
    return open_rows, closed_rows, disposals, insts


@router.get("/positions", response_model=PositionsView)
def list_positions(
    request: Request,
    kind: Literal["all", "stocks", "options", "crypto"] = "all",
    c: Caller = Depends(caller),
):
    """The open and closed positions, of one kind of instrument or all; another kind is
    refused, not read as all (R3.11)."""
    year = clock.today().year
    with server(request).db.read(user=c.id) as s:
        open_rows, closed_rows, disposals, _ = gather(s, c, KINDS.get(kind))
        this_year = [d for _, d in disposals if d.soldOn.year == year and d.gain is not None]
        return PositionsView(
            summary=Summary(
                unrealized=sum((r.unrealized or ZERO for r in open_rows), ZERO),
                expiringSoon=[
                    Expiring(symbol=r.symbol, days=r.daysToExpiry, inTheMoney=r.inTheMoney)
                    for r in open_rows
                    if r.daysToExpiry is not None and r.daysToExpiry <= 7
                ],
                realizedThisYear=sum((d.gain for d in this_year), ZERO),
                realizedShort=sum((d.gain for d in this_year if not d.longTerm), ZERO),
                realizedLong=sum((d.gain for d in this_year if d.longTerm), ZERO),
            ),
            open=open_rows,
            closed=closed_rows,
        )


class GainGroup(Model):
    key: str
    label: str
    shortTerm: Money
    longTerm: Money
    total: Money


class GainsView(Model):
    by: str
    year: int | None
    realized: list[GainGroup]
    unrealized: list[GainGroup]


@router.get("/positions/gains", response_model=GainsView)
def gains(
    request: Request,
    by: Literal["year", "month", "account", "instrument", "term"] = "year",
    year: int | None = Query(None, ge=1),
    c: Caller = Depends(caller),
):
    """Realized gains grouped by year, month, account, instrument or term (S3.9), and
    unrealized gains now, by account or instrument; of one year, or every year with none.
    Another grouping or a year of 0 is refused, not read as the default or as all (R3.11)."""
    with server(request).db.read(user=c.id) as s:
        open_rows, _, disposals, insts = gather(s, c)
        groups: dict[str, list[Decimal]] = {}
        labels: dict[str, str] = {}
        for a, d in disposals:
            if d.gain is None or (year is not None and d.soldOn.year != year):
                continue
            if by == "year":
                key = label = str(d.soldOn.year)
            elif by == "month":
                key = f"{d.soldOn:%Y-%m}"
                label = f"{d.soldOn:%B %Y}"
            elif by == "account":
                key, label = a.id, a.name
            elif by == "instrument":
                key, label = d.instrumentId, insts[d.instrumentId].symbol
            else:
                key = "long" if d.longTerm else "short"
                label = "Long term" if d.longTerm else "Short term"
            g = groups.setdefault(key, [ZERO, ZERO])
            g[1 if d.longTerm else 0] += d.gain
            labels[key] = label
        realized = [
            GainGroup(key=k, label=labels[k], shortTerm=v[0], longTerm=v[1], total=v[0] + v[1])
            for k, v in sorted(groups.items(), reverse=by in ("year", "month"))
        ]
        un: dict[str, list[Decimal]] = {}
        un_labels: dict[str, str] = {}
        for r in open_rows:
            if r.unrealized is None:
                continue
            key, label = (
                (r.instrumentId, r.symbol) if by == "instrument" else (r.accountId, r.accountName)
            )
            g = un.setdefault(key, [ZERO, ZERO])
            g[1 if r.term == "long" else 0] += r.unrealized
            un_labels[key] = label
        return GainsView(
            by=by,
            year=year,
            realized=realized,
            unrealized=[
                GainGroup(
                    key=k, label=un_labels[k], shortTerm=v[0], longTerm=v[1], total=v[0] + v[1]
                )
                for k, v in sorted(un.items(), key=lambda x: -(x[1][0] + x[1][1]))
            ],
        )


class OptionTradeRow(Model):
    accountId: str
    accountName: str
    instrumentId: str
    symbol: str
    side: str  # long or short: how it was opened
    contracts: Quantity  # the most open at once
    opened: dt.date
    closed: dt.date | None  # None while any of it is open
    how: str | None  # sold, bought back, moved out, expired, assigned, exercised
    premiumIn: Money  # credits received, after fees
    premiumOut: Money  # debits paid, with fees
    value: Money | None  # what is still open is worth now
    pl: Money | None  # in less out, plus what is open
    # The per-trade return's base (S3.9.2): a long option's premium, a short one's strike on
    # every share its contracts cover; a leg of a strategy, its strategy's capital at risk at
    # open, where that is finite.
    capitalRequired: Money
    returnPct: Ratio | None
    # A trade that ran through its contract's adjustment (S3.10.4): the contract it opened on,
    # and the day of the latest adjustment.
    adjustedFrom: str | None = None
    adjustedOn: dt.date | None = None


OPTION_KINDS = ("buy-to-open", "sell-to-open", "buy-to-close", "sell-to-close")
PCT = Decimal("0.01")
ENDS = ("expire", "assign", "exercise", "option-adjust")
MOVES = ("transfer-in", "transfer-out")  # contracts moved in or out (S2.2)


@router.get("/positions/option-trades", response_model=list[OptionTradeRow])
def option_trades(request: Request, c: Caller = Depends(caller)):
    """Each option trade (S3.9): from the first contract opened to the last one closed, with the
    premium in and out, its P/L and its return on the capital it required. A long option
    requires its premium; a short one the strike on every contract's shares, cash for a put and
    the shares for a call."""
    out: list[OptionTradeRow] = []
    with server(request).db.read(user=c.id) as s:
        for a, _ in access.accounts(s, c.id):
            if not atypes.investing(a.type):
                continue
            led = repo.load(s, a)
            positions = {p.instrumentId: p for p in valuation.positions(s, led)}
            out.extend(_account_trades(s, a, led, positions))
        # A leg in a strategy takes its strategy's capital at risk at open, where that is
        # finite (S3.9.2): an unlimited one leaves the trade's own capital required.
        from ..options import strategies as strat

        at_open: dict[tuple[str, str], Decimal] = {}
        for a, _ in access.accounts(s, c.id):
            mine = strat.of_account(s, a.id) if atypes.investing(a.type) else []
            if not mine:
                continue
            book = strat.Book(s, repo.load(s, a))
            for st in mine:
                v = strat.view(book, st)
                if v.riskAtOpen:
                    for x in v.legs:
                        at_open[(a.id, x.instrumentId)] = v.riskAtOpen
        for r in out:
            risk = at_open.get((r.accountId, r.instrumentId))
            if risk is not None:
                r.capitalRequired = risk
                r.returnPct = (r.pl / risk * 100).quantize(PCT) if r.pl is not None else None
    open_rows = [r for r in out if r.closed is None]
    done = sorted((r for r in out if r.closed is not None), key=lambda r: r.closed, reverse=True)
    return sorted(open_rows, key=lambda r: r.opened, reverse=True) + done


def _adjusted_long(led, t: Transaction) -> bool:
    """Whether the contract an adjustment came from was held long when it was adjusted, by its
    trades and moves up to the adjustment's day: the lots take every other trade of that day
    before the adjustment, one typed after it too."""
    # The new half always has its old one: deleting either deletes both.
    old = next(y.instrumentId for y in led.transactions if y.id == t.transferId)
    held = ZERO
    for x in led.transactions:
        if x.instrumentId != old or x.date > t.date:
            continue
        if x.kind in ("buy-to-open", "buy-to-close", "transfer-in"):
            held += abs(x.quantity or ZERO)
        elif x.kind in ("sell-to-open", "sell-to-close", "transfer-out"):
            held -= abs(x.quantity or ZERO)
    return held > 0


def _account_trades(s, a, led, positions) -> list[OptionTradeRow]:
    """An account's option trades. An adjustment (S3.10) is a pair of `option-adjust` rows, one
    taking the old contract's lots out and one putting them, times the ratio, in the new: it
    sells nothing, so the trade goes on under the adjusted contract (S3.10.4). Contracts moved
    in open or add to a trade as a buy does, and moved out take from it (S3.9.1)."""
    # Each of these names its instrument; a share's moves, with no contract, drop out below.
    txns = [t for t in led.transactions if t.kind in OPTION_KINDS + ENDS + MOVES]
    # In the order the lots take them: an adjustment's pair after the other trades of its day,
    # one typed later too (S3.10), the old contract's half before the new one's.
    txns.sort(
        key=lambda t: (t.date, t.kind == "option-adjust", t.createdAt, t.splitRatio is not None)
    )
    by_id = {t.id: t for t in txns}
    # Contracts an adjustment joins are one trade: an adjusted contract's trade is the one it
    # came from, and two adjusted onto one contract, or onto one already held, share theirs.
    joined: dict[str, frozenset[str]] = {}
    for t in txns:
        if t.kind == "option-adjust" and t.splitRatio is not None and t.transferId in by_id:
            old = by_id[t.transferId].instrumentId
            both = joined.get(old, frozenset({old})) | joined.get(
                t.instrumentId, frozenset({t.instrumentId})
            )
            for iid in both:
                joined[iid] = both
    contracts = {iid: options.contract_of(s, iid) for iid in {t.instrumentId for t in txns}}
    by_chain: dict[frozenset[str], list[Transaction]] = defaultdict(list)
    for t in txns:
        if contracts[t.instrumentId] is not None:
            by_chain[joined.get(t.instrumentId, frozenset({t.instrumentId}))].append(t)
    out: list[OptionTradeRow] = []
    for rows in by_chain.values():
        trade: dict | None = None
        net: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for t in rows:
            qty = abs(t.quantity or ZERO)
            moving_out = t.kind == "option-adjust" and t.splitRatio is None
            # Contracts moved in arrive long, as their lots open (S2.2).
            if t.kind in ("buy-to-open", "buy-to-close", "transfer-in"):
                step = qty
            elif t.kind in ("sell-to-open", "sell-to-close"):
                step = -qty
            elif t.kind == "option-adjust" and t.splitRatio is not None:
                # The adjusted contract takes over the old one's side (S3.10).
                step = qty if _adjusted_long(led, t) else -qty
            else:
                # An end, the old contract's lots leaving, or contracts moved out: toward none.
                step = -qty if net[t.instrumentId] > 0 else qty
            if trade is None:
                trade = {
                    "opened": t.date,
                    "side": "short" if step < 0 else "long",
                    "in": ZERO,
                    "out": ZERO,
                    "most": defaultdict(lambda: ZERO),
                    "first": t.instrumentId,
                }
            if t.amount > 0:
                trade["in"] += t.amount
            else:
                trade["out"] -= t.amount
            net[t.instrumentId] += step
            trade["most"][t.instrumentId] = max(
                trade["most"][t.instrumentId], abs(net[t.instrumentId])
            )
            # Both halves of an adjustment have its day.
            if t.kind == "option-adjust":
                trade["adjustedOn"] = t.date
            # The old contract's lots leaving end nothing: the new one takes them next.
            if not moving_out and not any(net.values()):
                out.append(_trade_row(a, s, contracts, trade, t, None))
                trade = None
        if trade is not None:
            # Open on every contract of it still held, named by the latest: worth them all.
            held = [i for i, n in net.items() if n]
            worth = [positions.get(i) for i in held]
            value = (
                sum((p.value for p in worth), ZERO)
                if all(p is not None and p.value is not None for p in worth)
                else None
            )
            out.append(_trade_row(a, s, contracts, trade, None, value, held[-1]))
    return out


def _trade_row(
    a, s, contracts, trade, last: Transaction | None, value, current: str | None = None
) -> OptionTradeRow:
    """A trade closed by `last`, or still open (`last` None) on `current` and worth `value`
    now. A short one requires the most its strike on its shares came to, before or after an
    adjustment."""
    iid = last.instrumentId if last is not None else current
    inst = s.get(Instrument, iid)
    pl = trade["in"] - trade["out"]
    if last is None:
        pl = pl + value if value is not None else None
    if trade["side"] == "long":
        risk = trade["out"]
    else:
        risk = max(
            (contracts[i].strike * contracts[i].multiplier * most).quantize(Decimal("0.01"))
            for i, most in trade["most"].items()
        )
    adjusted = trade["first"] != iid
    return OptionTradeRow(
        accountId=a.id,
        accountName=a.name,
        instrumentId=inst.id,
        symbol=inst.symbol,
        side=trade["side"],
        contracts=trade["most"][iid],
        opened=trade["opened"],
        closed=last.date if last else None,
        how=_how(last) if last else None,
        premiumIn=trade["in"],
        premiumOut=trade["out"],
        value=value,
        pl=pl,
        capitalRequired=risk,
        returnPct=(pl / risk * 100).quantize(PCT) if pl is not None and risk else None,
        adjustedFrom=s.get(Instrument, trade["first"]).symbol if adjusted else None,
        adjustedOn=trade.get("adjustedOn") if adjusted else None,
    )
