"""Corporate actions (requirements S2.4): a split, a symbol change, a spin-off or a merger,
each recorded as transactions that move or reshape lots, never as a sale and a buy. A move
between instruments is a pair linked by the new leg's transferId: the old instrument's first,
then the new one's with its ratio."""

import datetime as dt
from decimal import Decimal

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from . import ids
from .errors import FieldError, Problem
from .ledger import lots
from .store.entities.accounts import Account, Instrument, Transaction
from .store.repos import ledger as repo

KINDS = ("split", "symbol-change", "spin-off", "merger")
WORDS = {
    "split": "Split",
    "symbol-change": "Symbol change",
    "spin-off": "Spin-off",
    "merger": "Merger",
}


def record(
    s: Session,
    user_id: str,
    account: Account,
    inst: Instrument,
    kind: str,
    day: dt.date,
    ratio: Decimal | None,
    new_symbol: str | None,
    basis_share: Decimal | None = None,
    cash_per_share: Decimal | None = None,
    new_price: Decimal | None = None,
) -> list[Transaction]:
    """The transactions a corporate action makes, checked first; refused field by field."""
    e: list[FieldError] = []
    held = repo.load(s, account).replay().quantity(inst.id)
    if held <= 0:
        e.append(FieldError("instrumentId", "nothing-held", "Nothing of it is held here."))
    new_symbol = (new_symbol or "").strip().upper() or None
    all_cash = kind == "merger" and new_symbol is None
    needs_ratio = kind in ("split", "spin-off") or (kind == "merger" and not all_cash)
    if needs_ratio and (ratio is None or ratio <= 0):
        e.append(FieldError("ratio", "ratio-invalid", "New shares for each one held: 2, 0.5."))
    if kind in ("symbol-change", "spin-off") and new_symbol is None:
        e.append(FieldError("newSymbol", "symbol-missing", "The new symbol."))
    if new_symbol and (len(new_symbol) > 12 or new_symbol == inst.symbol):
        e.append(FieldError("newSymbol", "symbol-invalid", "Another instrument's symbol."))
    if kind == "spin-off" and (basis_share is None or not 0 < basis_share < 100):
        e.append(
            FieldError("basisShare", "share-invalid", "The basis that moves, in percent: 13.65.")
        )
    if kind == "merger":
        # Asked of every merger, so cash left out is never read as none (R3.11).
        if all_cash and not cash_per_share:
            e.append(FieldError("cashPerShare", "cash-missing", "What each share was paid."))
        elif cash_per_share is None:
            e.append(
                FieldError(
                    "cashPerShare",
                    "cash-missing",
                    "The cash for each share held: 0 for a merger paid all in shares.",
                )
            )
        if cash_per_share is not None and cash_per_share < 0:
            e.append(FieldError("cashPerShare", "cash-invalid", "Zero or more."))
        if cash_per_share and not all_cash and (new_price is None or new_price <= 0):
            e.append(
                FieldError(
                    "newPrice", "price-missing", "A new share's price that day, for the gain."
                )
            )
    if e:
        raise Problem(422, e[0].code, e[0].message, e)
    word = WORDS[kind]
    if kind == "split":
        t = _txn(account, user_id, day, "split", inst.id, f"{word} {ratio.normalize():f} for 1")
        t.splitRatio = ratio
        s.add(t)
        s.flush()
        from .options import adjust

        adjust.with_split(s, user_id, account, t)
        return [t]
    cash = ((cash_per_share or Decimal(0)) * held).quantize(Decimal("0.01"))
    old = _txn(account, user_id, day, kind, inst.id, f"{word}: {inst.symbol}")
    old.quantity = held
    old.amount = cash if kind == "merger" else Decimal(0)
    if kind == "spin-off":
        old.splitRatio = basis_share / 100
    s.add(old)
    s.flush()
    if all_cash:
        old.lotMethod = account.lotMethod
        return [old]
    new = repo.instrument(s, new_symbol, None, inst.instrumentClass)
    leg = _txn(account, user_id, day, kind, new.id, f"{word}: {inst.symbol} to {new.symbol}")
    leg.transferId = old.id
    leg.quantity = held * (ratio or Decimal(1))
    leg.splitRatio = ratio or Decimal(1)
    leg.price = new_price
    s.add(leg)
    s.flush()
    return [old, leg]


def _txn(account, user_id, day, kind, inst_id, payee) -> Transaction:
    return Transaction(
        id=ids.new_id("Txn"),
        accountId=account.id,
        date=day,
        kind=kind,
        amount=Decimal(0),
        payee=payee,
        instrumentId=inst_id,
        createdById=user_id,
    )


def undo(s: Session, by: str, txn: Transaction) -> None:
    """Deleting either leg of a pair deletes the other."""
    others = list(
        s.scalars(
            select(Transaction).where(
                Transaction.transferId == txn.id,
                Transaction.kind.in_(lots.CORPORATE),
                Transaction.deleted == false(),
            )
        )
    )
    if txn.transferId:
        other = s.get(Transaction, txn.transferId)
        if other is not None and not other.deleted:
            others.append(other)
    for o in others:
        o.mark_deleted(by)
