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
  opened. Another company's shares a contract delivers count at that company's price, or the
  figures are *not priced*. A calendar or diagonal shows its P/L only.
- **Capital at risk**: the max loss at expiry when it is finite, which is the net premium of
  long options and debit spreads, the widest wing less the credit of credit spreads and iron
  condors, the strike less the premium of a cash-secured put, and the shares' value less the
  premium of a covered call or collar. Undefined risk takes the margin requirement the owner
  types, or is *unlimited*. *Now* values shares at today's prices, *at open* at the opening
  day's; a calendar or diagonal risks its net debit.
"""

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from functools import cached_property
from itertools import pairwise

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
    # An adjusted contract's deliverable (S3.10.2): the underlying's shares and the cash a
    # contract delivers, when not the multiplier's shares alone.
    shares: Decimal | None = None
    cash: Decimal = ZERO
    # Another company's shares it delivers, each (instrument, shares), and what they are worth
    # at that company's price: None when one has no price.
    others: tuple[tuple[str, Decimal], ...] = ()
    other: Decimal | None = ZERO

    @property
    def option(self) -> bool:
        return self.kind != "stock"

    @property
    def per(self) -> Decimal:
        """The underlying's shares one contract (or share) moves with."""
        return Decimal(self.multiplier) if self.shares is None else self.shares

    @property
    def owed(self) -> Decimal:
        """What exercising one contract pays: the strike on the multiplier, less the cash and
        the other companies' shares it delivers, at their price."""
        return self.strike * self.multiplier - self.cash - self.other

    @property
    def at(self) -> Decimal:
        """The underlying's price at which it is at the money: what exercise pays over the
        shares delivered. One delivering none of the underlying has none (`per` is 0)."""
        return self.owed / self.per

    @property
    def open(self) -> bool:
        return self.quantity != 0

    @property
    def long(self) -> bool:
        """Bought, as an open leg is; one sold short is below zero."""
        return self.quantity > 0


def _worth(leg: Leg, price: Decimal) -> Decimal:
    """One contract (or share) at expiry if the underlying closes at this price: the shares it
    delivers at that price against what exercise pays, another company's shares in it counted
    at that company's price (S3.10.2)."""
    delivered = leg.per * price
    if leg.kind == "stock":
        return delivered
    if leg.kind == "call":
        return max(delivered - leg.owed, ZERO)
    return max(leg.owed - delivered, ZERO)


def payoff(legs: list[Leg], price: Decimal) -> Decimal:
    """The P/L at expiry if the underlying closes at this price."""
    return sum((x.quantity * _worth(x, price) - x.cost for x in legs if x.open), ZERO)


