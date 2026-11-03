"""Strategies (requirements S3.5): legs held together and shown as one. Grouping is a label:
each leg keeps its own lots, gains and wash sales.

- **Proposed, never forced**: legs on one underlying opened in one account on one day, and a
  short call against 100 or more shares held, are offered as a strategy; a proposal turned
  down isn't offered again. A leg closed and another opened on the same underlying the same
  day is offered to stay in its strategy (a roll).
- **Shapes**: from the open legs' rights, strikes, expiries and sides; anything else is
  *Custom*.
- **Figures at expiry**: worked out from the payoff at every strike, at zero and beyond the
  highest strike, so any shape gets its max profit, max loss and breakevens, *unlimited* where
  the payoff keeps rising or falling. Shares count at their value on the day the strategy
  opened. A calendar or diagonal shows its P/L only.
- **Capital at risk**: the max loss at expiry when it is finite, which is the net premium of
  long options and debit spreads, the widest wing less the credit of credit spreads and iron
  condors, the strike less the premium of a cash-secured put, and the shares' value less the
  premium of a covered call or collar. Undefined risk takes the margin requirement the owner
  types, or is *unlimited*. *Now* values shares at today's prices, *at open* at the opening
  day's; a calendar or diagonal risks its net debit.
"""

import datetime as dt
import hashlib
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from .. import clock, valuation
from ..store.entities.accounts import Instrument, OptionContract, Strategy, StrategyLeg
from . import contract_of

ZERO = Decimal(0)
CENT = Decimal("0.01")


@dataclass
class Leg:
    instrumentId: str
    symbol: str
    kind: str  # call, put or stock
    quantity: Decimal  # contracts or shares, short below zero; 0 once closed
    cost: Decimal  # paid for what is open (a credit is below zero); for shares, at open
    value: Decimal | None  # its mark now
    strike: Decimal | None = None
    expiry: dt.date | None = None
    multiplier: int = 1
    realized: Decimal = ZERO  # closed since the strategy opened
    addedOn: dt.date | None = None
    closedOn: dt.date | None = None

    @property
    def option(self) -> bool:
        return self.kind != "stock"

    @property
    def open(self) -> bool:
        return self.quantity != 0


def _intrinsic(leg: Leg, price: Decimal) -> Decimal:
    if leg.kind == "stock":
        return price
    if leg.kind == "call":
        return max(price - leg.strike, ZERO)
    return max(leg.strike - price, ZERO)


def payoff(legs: list[Leg], price: Decimal) -> Decimal:
    """The P/L at expiry if the underlying closes at this price."""
    return sum(
        (x.quantity * x.multiplier * _intrinsic(x, price) - x.cost for x in legs if x.open), ZERO
    )


