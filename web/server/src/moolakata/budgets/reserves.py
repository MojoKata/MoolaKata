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
    line_of,
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
        spent = _actual(tr, totals.get(m, {}), cat_id, in_force(every, m))
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


@dataclass(frozen=True)
class Flow:
    """One part of a transaction in an account reserves are held in, in exactly one class
    (S7.10.4): *moved* (a transfer with one of the budget's accounts, that month), *reserve*
    (spending or a refund, either sign, in a reserve's category: the reserve's own money, held
    here or not), *landed* (money in otherwise: given to the reserves, kept as the account's own,
    or unassigned, S7.10.5) or *own* (the rest: a fee, other spending, a transfer out of the
    budget)."""

    transactionId: str
    date: dt.date
    kind: str
    amount: Decimal  # signed, as in the account
    otherId: str | None = None  # moved: the budget's account at the other end
    reserveIn: str | None = None  # reserve: the account the reserve is held in (None: nowhere)


def classify(
    t: Transaction,
    parts: list,
    other: str | None,
    aid: str,
    mem: Members,
    tr: Tree,
    plan_at,
) -> list[Flow]:
    """A transaction's flows: a transfer with one of the budget's accounts that month whole;
    otherwise each part (its splits, or the whole) by its category's line that month."""
    if other is not None and other != aid and mem.counts(other, t.date):
        return [Flow(t.id, t.date, "moved", t.amount, otherId=other)]
    now = plan_at(month_of(t.date))
    out = []
    for category, amount in parts or [(t.categoryId, t.amount)]:
        line = line_of(tr, now, category) if category else None
        ln = now.get(line) if line else None
        if ln is not None and ln.target is not None and ln.cadence == "month":
            out.append(Flow(t.id, t.date, "reserve", amount, reserveIn=ln.heldInId))
        elif amount > 0:
            out.append(Flow(t.id, t.date, "landed", amount))
        else:
            out.append(Flow(t.id, t.date, "own", amount))
    return out


@dataclass
class Between:
    """Money a cross payment left in the wrong account (S7.10.4): one account paid for a reserve
    held in another, so the one holding it gives that much to the one that paid."""

    fromId: str
    toId: str
    amount: Decimal


@dataclass
class HeldIn:
    accountId: str
    reserves: list[tuple[str, Decimal]]  # category id, balance
    total: Decimal
    movedIn: Decimal  # transfers with the budget's other accounts, net, less what is kept
    reservesFlow: Decimal  # spending and refunds in reserves' categories paid here, signed
    given: Decimal  # landed money given to the reserves here
    balance: Decimal  # the account's
    withdrawals: int  # this month
    limit: int | None
    unassigned: list[Landed] = field(default_factory=list)
    # This month's transfers in from the budget's accounts, each counted for the reserves
    # unless kept as the account's own (S7.10.4).
    transfers: list[tuple[Landed, bool]] = field(default_factory=list)
    # Moves with another account reserves are held in, a cross payment's (S7.10.4).
    between: list[Between] = field(default_factory=list)

    @property
    def backing(self) -> Decimal:
        """What the account holds for its reserves, from its flows alone."""
        return self.movedIn + self.reservesFlow + self.given

    @property
    def short(self) -> Decimal:
        """What the reserves have that the account doesn't hold for them: + short, − ahead."""
        return self.total - self.backing

    @property
    def toMove(self) -> Decimal:
        """What is left to move with its moved-from account once moves between accounts
        reserves are held in are taken out: + to it, − back."""
        mine = sum((x.amount for x in self.between if x.toId == self.accountId), ZERO)
        theirs = sum((x.amount for x in self.between if x.fromId == self.accountId), ZERO)
        return self.short - mine + theirs