def shape(legs: list[Leg], cash_secured: bool = False) -> str:
    opts = [x for x in legs if x.open and x.option]
    stock = [x for x in legs if x.open and not x.option]
    if not opts:
        return "Shares" if stock else "Closed"
    sizes = {abs(x.quantity) for x in opts}
    if stock:
        if any(not x.long for x in stock) or len(sizes) != 1:
            return "Custom"
        calls = [x for x in opts if x.kind == "call"]
        puts = [x for x in opts if x.kind == "put"]
        if len(calls) == 1 and not puts and not calls[0].long:
            return "Covered call"
        if len(puts) == 1 and not calls and puts[0].long:
            return "Protective put"
        if len(calls) == 1 and len(puts) == 1 and not calls[0].long and puts[0].long:
            return "Collar"
        return "Custom"
    if len(opts) == 1:
        x = opts[0]
        if x.long:
            return f"Long {x.kind}"
        if x.kind == "put":
            return "Cash-secured put" if cash_secured else "Short put"
        return "Short call"
    expiries = {x.expiry for x in opts}
    if len(opts) == 2:
        a, b = sorted(opts, key=lambda x: (x.strike, x.kind))
        if len(expiries) == 2:
            if a.kind == b.kind and a.long != b.long and len(sizes) == 1:
                return "Calendar" if a.strike == b.strike else "Diagonal"
            return "Custom"
        if len(sizes) != 1:
            return "Custom"
        if a.kind == b.kind and a.long != b.long:
            if a.kind == "call":
                return "Bull call spread" if a.long else "Bear call spread"
            return "Bull put spread" if a.long else "Bear put spread"
        if a.kind != b.kind and a.long == b.long:
            side = "Long" if a.long else "Short"
            return f"{side} {'straddle' if a.strike == b.strike else 'strangle'}"
        return "Custom"
    if len(expiries) != 1:
        return "Custom"
    if len(opts) == 3 and len({x.kind for x in opts}) == 1:
        lo, mid, hi = sorted(opts, key=lambda x: x.strike)
        if (
            lo.long
            and lo.quantity == hi.quantity
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
            and puts[0].long
            and not puts[1].long
            and not calls[0].long
            and calls[1].long
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
    priced: bool = True  # false when another company's shares a contract delivers have no price


def figures(legs: list[Leg]) -> Figures:
    live = [x for x in legs if x.open]
    opts = [x for x in live if x.option]
    if not live:
        return Figures(ZERO, ZERO, [], True)
    if len({x.expiry for x in opts}) > 1:
        return Figures(None, None, [], False)
    if any(x.other is None for x in opts):
        # Another company's shares it delivers have no price: the payoff isn't known.
        return Figures(None, None, [], True, False)
    # The payoff at zero and at each strike; past the highest it is a line of this slope.
    strikes = sorted({x.at for x in opts if x.per})
    points = [(p, payoff(live, p)) for p in (ZERO, *strikes)]
    values = [v for _, v in points]
    slope = sum((x.quantity * x.per for x in live if x.kind in ("call", "stock")), ZERO)
    max_profit = None if slope > 0 else max(values)
    max_loss = None if slope < 0 else max(ZERO, -min(values))
    evens: list[Decimal] = []
    for (p0, v0), (p1, v1) in pairwise(points):
        if v0 == 0 and p0 > 0:
            evens.append(p0)
        elif (v0 < 0 < v1) or (v1 < 0 < v0):
            evens.append(p0 + (p1 - p0) * (-v0) / (v1 - v0))
    last, at_last = points[-1]
    if at_last == 0 and last > 0:
        evens.append(last)
    elif at_last * slope < 0:
        # The line past the highest strike crosses zero, however far out.
        evens.append(last - at_last / slope)
    return Figures(
        max_profit.quantize(CENT) if max_profit is not None else None,
        max_loss.quantize(CENT) if max_loss is not None else None,
        [e.quantize(CENT) for e in evens],
        True,
    )


def capital_at_risk(legs: list[Leg], margin: Decimal | None) -> Decimal | None:
    """What the strategy can lose: its finite max loss, else the margin typed, else none
    (*unlimited*). A calendar or diagonal risks its net debit, or the margin; one not priced,
    the margin."""
    f = figures(legs)
    if f.expiryKnown and f.priced and f.maxLoss is not None:
        return f.maxLoss
    debit = sum((x.cost for x in legs if x.open), ZERO)
    if not f.expiryKnown and debit > 0:
        return debit.quantize(CENT)
    return margin


# ---------- a strategy's legs, from its account's ledger ----------


def delivers(
    oc: OptionContract, same: set[str] | None = None
) -> tuple[Decimal | None, Decimal, tuple[tuple[str, Decimal], ...]]:
    """What one contract delivers (S3.10.2): its underlying's shares (None: the multiplier's,
    unadjusted), the cash, and each other company's shares. `same` is the instruments that are
    its underlying: itself, and the shares it became by a symbol change or a merger. A contract
    that delivers another company's shares too is covered by no holding of the underlying
    alone."""
    if not oc.deliverable:
        return None, ZERO, ()
    same = same or {oc.underlyingId}
    rows = json.loads(oc.deliverable)
    shares = sum((Decimal(str(x["shares"])) for x in rows if x["instrumentId"] in same), ZERO)
    others = tuple(
        (x["instrumentId"], Decimal(str(x["shares"])))
        for x in rows
        if x["instrumentId"] not in same
    )
    return shares, oc.deliverableCash or ZERO, others


@dataclass(frozen=True)
class LegRow:
    """A strategy's leg as it stands: on the contract its own was adjusted to, or the shares
    its own became, if they were; `stored` is then the leg as it was grouped."""

    instrumentId: str
    addedOn: dt.date
    quantity: Decimal | None
    stored: LegRow | None = None


def _follow(
    moved: dict[str, tuple[str, Decimal]], iid: str, qty: Decimal | None = None
) -> tuple[list[str], Decimal | None]:
    """The instruments one became in turn, itself first, and its quantity at the last: times
    each ratio. Moved back to one already passed, it stops there."""
    path, seen = [iid], set()
    while iid in moved and iid not in seen:
        seen.add(iid)
        iid, ratio = moved[iid]
        path.append(iid)
        qty = None if qty is None else qty * ratio
    return path, qty


def legs_of(s: Session, st: Strategy) -> list[LegRow]:
    """A strategy's legs as they are now: an option the OCC adjusted is followed to its
    adjusted contract, the contracts times the ratio (S3.10, CR3-401), and shares through a
    symbol change or a merger to the new shares, times its ratio. Nothing stored changes, so
    deleting the split or the action brings the leg back."""
    rows = list(
        s.scalars(
            select(StrategyLeg).where(
                StrategyLeg.strategyId == st.id, StrategyLeg.deleted == false()
            )
        )
    )
    moved = _adjusted(s, st.accountId)
    out = []
    for r in rows:
        path, qty = _follow(moved, r.instrumentId, r.quantity)
        stored = LegRow(r.instrumentId, r.addedOn, r.quantity)
        out.append(LegRow(path[-1], r.addedOn, qty, None if path[-1] == r.instrumentId else stored))
    return out


# What moves a leg to another instrument (S3.10): an option's adjustment, and a symbol change
# or a merger of shares. A spin-off leaves the shares held, and so in the strategy.
MOVES = ("option-adjust", "symbol-change", "merger")


def _adjusted(s: Session, account_id: str) -> dict[str, tuple[str, Decimal]]:
    """Each contract adjusted in the account, and each holding whose symbol changed or that
    merged: the instrument it became, and the ratio."""
    from ..store.entities.accounts import Transaction

    pairs = s.scalars(
        select(Transaction).where(
            Transaction.accountId == account_id,
            Transaction.kind.in_(MOVES),
            Transaction.splitRatio.is_not(None),
            Transaction.deleted == false(),
        )
    )
    out = {}
    for into in pairs:
        # A pair's halves are made and deleted together, the old instrument's named by the new
        # one's transferId; an adjustment typed by hand, an all-cash merger and a merger's old
        # half have no other.
        if into.transferId:
            old = s.get(Transaction, into.transferId)
            out[old.instrumentId] = (into.instrumentId, into.splitRatio)
    return out


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
        self.first: dict[str, dt.date] = {}  # the day its earliest open lot was acquired
        for lot in rp.open:
            iid = lot.instrumentId
            q, b = self.open.get(iid, (ZERO, ZERO))
            self.open[iid] = (q + lot.quantity, b + (lot.basis or ZERO))
            self.first[iid] = min(self.first.get(iid, lot.acquiredOn), lot.acquiredOn)
        self.disposals = rp.disposals
        # The last day anything happened to each instrument: a position at zero closed then,
        # by a sale, an expiry, an assignment or an exercise alike (S3.5.2). The ledger's
        # transactions come in date order, so the last one read is the last day.
        self.last: dict[str, dt.date] = {}
        for t in ledger.transactions:
            if t.instrumentId:
                self.last[t.instrumentId] = t.date
        self.marks = {p.instrumentId: p for p in valuation.positions(s, ledger)}
        self._prices: dict[tuple[str, dt.date], Decimal | None] = {}
        self._held: dict[dt.date, dict] = {}

    @cached_property
    def moved(self) -> dict[str, tuple[str, Decimal]]:
        """What each instrument moved to in the account, and the ratio (`legs_of`)."""
        return _adjusted(self.s, self.ledger.account.id)

    def held_on(self, day: dt.date) -> dict[str, tuple[Decimal, Decimal]]:
        """Each instrument's quantity and basis at the end of a day."""
        if day not in self._held:
            from ..ledger import holdingcheck

            self._held[day] = {
                k: (q, b or ZERO) for k, (q, b) in holdingcheck.held_on(self.ledger, day).items()
            }
        return self._held[day]

    def price(self, instrument_id: str, day: dt.date | None = None) -> Decimal | None:
        """Its price on a day, or today."""
        key = (instrument_id, day)
        if key not in self._prices:
            owner = self.ledger.account.ownerId
            p = valuation.prices(self.s, [instrument_id], day, owner=owner).get(instrument_id)
            self._prices[key] = p.price if p else None
        return self._prices[key]

    def worth(self, others, day: dt.date | None = None) -> Decimal | None:
        """Other companies' shares, each (instrument, shares), at their prices on a day, or
        today's; None when one has none."""
        total = ZERO
        for iid, shares in others:
            p = self.price(iid, day)
            if p is None:
                return None
            total += p * shares
        return total


def leg(book: Book, row: LegRow, opened: dt.date, held: dict | None = None) -> Leg:
    """A leg now, or, given `held` (the positions at the end of a day), as it was then; its
    value is today's."""
    s = book.s
    inst = s.get(Instrument, row.instrumentId)
    qty, basis = (held if held is not None else book.open).get(row.instrumentId, (ZERO, ZERO))
    closes = [
        d for d in book.disposals if d.instrumentId == row.instrumentId and d.soldOn >= opened
    ]
    realized = sum((d.gain or ZERO for d in closes), ZERO)
    closed_on = max(book.last.get(row.instrumentId, opened), opened) if qty == 0 else None
    oc = contract_of(s, row.instrumentId)
    if oc is None:
        # Shares: the leg's part of the position, valued at the opening day's price.
        held = qty if row.quantity is None else min(qty, row.quantity)
        at_open = book.price(row.instrumentId, opened)
        now = book.price(row.instrumentId)
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
    # What it delivers of the underlying: its shares, or those they became (S3.10).
    per, cash, others = delivers(oc, set(_follow(book.moved, oc.underlyingId)[0]))
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
        per,
        cash,
        others,
        book.worth(others),
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


def at_prices(book: Book, legs: list[Leg], day: dt.date | None = None) -> list[Leg]:
    """The legs with their shares valued at a day's price, or today's, for capital at risk
    then, and the other companies' shares a contract delivers at theirs."""
    out = []
    for x in legs:
        if x.kind == "stock" and x.quantity:
            p = book.price(x.instrumentId, day)
            if p is not None:
                x = Leg(**{**x.__dict__, "cost": (p * x.quantity).quantize(CENT)})
        elif x.others:
            x = Leg(**{**x.__dict__, "other": book.worth(x.others, day)})
        out.append(x)
    return out


def named(st: Strategy, kind: str) -> str:
    """A strategy as it is shown: its name, or its shape when it has none (S3.5.4)."""
    return st.name or kind


def shape_of(book: Book, st: Strategy) -> str:
    """A strategy's shape, from its legs now."""
    return shape([leg(book, r, st.openedOn) for r in legs_of(book.s, st)], st.cashSecured)


def view(book: Book, st: Strategy) -> View:
    s = book.s
    rows = legs_of(s, st)
    legs = [leg(book, r, st.openedOn) for r in rows]
    live = [x for x in legs if x.open]
    unrealized = (
        None if any(x.value is None for x in live) else sum((x.value - x.cost for x in live), ZERO)
    )
    # At open: the legs it opened with, as they were at the end of that day (S3.5.5), on the
    # instruments they were then.
    held = book.held_on(st.openedOn)
    at_open = [
        leg(book, r.stored or r, st.openedOn, held) for r in rows if r.addedOn <= st.openedOn
    ]
    kind = shape(legs, st.cashSecured)
    # Open while an option leg is; closed on the day its last leg closed, as every leg not
    # open has (it holds an option leg, S3.5.2).
    closed = None if any(x.option for x in live) else max(x.closedOn for x in legs if x.closedOn)
    return View(
        st,
        named(st, kind),
        kind,
        # The underlying, or the shares it became (S3.10).
        s.get(Instrument, _follow(book.moved, st.underlyingId)[0][-1]).symbol,
        legs,
        -sum((x.cost for x in live if x.option), ZERO),
        unrealized,
        sum((x.realized for x in legs), ZERO),
        figures(legs),
        None if closed else capital_at_risk(at_prices(book, legs), st.marginRequirement),
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
                            named(st, shape_of(book, st)),  # CR3-408
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
                shape([leg(book, LegRow(i, today, None), today) for i in iids]),
            )
        )
    # A short call against 100 or more shares held, whenever they were bought.
    taken = {i for p in out for i, _ in p.legs}
    for iid, oc in contracts.items():
        if iid in taken or oc.right != "call":
            continue
        qty, _ = book.open[iid]
        shares, _ = book.open.get(oc.underlyingId, (ZERO, ZERO))
        per, _, others = delivers(oc)
        # What it delivers (CR3-400); a long call's is below zero, so never 100.
        need = -qty * (oc.multiplier if per is None else per)
        if oc.underlyingId in grouped or others or shares < need or need < 100:
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
    strategy's, and each option outside one as a strategy of its own shape (S3.5.6); then
    whether anything is open at all. The risk is None, *unlimited*, when any is."""
    book = book or Book(s, ledger)
    value = ZERO
    risk: Decimal | None = ZERO
    any_open = False
    in_strategies: set[str] = set()
    for st in of_account(s, ledger.account.id):
        v = view(book, st)
        in_strategies |= {x.instrumentId for x in v.legs}
        if v.closedOn is None:
            risk = None if risk is None or v.riskNow is None else risk + v.riskNow
    # An option outside a strategy counts as a strategy of its own shape, through the same
    # payoff (S3.5.6, CR3-6): a long one risks its premium, a short put its strike less its
    # premium, a short call the account's shares cover is a covered call, an uncovered one has
    # no limit. Shares go to the calls in turn, and only shares no strategy holds (a long
    # option among them is never a call's underlying).
    spare = {iid: q for iid, (q, _) in book.open.items() if q > 0 and iid not in in_strategies}
    for iid, (qty, basis) in sorted(book.open.items()):
        oc = contract_of(s, iid)
        if oc is None or not qty:
            continue
        any_open = True
        mark = book.marks.get(iid)
        if mark is not None and mark.value is not None:
            value += mark.value
        if iid in in_strategies or risk is None:
            continue
        per, cash, others = delivers(oc)
        # What the payoff reads, and no more: one leg has one expiry, and no mark counts. By the
        # table, another company's shares in it count at nothing: a short put risks what
        # exercise pays, a long call its premium, a short call is unlimited below.
        legs = [Leg(iid, "", oc.right, qty, basis, None, oc.strike, multiplier=oc.multiplier,
                    shares=per, cash=cash)]  # fmt: skip
        if oc.right == "call" and qty < 0:
            if others:
                # It delivers another company's shares too, which the underlying's don't cover.
                risk = None
                continue
            if spare.get(oc.underlyingId):
                # Shares cover what the contract delivers, not its multiplier (CR3-400).
                covered = min(spare[oc.underlyingId], -qty * legs[0].per)
                spare[oc.underlyingId] -= covered
                price = book.price(oc.underlyingId)
                cost = (price * covered).quantize(CENT) if price is not None else ZERO
                legs.append(Leg(oc.underlyingId, "", "stock", covered, cost, None))
        one = capital_at_risk(legs, None)
        risk = None if one is None else risk + one
    return value, risk, any_open