def shape(legs: list[Leg], cash_secured: bool = False) -> str:
    opts = [x for x in legs if x.open and x.option]
    stock = [x for x in legs if x.open and not x.option]
    if not opts:
        return "Shares" if stock else "Closed"
    sizes = {abs(x.quantity) for x in opts}
    if stock:
        if any(x.quantity < 0 for x in stock) or len(sizes) != 1:
            return "Custom"
        calls = [x for x in opts if x.kind == "call"]
        puts = [x for x in opts if x.kind == "put"]
        if len(calls) == 1 and not puts and calls[0].quantity < 0:
            return "Covered call"
        if len(puts) == 1 and not calls and puts[0].quantity > 0:
            return "Protective put"
        if len(calls) == 1 and len(puts) == 1 and calls[0].quantity < 0 and puts[0].quantity > 0:
            return "Collar"
        return "Custom"
    if len(opts) == 1:
        x = opts[0]
        if x.quantity > 0:
            return f"Long {x.kind}"
        if x.kind == "put":
            return "Cash-secured put" if cash_secured else "Short put"
        return "Short call"
    expiries = {x.expiry for x in opts}
    if len(opts) == 2:
        a, b = sorted(opts, key=lambda x: (x.strike, x.kind))
        if len(expiries) == 2:
            if a.kind == b.kind and (a.quantity > 0) != (b.quantity > 0) and len(sizes) == 1:
                return "Calendar" if a.strike == b.strike else "Diagonal"
            return "Custom"
        if len(sizes) != 1:
            return "Custom"
        if a.kind == b.kind and (a.quantity > 0) != (b.quantity > 0):
            low_long = a.quantity > 0
            if a.kind == "call":
                return "Bull call spread" if low_long else "Bear call spread"
            return "Bull put spread" if low_long else "Bear put spread"
        if a.kind != b.kind and (a.quantity > 0) == (b.quantity > 0):
            side = "Long" if a.quantity > 0 else "Short"
            return f"{side} {'straddle' if a.strike == b.strike else 'strangle'}"
        return "Custom"
    if len(expiries) != 1:
        return "Custom"
    if len(opts) == 3 and len({x.kind for x in opts}) == 1:
        lo, mid, hi = sorted(opts, key=lambda x: x.strike)
        if (
            lo.quantity == hi.quantity > 0
            and mid.quantity == -2 * lo.quantity
            and mid.strike - lo.strike == hi.strike - mid.strike
        ):
            return "Butterfly"
        return "Custom"
    if len(opts) == 4 and len(sizes) == 1:
        puts = sorted((x for x in opts if x.kind == "put"), key=lambda x: x.strike)
        calls = sorted((x for x in opts if x.kind == "call"), key=lambda x: x.strike)
        if (
            len(puts) == 2
            and len(calls) == 2
            and puts[0].quantity > 0 > puts[1].quantity
            and calls[0].quantity < 0 < calls[1].quantity
        ):
            if puts[1].strike == calls[0].strike:
                return "Iron butterfly"
            if puts[1].strike < calls[0].strike:
                return "Iron condor"
    return "Custom"


@dataclass
class Figures:
    maxProfit: Decimal | None  # None: unlimited
    maxLoss: Decimal | None  # None: unlimited
    breakevens: list[Decimal]
    expiryKnown: bool  # false for a calendar or diagonal


def figures(legs: list[Leg]) -> Figures:
    live = [x for x in legs if x.open]
    opts = [x for x in live if x.option]
    if not live:
        return Figures(ZERO, ZERO, [], True)
    if len({x.expiry for x in opts}) > 1:
        return Figures(None, None, [], False)
    strikes = sorted({x.strike for x in opts})
    top = (strikes[-1] if strikes else ZERO) * 2 + 1
    points = [ZERO, *strikes, top]
    values = [payoff(live, p) for p in points]
    slope = sum((x.quantity * x.multiplier for x in live if x.kind in ("call", "stock")), ZERO)
    max_profit = None if slope > 0 else max(values)
    max_loss = None if slope < 0 else max(ZERO, -min(values))
    evens: list[Decimal] = []
    for (p0, v0), (p1, v1) in zip(
        zip(points, values, strict=True), zip(points[1:], values[1:], strict=True), strict=False
    ):
        if v0 == 0 and p0 not in evens and p0 > 0:
            evens.append(p0)
        elif (v0 < 0 < v1) or (v1 < 0 < v0):
            evens.append(p0 + (p1 - p0) * (-v0) / (v1 - v0))
    if values[-1] == 0 and top not in evens:
        evens.append(top)
    return Figures(
        max_profit.quantize(CENT) if max_profit is not None else None,
        max_loss.quantize(CENT) if max_loss is not None else None,
        [e.quantize(CENT) for e in evens],
        True,
    )


def capital_at_risk(legs: list[Leg], margin: Decimal | None) -> Decimal | None:
    """What the strategy can lose: its finite max loss, else the margin typed, else none
    (*unlimited*). A calendar or diagonal risks its net debit, or the margin."""
    f = figures(legs)
    if f.expiryKnown and f.maxLoss is not None:
        return f.maxLoss
    debit = sum((x.cost for x in legs if x.open), ZERO)
    if not f.expiryKnown and debit > 0:
        return debit.quantize(CENT)
    return margin


# ---------- a strategy's legs, from its account's ledger ----------