def held_in(
    s: Session,
    b: Budget,
    mem: Members,
    tr: Tree,
    every: list[BudgetLine],
    move_rows: list[BudgetMove],
    month: dt.date,
) -> list[HeldIn]:
    """Each account reserves are held in, its transactions since its reserves began classified
    once each (`classify`), and what is to move: the reserves' total less what the account holds
    for them, moved in, paid for them here, and given (S7.10.4, S7.10.5)."""
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
    plans: dict[dt.date, dict[str, BudgetLine]] = {}

    def plan_at(m: dt.date) -> dict[str, BudgetLine]:
        if m not in plans:
            plans[m] = in_force(every, m)
        return plans[m]

    end = month_end(month)
    given_rows = [m for m in move_rows if m.transactionId and m.month <= month]
    by_txn: dict[str, Decimal] = defaultdict(lambda: ZERO)
    own: dict[str, Decimal] = defaultdict(lambda: ZERO)  # kept as the account's own
    for m in given_rows:
        by_txn[m.transactionId] += m.amount
        if m.toCategoryId is None:
            own[m.transactionId] += m.amount
    out: list[HeldIn] = []
    flows_of: dict[str, list[Flow]] = {}
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
        parts = _parts(s, [t.id for t in txns])
        flows = [
            f
            for t in txns
            if t.id not in tr.skip
            for f in classify(
                t, parts.get(t.id, []), others.get(t.transferId or ""), aid, mem, tr, plan_at
            )
        ]
        flows_of[aid] = flows
        moved_in = sum(
            (
                f.amount - (own.get(f.transactionId, ZERO) if f.amount > 0 else ZERO)
                for f in flows
                if f.kind == "moved"
            ),
            ZERO,
        )
        unassigned = []
        for f in flows:
            if f.kind != "landed" or month_of(f.date) != month:
                continue
            free = f.amount - by_txn.get(f.transactionId, ZERO)
            if free > 0:
                t = next(x for x in txns if x.id == f.transactionId)
                unassigned.append(Landed(t.id, t.date, t.payee, f.amount, free))
        moved_this_month = [
            f for f in flows if f.kind == "moved" and f.amount > 0 and month_of(f.date) == month
        ]
        out.append(
            HeldIn(
                accountId=aid,
                reserves=[(r.categoryId, r.balance) for r in rs],
                total=sum((r.balance for r in rs), ZERO),
                movedIn=moved_in,
                reservesFlow=sum((f.amount for f in flows if f.kind == "reserve"), ZERO),
                given=sum(
                    (m.amount for m in given_rows if m.toCategoryId in cats and m.transactionId),
                    ZERO,
                ),
                balance=ledger.load(s, a).balance(end),
                withdrawals=sum(1 for t in txns if t.amount < 0 and month_of(t.date) == month),
                limit=a.withdrawalsAMonth,
                unassigned=unassigned,
                transfers=[
                    (
                        Landed(
                            f.transactionId,
                            f.date,
                            next(x.payee for x in txns if x.id == f.transactionId),
                            f.amount,
                            f.amount - own.get(f.transactionId, ZERO),
                        ),
                        own.get(f.transactionId, ZERO) > 0,
                    )
                    for f in moved_this_month
                ],
            )
        )
    _pair(out, flows_of)
    return out


def _parts(s: Session, ids: list[str]) -> dict[str, list[tuple[str | None, Decimal]]]:
    """Each split transaction's parts, by category."""
    from ..store.entities.accounts import Split

    out: dict[str, list[tuple[str | None, Decimal]]] = defaultdict(list)
    for chunk in range(0, len(ids), 500):
        for sp in s.scalars(
            select(Split).where(
                Split.transactionId.in_(ids[chunk : chunk + 500]), Split.deleted == false()
            )
        ):
            out[sp.transactionId].append((sp.categoryId, sp.amount))
    return out


def _pair(held: list[HeldIn], flows_of: dict[str, list[Flow]]) -> None:
    """A cross payment (1.1 of the budgets walk, S7.10.4): money paid from one account reserves
    are held in for a reserve held in another leaves the payer short and the holder ahead. The
    holder gives it straight to the payer, net of what it has given since, and never more than
    either is out."""
    by_id = {h.accountId: h for h in held}
    for payer, flows in flows_of.items():
        paid: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for f in flows:
            if f.kind == "reserve" and f.reserveIn and f.reserveIn != payer:
                paid[f.reserveIn] -= f.amount
        for holder, amount in paid.items():
            if holder not in by_id:
                continue
            given_back = sum(
                (f.amount for f in flows if f.kind == "moved" and f.otherId == holder), ZERO
            )
            due = min(amount - given_back, by_id[payer].short, -by_id[holder].short)
            if due > 0:
                pair = Between(holder, payer, due)
                by_id[payer].between.append(pair)
                by_id[holder].between.append(pair)
