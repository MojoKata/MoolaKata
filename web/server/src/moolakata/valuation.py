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


def _owned(stmt, entity, owner: str | None):
    """Only what the owner's own accounts hold: another user's files and trades never value
    theirs (S4.10)."""
    if owner is None:
        return stmt
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


def prices(
    s: Session, instrument_ids: list[str], day: dt.date | None = None, owner: str | None = None
) -> dict[str, Price]:
    """The latest price on or before the day for each instrument, for the accounts of `owner`
    (none: closes alone and every fallback)."""
    day = day or clock.today()
    ids_ = list(dict.fromkeys(instrument_ids))
    out: dict[str, Price] = {}
    if not ids_:
        return out
    insts = {i.id: i for i in s.scalars(select(Instrument).where(Instrument.id.in_(ids_)))}
    for iid, inst in insts.items():
        if inst.instrumentClass in ("cash", "money-market"):
            out[iid] = Price(Decimal(1), day, "fixed")
    if _closes:
        for iid, p in _closes[0](s, [i for i in ids_ if i not in out], day).items():
            out[iid] = p
    if owner is not None:
        for t in typed(
            s, owner, [i for i in ids_ if i not in out or out[i].source != "fixed"], None, day
        ):
            if t.instrumentId not in out or t.date >= out[t.instrumentId].asOf:
                stale = (min(day, clock.today()) - t.date).days > TYPED_STALE_DAYS
                out[t.instrumentId] = Price(t.close, t.date, "manual", stale)
    missing = [i for i in ids_ if i not in out]
    if missing:
        for h in s.scalars(
            _owned(select(Holding), Holding, owner)
            .where(
                Holding.instrumentId.in_(missing),
                Holding.deleted == false(),
                Holding.asOf <= day,
                Holding.marketValue.is_not(None),
            )
            .order_by(Holding.asOf)
        ):
            if h.quantity:
                out[h.instrumentId] = Price(h.marketValue / h.quantity, h.asOf, "statement")
    # An option's last trade isn't its mark: intrinsic value stands in instead (S3.7).
    missing = [i for i in ids_ if i not in out and i not in multipliers(s, ids_)]
    if missing:
        for txn in s.scalars(
            _owned(select(Transaction), Transaction, owner)
            .where(
                Transaction.instrumentId.in_(missing),
                Transaction.deleted == false(),
                Transaction.price.is_not(None),
                Transaction.date <= day,
            )
            .order_by(Transaction.date)
        ):
            out[txn.instrumentId] = Price(txn.price, txn.date, "trade")
    return out


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
    found = prices(s, list(by), day, ledger.account.ownerId)
    mult = multipliers(s, list(by))
    for iid in by:
        if iid in mult and iid not in found:
            mark = intrinsic(s, iid, day, ledger.account.ownerId)
            if mark is not None:
                found[iid] = mark
    out = []
    for iid, open_lots in by.items():
        qty = sum((x.quantity for x in open_lots), ZERO)
        basis = (
            None
            if any(x.basis is None for x in open_lots)
            else sum((x.basis for x in open_lots), ZERO)
        )
        out.append(Position(iid, qty, basis, found.get(iid), mult.get(iid, 1)))
    return out


def intrinsic(
    s: Session, instrument_id: str, day: dt.date | None = None, owner: str | None = None
) -> Price | None:
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
                OptionContract.instrumentId.in_(instrument_ids), OptionContract.deleted == false()
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


def price_points(
    s: Session,
    instrument_ids: list[str],
    first: dt.date,
    last: dt.date,
    owner: str | None = None,
) -> dict[str, list[tuple[dt.date, Decimal]]]:
    """Every known price of each instrument up to last, oldest first, from the same sources
    as `prices` and in the same precedence, for the accounts of `owner`: an instrument with
    stored closes or typed prices is valued from them alone; one without, from statement
    values and trades."""
    out: dict[str, list[tuple[dt.date, Decimal]]] = {i: [] for i in instrument_ids}
    if not instrument_ids:
        return out
    closed: set[str] = set()
    for iid, p in prices(s, instrument_ids, first, owner).items():
        out[iid].append((p.asOf, p.price))
        if p.source in ("close", "manual", "fixed"):
            closed.add(iid)
    if _history:
        for iid, rows in _history[0](s, instrument_ids, first, last).items():
            out[iid] += rows
            closed.add(iid)
    if owner is not None:
        # A typed price stands on its day, after the close of that day (S4.10).
        later = {}
        for t in typed(s, owner, instrument_ids, first, last):
            later.setdefault(t.instrumentId, []).append((t.date, t.close))
            closed.add(t.instrumentId)
        for iid, rows in later.items():
            out[iid] += rows
    others = [i for i in instrument_ids if i not in closed]
    if others:
        for h in s.scalars(
            _owned(select(Holding), Holding, owner).where(
                Holding.instrumentId.in_(others),
                Holding.deleted == false(),
                Holding.asOf > first,
                Holding.asOf <= last,
                Holding.marketValue.is_not(None),
            )
        ):
            if h.quantity:
                out[h.instrumentId].append((h.asOf, h.marketValue / h.quantity))
        statement = {iid for iid in others if out[iid]}
        for t in s.scalars(
            _owned(select(Transaction), Transaction, owner).where(
                Transaction.instrumentId.in_(others),
                Transaction.deleted == false(),
                Transaction.price.is_not(None),
                Transaction.date > first,
                Transaction.date <= last,
            )
        ):
            if t.instrumentId not in statement:
                out[t.instrumentId].append((t.date, t.price))
    for iid in out:
        out[iid] = sorted(dict(out[iid]).items())
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
    points = price_points(s, ids_, first, last, ledger.account.ownerId)
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


def _positions_on(ledger, day: dt.date) -> dict[str, Decimal]:
    return ledger.replay(day).positions()