def legs_of(s: Session, st: Strategy) -> list[StrategyLeg]:
    return list(
        s.scalars(
            select(StrategyLeg).where(
                StrategyLeg.strategyId == st.id, StrategyLeg.deleted == false()
            )
        )
    )


def of_account(s: Session, account_id: str, dismissed: bool = False) -> list[Strategy]:
    return list(
        s.scalars(
            select(Strategy)
            .where(
                Strategy.accountId == account_id,
                Strategy.deleted == false(),
                Strategy.dismissed == dismissed,
            )
            .order_by(Strategy.openedOn, Strategy.createdAt)
        )
    )


class Book:
    """An account's positions, as the strategies in it need them: open quantity and basis
    per instrument, the closes, today's marks, and prices on other days."""

    def __init__(self, s: Session, ledger):
        self.s = s
        self.ledger = ledger
        rp = ledger.replay()
        self.open: dict[str, tuple[Decimal, Decimal]] = {}
        for lot in rp.open:
            q, b = self.open.get(lot.instrumentId, (ZERO, ZERO))
            self.open[lot.instrumentId] = (q + lot.quantity, b + (lot.basis or ZERO))
        self.first: dict[str, dt.date] = {}
        for lot in rp.open:
            d = self.first.get(lot.instrumentId)
            self.first[lot.instrumentId] = min(d, lot.acquiredOn) if d else lot.acquiredOn
        self.disposals = rp.disposals
        # The last day anything happened to each instrument: a position at zero closed then,
        # by a sale, an expiry, an assignment or an exercise alike (S3.5.2).
        self.last: dict[str, dt.date] = {}
        for t in ledger.transactions:
            if t.instrumentId and (
                t.instrumentId not in self.last or t.date > self.last[t.instrumentId]
            ):
                self.last[t.instrumentId] = t.date
        self.marks = {p.instrumentId: p for p in valuation.positions(s, ledger)}
        self._prices: dict[tuple[str, dt.date], Decimal | None] = {}
        self._held: dict[dt.date, dict] = {}

    def held_on(self, day: dt.date) -> dict[str, tuple[Decimal, Decimal]]:
        """Each instrument's quantity and basis at the end of a day."""
        if day not in self._held:
            from ..ledger import holdingcheck

            self._held[day] = {
                k: (q, b or ZERO) for k, (q, b) in holdingcheck.held_on(self.ledger, day).items()
            }
        return self._held[day]

    def price(self, instrument_id: str, day: dt.date) -> Decimal | None:
        key = (instrument_id, day)
        if key not in self._prices:
            owner = self.ledger.account.ownerId
            p = valuation.prices(self.s, [instrument_id], day, owner=owner).get(instrument_id)
            self._prices[key] = p.price if p else None
        return self._prices[key]


def leg(
    book: Book, row: StrategyLeg, opened: dt.date, today: dt.date, held: dict | None = None
) -> Leg | None:
    """A leg now, or, given `held` (the positions at the end of a day), as it was then."""
    s = book.s
    inst = s.get(Instrument, row.instrumentId)
    if inst is None:
        return None
    qty, basis = (held if held is not None else book.open).get(row.instrumentId, (ZERO, ZERO))
    closes = [
        d for d in book.disposals if d.instrumentId == row.instrumentId and d.soldOn >= opened
    ]
    realized = sum((d.gain or ZERO for d in closes), ZERO)
    closed_on = max(book.last.get(row.instrumentId, opened), opened) if qty == 0 else None
    oc = contract_of(s, row.instrumentId) if inst.instrumentClass == "option" else None
    if oc is None:
        # Shares: the leg's part of the position, valued at the opening day's price.
        held = qty if row.quantity is None else min(qty, row.quantity)
        at_open = book.price(row.instrumentId, opened)
        now = book.price(row.instrumentId, today)
        per = at_open if at_open is not None else (basis / qty if qty else ZERO)
        return Leg(
            row.instrumentId,
            inst.symbol,
            "stock",
            held,
            (per * held).quantize(CENT),
            (now * held).quantize(CENT) if now is not None else None,
            addedOn=row.addedOn,
        )
    mark = book.marks.get(row.instrumentId)
    return Leg(
        row.instrumentId,
        inst.symbol,
        oc.right,
        qty,
        basis,
        mark.value if mark is not None else None,
        oc.strike,
        oc.expiry,
        oc.multiplier,
        realized,
        row.addedOn,
        closed_on,
    )


