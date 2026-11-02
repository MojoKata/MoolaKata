"""Reserves and where their money is (requirements S7.10): a monthly line with a target puts in
its amount each month, never more than reaches the target, and spending in its category takes
from it; its balance is worked out, never stored. For each account reserves are held in, what
is to move there, or back, is worked out from what the reserves gained against what was moved
in (S7.10.4), and money that lands there otherwise waits to be given (S7.10.5)."""

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from ..store.entities.accounts import Account, Transaction
from ..store.entities.budgets import Budget, BudgetLine, BudgetMove
from . import (
    ZERO,
    Members,
    Tree,
    _actual,
    _monthly,
    add_months,
    in_force,
    month_end,
    month_of,
    other_halves,
)

MoveKey = tuple[dt.date, str]  # (month, category id)


def moves(s: Session, b: Budget) -> list[BudgetMove]:
    return list(
        s.scalars(
            select(BudgetMove).where(BudgetMove.budgetId == b.id, BudgetMove.deleted == false())
        )
    )


def net_moves(rows: list[BudgetMove]) -> dict[MoveKey, Decimal]:
    """What moves put into (+) or took out of (−) each category, by month."""
    out: dict[MoveKey, Decimal] = defaultdict(lambda: ZERO)
    for m in rows:
        if m.toCategoryId:
            out[(m.month, m.toCategoryId)] += m.amount
        if m.fromCategoryId:
            out[(m.month, m.fromCategoryId)] -= m.amount
    return out


@dataclass
class Reserve:
    categoryId: str
    target: Decimal
    heldInId: str | None
    start: Decimal  # the balance the month began with
    putIn: Decimal
    spent: Decimal
    moved: Decimal  # moves in, less moves out
    began: dt.date  # the first month of the run of lines with a target

    @property
    def balance(self) -> Decimal:
        return self.start + self.putIn + self.moved - self.spent

    @property
    def funded(self) -> bool:
        return self.balance >= self.target


def reserve(
    s: Session,
    tr: Tree,
    mem: Members,
    every: list[BudgetLine],
    moved: dict[MoveKey, Decimal],
    cat_id: str,
    month: dt.date,
) -> Reserve | None:
    """A reserve's month: the balance it began with, what it put in, what was spent and moved.
    A month without a line, or with a line without a target, sets it back to nothing."""
    mine = [ln for ln in every if ln.categoryId == cat_id]
    if not mine:
        return None
    first = mine[0].fromMonth
    totals = _monthly(s, mem, first, month, tr)
    bal, began = ZERO, first
    m = first
    while m <= month:
        ln = in_force(mine, m).get(cat_id)
        if ln is None or ln.target is None or ln.cadence != "month":
            bal, began = ZERO, add_months(m, 1)
            if m == month:
                return None
            m = add_months(m, 1)
            continue
        put = min(ln.amount, max(ln.target - bal, ZERO))
        spent = _actual(tr, totals.get(m, {}), cat_id)
        mv = moved.get((m, cat_id), ZERO)
        if m == month:
            return Reserve(cat_id, ln.target, ln.heldInId, bal, put, spent, mv, began)
        bal = bal + put + mv - spent
        m = add_months(m, 1)
    return None


# ---------- where the money is (S7.10.4, S7.10.5) ----------


@dataclass
class Landed:
    transactionId: str
    date: dt.date
    payee: str | None
    amount: Decimal
    free: Decimal  # not yet given to a reserve, nor kept


@dataclass
class HeldIn:
    accountId: str
    reserves: list[tuple[str, Decimal]]  # category id, balance
    total: Decimal
    movedIn: Decimal  # transfers in from the budget's other accounts, net
    given: Decimal  # landed money given to the reserves here
    balance: Decimal  # the account's
    withdrawals: int  # this month
    limit: int | None
    unassigned: list[Landed] = field(default_factory=list)
    # This month's transfers in from the budget's accounts, each counted for the reserves
    # unless kept as the account's own (S7.10.4).
    transfers: list[tuple[Landed, bool]] = field(default_factory=list)

    @property
    def toMove(self) -> Decimal:
        return self.total - self.movedIn - self.given


def held_in(
    s: Session,
    b: Budget,
    mem: Members,
    tr: Tree,
    every: list[BudgetLine],
    move_rows: list[BudgetMove],
    month: dt.date,
) -> list[HeldIn]:
    from ..store.repos import ledger

    moved = net_moves(move_rows)
    now = in_force(every, month)
    by_account: dict[str, list[Reserve]] = defaultdict(list)
    for cat_id, ln in now.items():
        if ln.target is None or not ln.heldInId:
            continue
        r = reserve(s, tr, mem, every, moved, cat_id, month)
        if r is not None:
            by_account[ln.heldInId].append(r)
    end = month_end(month)
    out = []
    for aid, rs in by_account.items():
        a = s.get(Account, aid)
        if a is None or a.deleted:
            continue
        since = min(r.began for r in rs)
        cats = {r.categoryId for r in rs}
        txns = s.scalars(
            select(Transaction).where(
                Transaction.accountId == aid,
                Transaction.deleted == false(),
                Transaction.date >= since,
                Transaction.date <= end,
            )
        ).all()
        others = {
            k: o.accountId
            for k, o in other_halves(s, [t.transferId for t in txns if t.transferId]).items()
        }

        def from_inside(t, aid=aid, others=others) -> bool:
            """A transfer with another of the budget's accounts, as they were that month."""
            o = others.get(t.transferId) if t.transferId else None
            return o is not None and o != aid and mem.counts(o, t.date)

        given_rows = [m for m in move_rows if m.transactionId and m.month <= month]
        # A transfer kept as the account's own (savings of its own) isn't the reserves'.
        own: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for m in given_rows:
            if m.toCategoryId is None:
                own[m.transactionId] += m.amount
        moved_in = sum(
            (
                t.amount - (own.get(t.id, ZERO) if t.amount > 0 else ZERO)
                for t in txns
                if from_inside(t)
            ),
            ZERO,
        )
        by_txn: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for m in given_rows:
            by_txn[m.transactionId] += m.amount
        given = sum(
            (m.amount for m in given_rows if m.toCategoryId in cats and m.transactionId), ZERO
        )
        unassigned = []
        for t in txns:
            landed = t.amount > 0 and not from_inside(t)
            if not landed or month_of(t.date) != month:
                continue
            free = t.amount - by_txn.get(t.id, ZERO)
            if free > 0:
                unassigned.append(Landed(t.id, t.date, t.payee, t.amount, free))
        out.append(
            HeldIn(
                accountId=aid,
                reserves=[(r.categoryId, r.balance) for r in rs],
                total=sum((r.balance for r in rs), ZERO),
                movedIn=moved_in,
                given=given,
                balance=ledger.load(s, a).balance(end),
                withdrawals=sum(1 for t in txns if t.amount < 0 and month_of(t.date) == month),
                limit=a.withdrawalsAMonth,
                unassigned=unassigned,
                transfers=[
                    (
                        Landed(t.id, t.date, t.payee, t.amount, t.amount - own.get(t.id, ZERO)),
                        own.get(t.id, ZERO) > 0,
                    )
                    for t in txns
                    if t.amount > 0 and from_inside(t) and month_of(t.date) == month
                ],
            )
        )
    return out
