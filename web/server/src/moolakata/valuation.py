"""What holdings are worth (requirements S4.6, S4.7): every value derived from a price carries
the price's source and `as_of`. Charts and screens read stored prices only, never a price
source during a request.

Prices come, in order, from: the stored daily closes (S4), or a later price the account's
owner typed (S4.10); a value a broker's file reported for the holding; and the owner's last
trade in it. Another user's typed prices, statements and trades never value an account.
"""

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from . import clock
from .ledger import balances
from .money import CENT
from .store.entities.accounts import Account, Holding, Instrument, Transaction
from .store.entities.prices import TypedPrice

ZERO = Decimal(0)
TYPED_STALE_DAYS = 90  # a typed price, as a statement's value (S4.7)


@dataclass(frozen=True)
class Price:
    price: Decimal
    asOf: dt.date
    source: str  # "close" from a price source, "statement", "trade", "fixed"
    stale: bool = False


# Stored closes, installed by prices/refresh.py: the latest on a day, and a range of them.
CloseLookup = Callable[[Session, list[str], dt.date], dict[str, Price]]
CloseHistory = Callable[
    [Session, list[str], dt.date, dt.date], dict[str, list[tuple[dt.date, Decimal]]]
]
_closes: list[CloseLookup] = []
_history: list[CloseHistory] = []


def use_closes(lookup: CloseLookup, history: CloseHistory | None = None) -> None:
    _closes[:] = [lookup]
    _history[:] = [history] if history else []


def _owned(stmt, entity, owner: str):
    """Only what the owner's own accounts hold: another user's files and trades never value
    theirs (S4.10)."""
    return stmt.join(Account, Account.id == entity.accountId).where(Account.ownerId == owner)


def typed(s: Session, owner: str, instrument_ids: list[str], first: dt.date | None, last: dt.date):
    """The prices the owner typed for these instruments, oldest first: those after `first`
    up to `last`, or with `first` None, every one up to `last`."""
    q = select(TypedPrice).where(
        TypedPrice.userId == owner,
        TypedPrice.instrumentId.in_(instrument_ids),
        TypedPrice.deleted == false(),
        TypedPrice.date <= last,
    )
    if first is not None:
        q = q.where(TypedPrice.date > first)
    return list(s.scalars(q.order_by(TypedPrice.date)))


# The order of a price's sources (S4, S4.10): a stored close, or a later price the owner
# typed; failing those, a value the owner's own statement reported; failing that, the owner's
# last trade. Worked out once, over a range of days (`_effective`): a day's price (`prices`)
# is the last point of the range ending that day (`price_points`), so a figure for one day and
# a chart's agree (13.1). Another user's typed prices, statements and trades never count.
_RANK = {"fixed": 0, "close": 0, "manual": 1, "statement": 2, "trade": 3}


def _tiers(
    s: Session, ids: list[str], first: dt.date, last: dt.date, owner: str
) -> dict[str, list[list[Price]]]:
    """Each instrument's points up to `last` (and the last before `first`), oldest first, in
    three tiers: closes and the owner's typed prices; the owner's statement values; the
    owner's trades."""
    out = {i: [[], [], []] for i in ids}
    if not ids:
        return out
    insts = {i.id: i for i in s.scalars(select(Instrument).where(Instrument.id.in_(ids)))}
    fixed = {iid for iid, inst in insts.items() if inst.instrumentClass in ("cash", "money-market")}
    for iid in fixed:
        out[iid][0].append(Price(Decimal(1), dt.date.min, "fixed"))
    rest = [i for i in ids if i not in fixed]
    if _closes:
        for iid, p in _closes[0](s, rest, first).items():
            out[iid][0].append(p)
    if _history and last > first:
        for iid, rows in _history[0](s, rest, first, last).items():
            out[iid][0] += [Price(v, d, "close") for d, v in rows]
    today = clock.today()
    for t in typed(s, owner, rest, None, last):
        stale = (min(last, today) - t.date).days > TYPED_STALE_DAYS
        out[t.instrumentId][0].append(Price(t.close, t.date, "manual", stale))
    # Statements and trades count only before an instrument's first close or typed price.
    loose = [i for i in rest if not any(p.asOf <= first for p in out[i][0])]
    if loose:
        for h in s.scalars(
            _owned(select(Holding), Holding, owner).where(
                Holding.instrumentId.in_(loose),
                Holding.deleted == false(),
                Holding.asOf <= last,
                Holding.marketValue.is_not(None),
            )
        ):
            if h.quantity:
                worth = h.marketValue / h.quantity
                out[h.instrumentId][1].append(Price(worth, h.asOf, "statement"))
        # An option's last trade isn't its mark: intrinsic value stands in instead (S3.7).
        mult = multipliers(s, loose)
        traded = [i for i in loose if i not in mult]
        if traded:
            for txn in s.scalars(
                _owned(select(Transaction), Transaction, owner).where(
                    Transaction.instrumentId.in_(traded),
                    Transaction.deleted == false(),
                    Transaction.price.is_not(None),
                    Transaction.date <= last,
                )
            ):
                out[txn.instrumentId][2].append(Price(txn.price, txn.date, "trade"))
    for tiers in out.values():
        for tier in tiers:
            # A typed price stands on its day, after the close of that day (S4.10).
            tier.sort(key=lambda p: (p.asOf, _RANK[p.source]))
    return out


