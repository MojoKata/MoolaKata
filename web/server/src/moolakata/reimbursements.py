"""Reimbursable spending (requirements S2.9): a transaction, or one split of it, marked as to be
paid back, and the deposits paired with it. Budgets don't count what is awaited or paid back,
nor the part of a deposit that pays spending back (S7.3.4)."""

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from .store.entities.accounts import Reimbursement, Split, Transaction

ZERO = Decimal(0)
WINDOW = dt.timedelta(days=90)  # a payback arrives within this after the spending


def _sums(s: Session, column, ids: list[str]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for chunk in range(0, len(ids), 500):
        for r in s.scalars(
            select(Reimbursement).where(
                column.in_(ids[chunk : chunk + 500]), Reimbursement.deleted == false()
            )
        ):
            out[getattr(r, column.key)] += r.amount
    return dict(out)


def paid_back(s: Session, spending_ids: list[str]) -> dict[str, Decimal]:
    """What paired deposits have paid back of each transaction and its splits."""
    return _sums(s, Reimbursement.spendingId, spending_ids)


def paired_out(s: Session, payback_ids: list[str]) -> dict[str, Decimal]:
    """How much of each deposit pays spending back."""
    return _sums(s, Reimbursement.paybackId, payback_ids)


@dataclass
class Awaiting:
    spendingId: str
    splitId: str | None
    accountId: str
    date: dt.date
    payee: str | None
    categoryId: str | None
    owedBy: str | None
    reimbursable: Decimal
    paidBack: Decimal

    @property
    def awaited(self) -> Decimal:
        return self.reimbursable - self.paidBack


def marked(s: Session, accounts: list[str]) -> list[Awaiting]:
    """Every mark in the accounts, paid back in full or not, oldest first."""
    if not accounts:
        return []
    out: list[Awaiting] = []
    txns = s.scalars(
        select(Transaction).where(
            Transaction.accountId.in_(accounts),
            Transaction.deleted == false(),
            Transaction.reimbursable.is_not(None),
        )
    ).all()
    split_rows = s.execute(
        select(Split, Transaction)
        .join(Transaction, Transaction.id == Split.transactionId)
        .where(
            Transaction.accountId.in_(accounts),
            Transaction.deleted == false(),
            Split.deleted == false(),
            Split.reimbursable.is_not(None),
        )
    ).all()
    pairs = s.scalars(
        select(Reimbursement).where(
            Reimbursement.spendingId.in_([t.id for t in txns] + [t.id for _, t in split_rows]),
            Reimbursement.deleted == false(),
        )
    ).all()
    paid: dict[tuple[str, str | None], Decimal] = defaultdict(lambda: ZERO)
    for r in pairs:
        paid[(r.spendingId, r.splitId)] += r.amount
    for t in txns:
        out.append(
            Awaiting(
                t.id,
                None,
                t.accountId,
                t.date,
                t.payee,
                t.categoryId,
                t.owedBy,
                t.reimbursable,
                paid[(t.id, None)],
            )
        )
    for sp, t in split_rows:
        out.append(
            Awaiting(
                t.id,
                sp.id,
                t.accountId,
                t.date,
                t.payee,
                sp.categoryId,
                sp.owedBy,
                sp.reimbursable,
                paid[(t.id, sp.id)],
            )
        )
    return sorted(out, key=lambda a: (a.date, a.spendingId, a.splitId or ""))


def offers(
    s: Session, item: Awaiting, accounts: list[str], limit: int = 5
) -> list[tuple[Transaction, Decimal]]:
    """Deposits that may pay a mark back: money in, not a transfer, within 90 days after the
    spending, with some of it not yet pairing other spending. The amount awaited first, then
    the deposits no larger than it, then the larger ones (an expense report paying several)."""
    if item.awaited <= 0 or not accounts:
        return []
    rows = s.scalars(
        select(Transaction).where(
            Transaction.accountId.in_(accounts),
            Transaction.deleted == false(),
            Transaction.transferId.is_(None),
            Transaction.amount > 0,
            Transaction.instrumentId.is_(None),
            Transaction.date >= item.date,
            Transaction.date <= item.date + WINDOW,
        )
    ).all()
    used = paired_out(s, [t.id for t in rows])
    free = [(t, t.amount - used.get(t.id, ZERO)) for t in rows]
    free = [(t, f) for t, f in free if f > 0]
    free.sort(key=lambda x: (x[1] != item.awaited, x[1] > item.awaited, x[0].date))
    return free[:limit]