@dataclass
class View:
    strategy: Strategy
    name: str
    shape: str
    underlying: str
    legs: list[Leg]
    credit: Decimal  # the net option premium received; a debit below zero
    unrealized: Decimal | None
    realized: Decimal
    figures: Figures
    riskNow: Decimal | None
    riskAtOpen: Decimal | None
    closedOn: dt.date | None

    @property
    def pl(self) -> Decimal | None:
        return None if self.unrealized is None else self.unrealized + self.realized


def at_prices(book: Book, legs: list[Leg], day: dt.date) -> list[Leg]:
    """The legs with their shares valued at a day's price, for capital at risk then."""
    out = []
    for x in legs:
        if x.kind == "stock" and x.quantity:
            p = book.price(x.instrumentId, day)
            if p is not None:
                x = Leg(**{**x.__dict__, "cost": (p * x.quantity).quantize(CENT)})
        out.append(x)
    return out


def view(book: Book, st: Strategy, today: dt.date | None = None) -> View:
    s = book.s
    today = today or clock.today()
    legs = [x for x in (leg(book, r, st.openedOn, today) for r in legs_of(s, st)) if x is not None]
    live = [x for x in legs if x.open]
    known = [x.value for x in live]
    unrealized = (
        sum((v - x.cost for v, x in zip(known, live, strict=True)), ZERO)
        if all(v is not None for v in known)
        else None
    )
    # At open: the legs it opened with, as they were at the end of that day (S3.5.5).
    held = book.held_on(st.openedOn)
    at_open = [
        x
        for x in (
            leg(book, r, st.openedOn, st.openedOn, held)
            for r in legs_of(s, st)
            if r.addedOn <= st.openedOn
        )
        if x is not None
    ]
    kind = shape(legs, st.cashSecured)
    under = s.get(Instrument, st.underlyingId)
    closed = (
        None
        if live and any(x.option for x in live)
        else max((x.closedOn for x in legs if x.closedOn), default=None)
    )
    return View(
        st,
        st.name or kind,
        kind,
        under.symbol if under else "?",
        legs,
        -sum((x.cost for x in live if x.option), ZERO),
        unrealized,
        sum((x.realized for x in legs), ZERO),
        figures(legs),
        None if closed else capital_at_risk(at_prices(book, legs, today), st.marginRequirement),
        capital_at_risk(at_prices(book, at_open, st.openedOn), st.marginRequirement),
        closed,
    )


# ---------- proposals (S3.5.1, S3.5.2) ----------


@dataclass
class Proposal:
    key: str
    kind: str  # group, covered-call, roll
    accountId: str
    underlyingId: str
    openedOn: dt.date
    legs: list[tuple[str, Decimal | None]]  # instrument, and shares for a stock leg
    shape: str
    strategyId: str | None = None  # a roll's
    symbols: list[str] = field(default_factory=list)


def proposal_key(account_id: str, legs: list[str]) -> str:
    return hashlib.sha256(("|".join([account_id, *sorted(legs)])).encode()).hexdigest()[:16]