def _effective(tiers: list[list[Price]], day: dt.date) -> Price | None:
    """The price on a day: the latest point of the first tier with one by then."""
    for tier in tiers:
        found = None
        for p in tier:
            if p.asOf > day:
                break
            found = p
        if found is not None:
            return found if found.source != "fixed" else Price(found.price, day, "fixed")
    return None


def prices(
    s: Session, instrument_ids: list[str], day: dt.date | None = None, *, owner: str
) -> dict[str, Price]:
    """The latest price on or before the day for each instrument, for the accounts of
    `owner`: the last point of `price_points` up to that day."""
    day = day or clock.today()
    ids_ = list(dict.fromkeys(instrument_ids))
    out = {}
    for iid, tiers in _tiers(s, ids_, day, day, owner).items():
        p = _effective(tiers, day)
        if p is not None:
            out[iid] = p
    return out


def closes(s: Session, instrument_ids: list[str], day: dt.date) -> dict[str, Price]:
    """The market's stored closes alone, the latest on or before the day: what a decision
    resting on the market reads (an expiry, S3.6), and what reads for no one in particular. No
    typed price, statement or trade, anyone's, counts."""
    if not instrument_ids or not _closes:
        return {}
    return {
        iid: p
        for iid, p in _closes[0](s, list(dict.fromkeys(instrument_ids)), day).items()
        if p.source == "close"
    }


@dataclass
class Position:
    instrumentId: str
    quantity: Decimal
    costBasis: Decimal | None
    price: Price | None
    multiplier: int = 1  # an option contract's shares (S3.2)

    @property
    def value(self) -> Decimal | None:
        if self.price is None:
            return None
        return (self.quantity * self.price.price * self.multiplier).quantize(CENT)

    @property
    def gain(self) -> Decimal | None:
        if self.value is None or self.costBasis is None:
            return None
        return self.value - self.costBasis


def positions(s: Session, ledger, day: dt.date | None = None) -> list[Position]:
    """An investing account's holdings on a day (today when none), from its lots replayed to
    that day, valued at that day's prices."""
    replay = ledger.replay(day)
    by: dict[str, list] = {}
    for lot in replay.open:
        by.setdefault(lot.instrumentId, []).append(lot)
    found = prices(s, list(by), day, owner=ledger.account.ownerId)
    mult = multipliers(s, list(by))
    for iid in by:
        if iid in mult and iid not in found:
            mark = intrinsic(s, iid, day, ledger.account.ownerId)
            if mark is not None:
                found[iid] = mark
    out = []
    for iid, open_lots in by.items():
        # A lot's quantity is a Decimal and open_lots is never empty: no start changes the sum.
        qty = sum((x.quantity for x in open_lots), ZERO)  # pragma: no mutate
        basis = (
            None
            if any(x.basis is None for x in open_lots)
            else sum((x.basis for x in open_lots), ZERO)
        )
        out.append(Position(iid, qty, basis, found.get(iid), mult.get(iid, 1)))
    return out


def intrinsic(s: Session, instrument_id: str, day: dt.date | None, owner: str) -> Price | None:
    """An option's value at the underlying's close, when no close or typed mark is known:
    what exercising it would be worth, labelled as such (S3.7)."""
    from . import options

    c = options.contract_of(s, instrument_id)
    if c is None:
        return None
    under = options.per_share(s, c, day, owner)
    if under is None:
        return None
    price, asof = under
    worth = price - c.strike if c.right == "call" else c.strike - price
    return Price(max(worth, ZERO), asof, "intrinsic")


def multipliers(s: Session, instrument_ids: list[str]) -> dict[str, int]:
    """Option contracts' shares per contract; anything else counts one."""
    from .store.entities.accounts import OptionContract

    if not instrument_ids:
        return {}
    return {
        o.instrumentId: o.multiplier
        for o in s.scalars(
            select(OptionContract).where(
                OptionContract.instrumentId.in_(instrument_ids),
                OptionContract.deleted == false(),
            )
        )
    }


