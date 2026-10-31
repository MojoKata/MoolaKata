"""Wash sales (requirements S3.8): a loss sale of a stock or fund with the same instrument bought
within 30 days either side, in any of the user's accounts (IRAs included) or their spouse's.
The disallowed loss moves to the replacement's basis, with the sold shares' holding period.
Worked out again from the trades whenever they change, for the user and their spouse together,
and stored for the ledger to apply."""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, false, select
from sqlalchemy.orm import Session

from . import clock, ids
from .ledger import types as atypes
from .store import scoping
from .store.entities.accounts import Account, Instrument, Lot, Transaction, WashSale
from .store.repos import ledger as repo

DAYS = 30
CENT = Decimal("0.01")
CLASSES = ("equity", "etf", "mutual-fund")


def household(s: Session, user_id: str) -> list[str]:
    """The user and everyone ever married to them, and to those in turn (S10.10.4), whose
    trades are worked out together; a match counts only with the spouse on the day sold."""
    from . import people

    seen, todo = {user_id}, [user_id]
    while todo:
        for other in people.spouse_users_ever(s, todo.pop()):
            if other not in seen:
                seen.add(other)
                todo.append(other)
    return sorted(seen)


@dataclass
class _Buy:
    txn: Transaction
    remaining: Decimal


def recompute(s: Session, user_id: str) -> int:
    """The household's wash sales, worked out from its trades and stored whole: the server's
    work across the user's and their spouse's accounts, whoever's change set it off."""
    with scoping.as_server(s, "wash sales: worked out again") as server:
        return _recompute(server, user_id)


def _recompute(s: Session, user_id: str) -> int:
    who = household(s, user_id)
    s.execute(delete(WashSale).where(WashSale.ownerId.in_(who)))
    accounts = list(
        s.scalars(select(Account).where(Account.ownerId.in_(who), Account.deleted == false()))
    )
    if not accounts:
        return 0
    by_id = {a.id: a for a in accounts}
    classes = {
        i.id: i.instrumentClass
        for i in s.scalars(select(Instrument).where(Instrument.instrumentClass.in_(CLASSES)))
    }
    # Shares that came through an option (a put assigned, a call exercised) are never taken
    # as a replacement: the rules leave that to the preparer, flagged for review (S3.8.5.3).
    through_options = set(
        s.scalars(
            select(Transaction.id).where(
                Transaction.accountId.in_(list(by_id)),
                Transaction.kind.in_(("assign", "exercise")),
            )
        )
    )
    buys: dict[str, list[_Buy]] = {}
    for t in s.scalars(
        select(Transaction).where(
            Transaction.accountId.in_(list(by_id)),
            Transaction.deleted == false(),
            Transaction.kind.in_(("buy", "reinvest")),
            Transaction.instrumentId.in_(list(classes)),
        )
    ):
        if t.quantity and t.optionTransactionId not in through_options:
            buys.setdefault(t.instrumentId, []).append(_Buy(t, abs(t.quantity)))
    lot_txn = {
        lot.id: lot.transactionId
        for lot in s.scalars(select(Lot).where(Lot.accountId.in_(list(by_id))))
    }
    ledgers = [
        repo.load(s, a, raw=True)
        for a in accounts
        if atypes.TAX.get(a.type) == "taxable" and atypes.investing(a.type)
    ]
    from . import people

    spouse_on: dict[tuple[str, dt.date], str | None] = {}

    def counts(seller: str, buyer: str, day: dt.date) -> bool:
        """A buy counts in the seller's own accounts, or their spouse's on the day sold."""
        if seller == buyer:
            return True
        if (seller, day) not in spouse_on:
            spouse_on[(seller, day)] = people.spouse_user_on(s, seller, day)
        return spouse_on[(seller, day)] == buyer

    # A deferred loss moves into its replacement's basis, so selling that at a loss can defer
    # it again: the losses are found on the replay with the wash sales so far applied, again
    # and again, until nothing changes (S3.8.3, S3.8.4).
    now = clock.now()
    rows: list[WashSale] = []
    for _ in range(ROUNDS):
        found = _round(ledgers, rows, classes, buys, lot_txn, by_id, counts, now)
        if _same(found, rows):
            break
        rows = found
    for w in rows:
        s.add(w)
    s.flush()
    return len(rows)


ROUNDS = 12


def _same(a: list[WashSale], b: list[WashSale]) -> bool:
    key = lambda w: (w.saleId, w.replacementId, w.quantity, w.disallowed, w.heldFrom)  # noqa: E731
    return sorted(map(key, a)) == sorted(map(key, b))


def _round(ledgers, rows, classes, buys, lot_txn, by_id, counts, now) -> list[WashSale]:
    losses = []
    for led in ledgers:
        ids_ = {t.id for t in led.transactions}
        led.washes = [w for w in rows if w.saleId in ids_ or w.replacementId in ids_]
        for d in led.replay().disposals:
            raw = d.raw_gain
            if d.instrumentId in classes and raw is not None and raw < 0 and d.saleId:
                losses.append((led.account, d))
    losses.sort(key=lambda x: x[1].soldOn)
    remaining = {id(b): b.remaining for group in buys.values() for b in group}
    out = []
    for a, d in losses:
        own = lot_txn.get(d.lotId) if d.lotId else None
        left = d.quantity
        loss = -d.raw_gain
        for b in sorted(
            buys.get(d.instrumentId, []), key=lambda b: abs((b.txn.date - d.soldOn).days)
        ):
            if left <= 0:
                break
            if abs((b.txn.date - d.soldOn).days) > DAYS or remaining[id(b)] <= 0:
                continue
            if not counts(a.ownerId, by_id[b.txn.accountId].ownerId, d.soldOn):
                continue
            if b.txn.id == own or b.txn.id == d.saleId:
                continue
            if own is None and b.txn.date == d.acquiredOn and b.txn.accountId == a.id:
                continue  # the shares that were sold
            take = min(left, remaining[id(b)])
            remaining[id(b)] -= take
            left -= take
            held_from = d.heldFrom or d.acquiredOn
            out.append(
                WashSale(
                    id=ids.new_id("WashS"),
                    ownerId=a.ownerId,
                    saleId=d.saleId,
                    replacementId=b.txn.id,
                    quantity=take,
                    disallowed=(loss * take / d.quantity).quantize(CENT),
                    heldFrom=b.txn.date - (d.soldOn - held_from),
                    createdAt=now,
                )
            )
    return out


def for_users(s: Session, user_ids: list[str], first: dt.date, last: dt.date) -> list[WashSale]:
    """The wash sales of these users' sales between two days."""
    return list(
        s.scalars(
            select(WashSale)
            .join(Transaction, Transaction.id == WashSale.saleId)
            .where(
                WashSale.ownerId.in_(user_ids),
                Transaction.date >= first,
                Transaction.date <= last,
            )
        )
    )