def proposals(s: Session, account, book: Book) -> list[Proposal]:
    grouped: set[str] = set()
    live = of_account(s, account.id)
    for st in live:
        grouped |= {r.instrumentId for r in legs_of(s, st)}
    declined = {
        proposal_key(account.id, [r.instrumentId for r in legs_of(s, st)])
        for st in of_account(s, account.id, dismissed=True)
    }
    contracts: dict[str, OptionContract] = {}
    for iid, (qty, _) in book.open.items():
        if qty and iid not in grouped:
            oc = contract_of(s, iid)
            if oc is not None:
                contracts[iid] = oc
    out: list[Proposal] = []
    today = clock.today()

    def legs_for(iids, extra=None) -> list[Leg]:
        rows = [
            StrategyLeg(strategyId="", instrumentId=i, addedOn=today, createdAt=clock.now())
            for i in iids
        ]
        if extra:
            rows.append(
                StrategyLeg(
                    strategyId="",
                    instrumentId=extra[0],
                    quantity=extra[1],
                    addedOn=today,
                    createdAt=clock.now(),
                )
            )
        return [x for x in (leg(book, r, today, today) for r in rows) if x is not None]

    # Rolls: a leg closed, and another opened on the same underlying that day.
    rolled: set[str] = set()
    for st in live:
        mine = legs_of(s, st)
        for r in mine:
            qty, _ = book.open.get(r.instrumentId, (ZERO, ZERO))
            if qty:
                continue
            closes = [d.soldOn for d in book.disposals if d.instrumentId == r.instrumentId]
            if not closes:
                continue
            day = max(closes)
            for iid, oc in contracts.items():
                if oc.underlyingId == st.underlyingId and book.first.get(iid) == day:
                    key = proposal_key(account.id, [iid])
                    if key in declined or iid in rolled:
                        continue
                    rolled.add(iid)
                    out.append(
                        Proposal(
                            key,
                            "roll",
                            account.id,
                            st.underlyingId,
                            day,
                            [(iid, None)],
                            st.name or "",
                            st.id,
                        )
                    )
    # Legs on one underlying opened the same day.
    by: dict[tuple[str, dt.date], list[str]] = {}
    for iid, oc in contracts.items():
        if iid in rolled:
            continue
        by.setdefault((oc.underlyingId, book.first[iid]), []).append(iid)
    for (under, day), iids in by.items():
        if len(iids) < 2:
            continue
        key = proposal_key(account.id, iids)
        if key in declined:
            continue
        out.append(
            Proposal(
                key,
                "group",
                account.id,
                under,
                day,
                [(i, None) for i in sorted(iids)],
                shape(legs_for(iids)),
            )
        )
    # A short call against 100 or more shares held, whenever they were bought.
    taken = {i for p in out for i, _ in p.legs}
    for iid, oc in contracts.items():
        qty, _ = book.open[iid]
        if iid in taken or oc.right != "call" or qty >= 0:
            continue
        shares, _ = book.open.get(oc.underlyingId, (ZERO, ZERO))
        need = -qty * oc.multiplier
        if oc.underlyingId in grouped or shares < need or need < 100:
            continue
        key = proposal_key(account.id, [iid, oc.underlyingId])
        if key in declined:
            continue
        out.append(
            Proposal(
                key,
                "covered-call",
                account.id,
                oc.underlyingId,
                book.first[iid],
                [(oc.underlyingId, need), (iid, None)],
                "Covered call",
            )
        )
    for p in out:
        p.symbols = [s.get(Instrument, i).symbol for i, _ in p.legs]
    return out


def risk_of_account(
    s: Session, ledger, book: Book | None = None
) -> tuple[Decimal, Decimal | None, bool]:
    """An investing account's options' market value, and their capital at risk now: each
    strategy's, and each option outside one as a single leg (S3.9.2); then whether anything
    is open at all. The risk is None, *unlimited*, when an open strategy's is."""
    book = book or Book(s, ledger)
    value = ZERO
    risk: Decimal | None = ZERO
    any_open = False
    in_strategies: set[str] = set()
    for st in of_account(s, ledger.account.id):
        v = view(book, st)
        in_strategies |= {x.instrumentId for x in v.legs}
        if v.closedOn is None and any(x.open and x.option for x in v.legs):
            any_open = True
            risk = None if risk is None or v.riskNow is None else risk + v.riskNow
    for iid, (qty, basis) in book.open.items():
        oc = contract_of(s, iid)
        if oc is None or not qty:
            continue
        any_open = True
        mark = book.marks.get(iid)
        if mark is not None and mark.value is not None:
            value += mark.value
        if iid in in_strategies or risk is None:
            continue
        risk += basis if qty > 0 else (oc.strike * oc.multiplier * -qty).quantize(CENT)
    return value, risk, any_open