@dataclass
class Part:
    """One part of what an account holds (S5.2.3): its cash, a security, an option, what a
    loan owes (negative), or an item. `value` is None for a holding with no price, which counts
    nothing."""

    kind: str  # "cash", "security", "option", "loan", "item"
    name: str
    value: Decimal | None
    position: Position | None = None
    item: object | None = None  # the Item, for an item
    accountType: str = ""


def parts(s: Session, ledger, investing: bool, day: dt.date | None = None) -> list[Part]:
    """What an account holds on a day, part by part: the one breakdown every figure built on
    accounts adds up (its value, a portfolio's Holdings, a projection's start). A loan is minus
    what is owed, from its terms and payments (S1.9); a physical-asset account, each of its
    items at what it is worth (S1.10); any other account, its cash and, when it invests, each
    holding at its price."""
    from . import assets, loans

    a = ledger.account
    if loans.is_loan(a.type):
        return [Part("loan", a.name, loans.value(s, a, day), accountType=a.type)]
    if assets.is_physical(a.type):
        return [
            Part("item", it.name, worth, item=it, accountType=a.type)
            for it, worth in assets.worth(s, a, day)
        ]
    out = [Part("cash", a.name, ledger.balance(day), accountType=a.type)]
    if investing:
        for p in positions(s, ledger, day):
            kind = "option" if p.multiplier != 1 else "security"
            out.append(Part(kind, p.instrumentId, p.value, position=p, accountType=a.type))
    return out


def account_value(s: Session, ledger, investing: bool, day: dt.date | None = None) -> Decimal:
    """What an account is worth on a day: the sum of its parts (a holding with no price counts
    nothing)."""
    return sum((p.value or ZERO for p in parts(s, ledger, investing, day)), ZERO)


def market_points(
    s: Session, instrument_ids: list[str], first: dt.date, last: dt.date
) -> dict[str, list[tuple[dt.date, Decimal]]]:
    """The stored closes alone from `first` to `last` (the last before `first` too), oldest
    first: a benchmark's line, the market's for everyone."""
    out: dict[str, list[tuple[dt.date, Decimal]]] = {i: [] for i in instrument_ids}
    if not instrument_ids:
        return out
    for iid, p in closes(s, instrument_ids, first).items():
        out[iid].append((p.asOf, p.price))
    if _history and last > first:
        for iid, rows in _history[0](s, instrument_ids, first, last).items():
            out[iid] += rows
    return out


def price_points(
    s: Session,
    instrument_ids: list[str],
    first: dt.date,
    last: dt.date,
    *,
    owner: str,
) -> dict[str, list[tuple[dt.date, Decimal]]]:
    """Each instrument's price from `first` to `last`, as the days it changes on, oldest
    first, by the one order of sources (`_tiers`): its value on any day is the last point on or
    before it, which is what `prices` gives for that day."""
    out: dict[str, list[tuple[dt.date, Decimal]]] = {i: [] for i in instrument_ids}
    if not instrument_ids:
        return out
    for iid, tiers in _tiers(s, list(dict.fromkeys(instrument_ids)), first, last, owner).items():
        # Walked once, day by day of the points: each tier's latest so far, the first tier
        # with one deciding, as `_effective` does for a single day.
        days = sorted({max(p.asOf, first) for tier in tiers for p in tier if p.asOf <= last})
        at = [0, 0, 0]
        now: list[Price | None] = [None, None, None]
        # Any non-Decimal start differs from every price, so the first point is always kept.
        was = None  # pragma: no mutate
        for d in days:
            for k, tier in enumerate(tiers):
                while at[k] < len(tier) and max(tier[at[k]].asOf, first) <= d:
                    now[k] = tier[at[k]]
                    at[k] += 1
            # Every day is some point's own, taken in just above: a tier always has a price by it.
            p = next((x for x in now if x is not None), None)  # pragma: no mutate
            if p is not None and p.price != was:
                out[iid].append((d, p.price))
                was = p.price
    return out


def series(
    s: Session,
    ledger,
    investing: bool,
    first: dt.date,
    last: dt.date,
    step_days: int = 1,
    options: bool = True,
) -> list[tuple[dt.date, Decimal]]:
    """The account's value at the end of each day (or every step_days), for its chart; without
    `options`, leaving its options out, as a projection does. Positions change only on the days
    of trades and snapshots, so the ledger is replayed on those days alone; prices are carried
    forward from the last known one."""
    from . import assets, loans

    if assets.is_physical(ledger.account.type):
        return assets.series(s, ledger.account, first, last, step_days)
    if loans.is_loan(ledger.account.type):
        row = loans.loan_of(s, ledger.account)
        if row is None:
            return []
        terms = loans.terms_of(row)
        payments, draws = loans.history(s, ledger.account)
        out, day = [], first
        while day <= last:
            out.append((day, -loans.balance_on(terms, payments, draws, day)))
            day += dt.timedelta(days=step_days)
        if out and out[-1][0] != last:
            out.append((last, -loans.balance_on(terms, payments, draws, last)))
        return out
    cash = dict(balances.daily(ledger.opening(), ledger.transactions, first, last))
    days = sorted(cash)
    if step_days > 1:
        days = sorted({*days[::step_days], last})
    if not investing:
        return [(d, cash[d]) for d in days]
    changes = sorted(
        {t.date for t in ledger.transactions if t.instrumentId and first < t.date <= last}
        | {h.asOf for h in ledger.snapshots if first < h.asOf <= last}
    )
    held: list[tuple[dt.date, dict[str, Decimal]]] = [(first, _positions_on(ledger, first))]
    for day in changes:
        held.append((day, _positions_on(ledger, day)))
    ids_ = sorted({i for _, pos in held for i in pos})
    points = price_points(s, ids_, first, last, owner=ledger.account.ownerId)
    mult = multipliers(s, ids_)
    out = []
    h_i = 0
    cursor = {i: 0 for i in ids_}
    current: dict[str, Decimal | None] = {i: None for i in ids_}
    for day in days:
        while h_i + 1 < len(held) and held[h_i + 1][0] <= day:
            h_i += 1
        for iid in ids_:
            pts = points[iid]
            while cursor[iid] < len(pts) and pts[cursor[iid]][0] <= day:
                current[iid] = pts[cursor[iid]][1]
                cursor[iid] += 1
        value = cash[day]
        for iid, qty in held[h_i][1].items():
            if not options and iid in mult:
                continue
            if current.get(iid) is not None:
                value += (qty * current[iid] * mult.get(iid, 1)).quantize(CENT)
        out.append((day, value))
    return out


def flows(
    s: Session, ledger, investing: bool, first: dt.date, last: dt.date
) -> dict[dt.date, Decimal]:
    """The money that came into the account from outside (+) or left it (−), per day from
    `first` (after it) to `last`, valued as `series` values the account (CR3-28): cash in and
    out; shares moved in or out at the price the series takes for them that day; an item
    added at its worth then, one sold at what its sale brought; a loan's opening
    balance owed and its draws as money out, its payments as money in. So a day with only a
    move has no growth, and the returns, contributions and benchmark read the same money."""
    from . import assets, loans
    from .ledger import performance as perf

    a = ledger.account
    out: dict[dt.date, Decimal] = {}

    def add(day: dt.date, amount: Decimal) -> None:
        if first < day <= last and amount:
            out[day] = out.get(day, ZERO) + amount

    if loans.is_loan(a.type):
        row = loans.loan_of(s, a)
        if row is None:
            return out
        terms = loans.terms_of(row)
        add(terms.start, -terms.principal)
        for t in ledger.transactions:
            add(t.date, t.amount)  # a payment in, a draw out
        return out
    if assets.is_physical(a.type):
        # Only the items are read, not their worth, and the items don't depend on the day.
        for it, _ in assets.worth(s, a, last):  # pragma: no mutate
            add(it.acquiredOn, assets.worth_on(s, it, it.acquiredOn))
            # Its sale takes out what it brought, so a gain on it is growth. A sold item always
            # has its proceeds (the table's check `sale`); the test is for the type checker.
            if it.soldOn is not None and it.proceeds is not None:
                add(it.soldOn, (it.saleFees or ZERO) - it.proceeds)
        return out
    for day, amount in perf.flows(ledger.transactions).items():
        add(day, amount)
    if not investing:
        return out
    moved = [
        t
        for t in ledger.transactions
        if t.kind in ("transfer-in", "transfer-out")
        and t.instrumentId
        and t.quantity
        and first < t.date <= last
    ]
    if not moved:
        return out
    ids_ = sorted({t.instrumentId for t in moved})
    points = price_points(s, ids_, first, last, owner=a.ownerId)
    mult = multipliers(s, ids_)
    for t in moved:
        pts = [p for d, p in points[t.instrumentId] if d <= t.date]
        if not pts:
            continue  # no price yet: the series counts it nothing, and so does its flow
        qty = abs(t.quantity) * (1 if t.kind == "transfer-in" else -1)
        add(t.date, (qty * pts[-1] * mult.get(t.instrumentId, 1)).quantize(CENT))
    return out


def _positions_on(ledger, day: dt.date) -> dict[str, Decimal]:
    return ledger.replay(day).positions()
