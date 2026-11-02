"""Budgets (requirements S7.1–S7.4): per category, the planned amount, the actual from
categorised transactions in the budget's accounts, and what remains, with the unspent or
overspent remainder rolled over to the next period where the plan says so.

A plan line holds from its month on; a change to the plan starts a new line in the month it is
made, so past months keep the plan they had. A line marked out takes a category out of the
plan; any amount, 0 included, keeps it in.
Monthly lines compare with the month; yearly ones with the year to date.

Amounts follow the transactions' signs: spending is shown as a positive amount spent, income
as received, savings as saved; a refund lowers its category's spending in the month it lands.
A transaction with splits counts through its splits. Transfer categories never count, nor do
matched transfers between two of the budget's accounts (S1.7). A matched transfer between one
of them and an account the budget doesn't count is money leaving or entering it, counted by
its category, or listed to sort when it has none (S7.3.2); a loan payment counts at the bank as
its loan says, split by the schedule or whole (S1.9.7, S7.3.3). Imports bring posted
transactions only, so nothing pending is counted.
"""

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import false, func, select
from sqlalchemy.orm import Session

from ..store.entities.accounts import Account, Category, Split, Transaction
from ..store.entities.budgets import Budget, BudgetAccount, BudgetLine

ZERO = Decimal(0)
WARN_AT = Decimal("0.9")


def month_of(day: dt.date) -> dt.date:
    return day.replace(day=1)


def add_months(month: dt.date, n: int) -> dt.date:
    y, m = divmod(month.month - 1 + n, 12)
    return dt.date(month.year + y, m + 1, 1)


def month_end(month: dt.date) -> dt.date:
    return add_months(month, 1) - dt.timedelta(days=1)


@dataclass(frozen=True)
class Span:
    """An account counted from its first month to its last, either open-ended."""

    accountId: str
    first: dt.date | None
    last: dt.date | None

    def holds(self, month: dt.date) -> bool:
        return (self.first is None or self.first <= month) and (
            self.last is None or month <= self.last
        )


@dataclass(frozen=True)
class Members:
    """The accounts a budget counts, month by month, for one viewer (S7.1.7, R3.10): a past
    month keeps the accounts it had, a closed account counts up to the month it closed, and a
    deleted one, a correction, counts in none."""

    spans: tuple[Span, ...]

    def at(self, month: dt.date) -> list[str]:
        return list(dict.fromkeys(x.accountId for x in self.spans if x.holds(month)))

    def ever(self) -> list[str]:
        return list(dict.fromkeys(x.accountId for x in self.spans))

    def counts(self, account_id: str, day: dt.date) -> bool:
        m = month_of(day)
        return any(x.accountId == account_id and x.holds(m) for x in self.spans)


def members(s: Session, budget: Budget, viewer: str | None = None) -> Members:
    """The budget's accounts by month, less any loan: a loan's payments are counted at the
    bank. For a receiver (`viewer`), the owner's own accounts, and one shared with the owner
    only if it is shared with them too, so a budget never passes on an account someone else
    shared (S7.1.1)."""
    from .. import access
    from ..loans import TYPES

    rows = s.execute(
        select(BudgetAccount, Account)
        .join(Account, BudgetAccount.accountId == Account.id)
        .where(
            BudgetAccount.budgetId == budget.id,
            BudgetAccount.deleted == false(),
            Account.deleted == false(),
            Account.type.not_in(TYPES),
        )
        .order_by(BudgetAccount.fromMonth)
    ).all()
    if viewer is not None and viewer != budget.ownerId:
        ids = [a.id for _, a in rows]
        theirs = {a.id for a, _ in access.accounts(s, viewer, Account.id.in_(ids))}
        rows = [(m, a) for m, a in rows if a.ownerId == budget.ownerId or a.id in theirs]
    spans = []
    for m, a in rows:
        last = m.untilMonth
        if a.closedOn is not None:
            closed = month_of(a.closedOn)
            last = closed if last is None else min(last, closed)
        spans.append(Span(a.id, m.fromMonth, last))
    return Members(tuple(spans))


def account_ids(s: Session, budget: Budget, viewer: str | None, month: dt.date) -> list[str]:
    """The accounts the budget counts in a month, for a viewer."""
    return members(s, budget, viewer).at(month_of(month))


def active_id(s: Session, user_id: str) -> str | None:
    """The budget a user follows (S7.12), if they can still see it."""
    from .. import access
    from ..store.entities.users import User

    u = s.get(User, user_id)
    if u is None or not u.activeBudgetId:
        return None
    b = s.get(Budget, u.activeBudgetId)
    if b is None or b.deleted:
        return None
    try:
        access.budget(s, user_id, b.id)
    except Exception:  # no longer shared with them
        return None
    return b.id


@dataclass
class Tree:
    """The categories, each with its parent and kind; and, while one budget's figures are
    worked out, the transactions it leaves out (S7.3.5)."""

    by_id: dict[str, Category]
    skip: frozenset[str] = frozenset()

    def key(self, builtin: str) -> str | None:
        """A shipped category's id, by its key."""
        return next((c.id for c in self.by_id.values() if c.builtIn == builtin), None)

    def top(self, cat_id: str) -> Category:
        c = self.by_id[cat_id]
        return self.by_id[c.parentId] if c.parentId and c.parentId in self.by_id else c

    def children(self, cat_id: str) -> list[str]:
        return [c.id for c in self.by_id.values() if c.parentId == cat_id]

    def label(self, cat_id: str) -> str:
        c = self.by_id[cat_id]
        if c.parentId and c.parentId in self.by_id:
            return f"{self.by_id[c.parentId].name} › {c.name}"
        return c.name


def tree(s: Session, budget: Budget | None = None) -> Tree:
    """The categories; for a budget, with the transactions it leaves out."""
    from ..store.entities.budgets import BudgetLeaveOut

    skip = frozenset()
    if budget is not None:
        skip = frozenset(
            s.scalars(
                select(BudgetLeaveOut.transactionId).where(
                    BudgetLeaveOut.budgetId == budget.id, BudgetLeaveOut.deleted == false()
                )
            )
        )
    return Tree(
        {c.id: c for c in s.scalars(select(Category).where(Category.deleted == false()))}, skip
    )


@dataclass
class Moved:
    """A matched transfer between one of the budget's accounts and one it doesn't count, with
    no category to count it by: listed to sort (S7.3.2)."""

    transactionId: str
    date: dt.date
    accountId: str
    otherAccountId: str
    amount: Decimal  # − left the budget, + entered it
    payee: str | None
    otherDeleted: bool = False  # the other account was deleted since


# A loan payment's parts, by the shipped category each counts in when split (S1.9.7).
LOAN_PARTS = {
    "interest": "loans.interest",
    "escrowTax": "loans.escrow",
    "escrowInsurance": "loans.escrow",
    "pmi": "loans.pmi",
    "fees": "loans.fees",
    "principal": "loans.principal",
}


def amounts(
    s: Session,
    accounts: list[str],
    start: dt.date,
    end: dt.date,
    moved: list[Moved] | None = None,
    tr: Tree | None = None,
) -> dict[str, Decimal]:
    """The signed total per category over the accounts, between two dates inclusive. Transfers
    that leave or enter the accounts with no category to count them by go to `moved`."""
    if not accounts:
        return {}
    tr = tr or tree(s)
    inside = set(accounts)
    out: dict[str, Decimal] = defaultdict(lambda: ZERO)
    txns = s.scalars(
        select(Transaction).where(
            Transaction.accountId.in_(accounts),
            Transaction.deleted == false(),
            Transaction.date >= start,
            Transaction.date <= end,
        )
    ).all()
    others = other_halves(s, [t.transferId for t in txns if t.transferId])
    ids = [t.id for t in txns]
    splits: dict[str, list[Split]] = defaultdict(list)
    for chunk in range(0, len(ids), 500):
        for sp in s.scalars(
            select(Split).where(
                Split.transactionId.in_(ids[chunk : chunk + 500]), Split.deleted == false()
            )
        ):
            splits[sp.transactionId].append(sp)
    from .. import reimbursements

    # Spending awaited or paid back isn't counted, nor the part of a deposit that paid it (S2.9).
    paying = reimbursements.paired_out(s, ids)
    loans_seen: dict[str, dict] = {}
    for t in txns:
        if t.id in tr.skip:
            continue  # left out of this budget (S7.3.5)
        other = others.get(t.transferId) if t.transferId else None
        if other is not None and other.accountId in inside:
            continue  # between two of the budget's accounts: no money moved in or out
        if other is not None and other.type in _loan_types() and not other.deleted:
            loan_account = s.get(Account, other.accountId)
            if loan_account is not None:
                _count_loan_payment(s, tr, out, t, (other, loan_account), loans_seen)
                continue
            # A loan the viewer can't see counts whole, so its split never shows (S7.1.1).
            cat = t.categoryId if t.categoryId and _counts(tr, t.categoryId) else tr.key("loans")
            if cat:
                out[cat] += t.amount
                continue
        parts = splits.get(t.id)
        counted = False
        if parts:
            for sp in parts:
                if sp.categoryId and _counts(tr, sp.categoryId):
                    out[sp.categoryId] += _counted(sp.amount, sp.reimbursable)
                    counted = True
        elif t.categoryId and _counts(tr, t.categoryId):
            out[t.categoryId] += _counted(t.amount, t.reimbursable) - paying.get(t.id, ZERO)
            counted = True
        if other is not None and not counted and other.type == "cash" and tr.key("cash"):
            # Cash taken out to a cash account the budget doesn't count is spent (S7.3.2).
            out[tr.key("cash")] += t.amount
            counted = True
        if other is not None and not counted and moved is not None:
            moved.append(
                Moved(t.id, t.date, t.accountId, other.accountId, t.amount, t.payee, other.deleted)
            )
    return dict(out)


def _counted(amount: Decimal, reimbursable: Decimal | None) -> Decimal:
    """Spending less what is to be paid back of it."""
    if reimbursable and amount < 0:
        return amount + min(reimbursable, -amount)
    return amount


def _counts(tr: Tree, cat_id: str) -> bool:
    c = tr.by_id.get(cat_id)
    return c is not None and c.kind != "transfer"


def _loan_types() -> tuple[str, ...]:
    from ..loans import TYPES

    return TYPES


@dataclass(frozen=True)
class OtherHalf:
    """A matched transfer's other half: which account it is in, whatever the viewer can see,
    and whether that account was deleted since (R3.10)."""

    id: str
    accountId: str
    type: str
    deleted: bool


def other_halves(s: Session, transfer_ids: list[str]) -> dict[str, OtherHalf]:
    """Each matched transfer's other half, by its id. Read as the server, as columns only: the
    figures need to know whether the money stayed in the budget's accounts, deleted or hidden
    from the viewer or not, and the viewer is shown nothing of that account but this (S7.1.1).
    A half deleted on its own is no half: the transfer is money in or out."""
    from ..store.scoping import unscoped

    out: dict[str, OtherHalf] = {}
    for chunk in range(0, len(transfer_ids), 500):
        stmt = (
            select(Transaction.id, Transaction.accountId, Account.type, Account.deletedAt)
            .join(Account, Account.id == Transaction.accountId)
            .where(
                Transaction.id.in_(transfer_ids[chunk : chunk + 500]),
                Transaction.deletedAt.is_(None),
            )
        )
        for tid, aid, kind, gone in s.execute(unscoped(stmt, "a budget's transfers")):
            out[tid] = OtherHalf(tid, aid, kind, gone is not None)
    return out


def _count_loan_payment(s, tr, out, t, other, loans_seen) -> None:
    """A payment to a loan, as the loan says: split by the schedule into its parts' categories,
    or whole in one (S1.9.7). `t` is the bank's half, `other` the loan's."""
    from .. import loans

    o, loan_account = other
    if loan_account.id not in loans_seen:
        row = loans.loan_of(s, loan_account)
        payments = {p.transactionId: p for p in loans.history(s, loan_account)[0]}
        loans_seen[loan_account.id] = {"row": row, "payments": payments}
    seen = loans_seen[loan_account.id]
    row = seen["row"]
    if row is not None and row.budgetCounting == "whole":
        cat = row.budgetCategoryId or tr.key("loans")
        if cat:
            out[cat] += t.amount
        return
    p = seen["payments"].get(o.id)
    if p is None:
        return
    for part, key in LOAN_PARTS.items():
        amount = getattr(p, part)
        cat = tr.key(key)
        if amount and cat:
            out[cat] -= amount
    # What the schedule didn't place (a payment larger than the loan's balance) counts whole.
    rest = -t.amount - sum((getattr(p, part) for part in LOAN_PARTS), ZERO)
    if rest and tr.key("loans"):
        out[tr.key("loans")] -= rest


def uncategorised(s: Session, accounts: list[str], start: dt.date, end: dt.date) -> int:
    if not accounts:
        return 0
    return s.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(
            Transaction.accountId.in_(accounts),
            Transaction.deleted == false(),
            Transaction.transferId.is_(None),
            Transaction.categoryId.is_(None),
            Transaction.instrumentId.is_(None),
            Transaction.date >= start,
            Transaction.date <= end,
        )
    )


def lines(s: Session, budget: Budget) -> list[BudgetLine]:
    return list(
        s.scalars(
            select(BudgetLine)
            .where(BudgetLine.budgetId == budget.id, BudgetLine.deleted == false())
            .order_by(BudgetLine.fromMonth)
        )
    )


def in_force(all_lines: list[BudgetLine], month: dt.date) -> dict[str, BudgetLine]:
    """Per category, the line that holds in a month: none once a line takes it out of the plan
    (S7.1.2). A line of 0 is in the plan and puts nothing in."""
    found: dict[str, BudgetLine] = {}
    for ln in all_lines:
        if ln.fromMonth <= month:
            found[ln.categoryId] = ln
    return {k: v for k, v in found.items() if not v.out}


@dataclass
class Row:
    """A line's month, the same parts for every kind of line (S7.3.11): what it carried in, put
    in and was moved, spent, and what remains, always remaining = carried + putIn + moved −
    actual; `planned` is what was available, carried + putIn + moved."""

    categoryId: str
    label: str
    kind: str
    cadence: str
    rollover: bool
    planned: Decimal  # available: carried + putIn + moved
    carried: Decimal  # what came in from the month before
    actual: Decimal  # spent, or received for income
    remaining: Decimal
    state: str  # under, near (90% or more), over
    fromPlan: str | None = None  # gifts or giving: planned by those plans (S7.3.6)
    overspend: str = "carry"
    projectionId: str | None = None
    projection: tuple[str, Decimal] | None = None  # an active projection's name and monthly
    moved: Decimal = ZERO  # moves in, less moves out, this month (S7.11)
    target: Decimal | None = None  # a reserve's (S7.10)
    heldInId: str | None = None
    balance: Decimal | None = None  # a reserve's, at the month's end
    putIn: Decimal = ZERO  # this month's own: its plan, what was assigned, a reserve's deposit


@dataclass
class Month:
    month: dt.date
    rows: list[Row]
    unplanned: list[tuple[str, str, Decimal]]  # (categoryId, label, spent) not in the plan
    income: Decimal
    expectedIncome: Decimal
    spent: Decimal
    saved: Decimal
    moved: list[Moved]
    # The Spent card's (S7.3): what the monthly spending lines had available, reserves included,
    # and what they and the spending outside the plan leave; spending against yearly lines is
    # compared with their year, so it is apart.
    available: Decimal
    left: Decimal
    yearlySpent: Decimal
    uncategorised: int
    daysLeft: int
    toBudget: Decimal | None = None  # an envelope budget's (S7.13)
    assigned: Decimal | None = None  # by its plan this month
    assignedByMoves: Decimal | None = None  # from To Budget by moves
    cards: list = field(default_factory=list)  # its cards' payment lines


def line_of(tree_: Tree, planned: set[str] | dict, cat_id: str) -> str | None:
    """The line a category's money counts against (S7.1.2): its own, else its parent's, else
    none (not in the plan). Every transaction counts against one line at most, so no spending
    is counted twice, in either method."""
    if cat_id in planned:
        return cat_id
    c = tree_.by_id.get(cat_id)
    if c is not None and c.parentId and c.parentId in planned:
        return c.parentId
    return None


def _actual(
    tree_: Tree, totals: dict[str, Decimal], cat_id: str, planned: set[str] | dict
) -> Decimal:
    """What a line is compared with: the money of the categories that count against it
    (`line_of`), spending and saving as positive."""
    c = tree_.by_id[cat_id]
    raw = sum((v for k, v in totals.items() if line_of(tree_, planned, k) == cat_id), ZERO)
    return -raw if c.kind in ("expense", "savings") else raw


def _state(planned: Decimal, actual: Decimal) -> str:
    if planned <= 0:
        return "over" if actual > 0 else "under"
    if actual > planned:
        return "over"
    return "near" if actual >= planned * WARN_AT else "under"


def month_view(
    s: Session, budget: Budget, month: dt.date, today: dt.date, viewer: str | None = None
) -> Month:
    """A month's figures, kept once worked out until what they come from changes (S7.3.10)."""
    from . import cache

    return cache.month(
        s, (budget.id, month, today, viewer), lambda: _month_view(s, budget, month, today, viewer)
    )


def _month_view(
    s: Session, budget: Budget, month: dt.date, today: dt.date, viewer: str | None = None
) -> Month:
    from . import plan, reserves

    tr = tree(s, budget)
    mem = members(s, budget, viewer)
    accts = mem.at(month)
    every = lines(s, budget)
    now = in_force(every, month)
    move_rows = reserves.moves(s, budget)
    moved_by = reserves.net_moves(move_rows)
    env = None
    # An envelope budget has no To Budget before the month it starts in (S7.13.1).
    if budget.method == "envelope" and month >= (budget.startMonth or month):
        from . import envelope

        env = envelope.month(s, budget, mem, tr, every, move_rows, month)
    moved: list[Moved] = []
    totals = amounts(s, accts, month, month_end(month), moved, tr)
    year_start = month.replace(month=1)
    ytd = _summed(_monthly(s, mem, year_start, month, tr))
    rows: list[Row] = []
    planned_cats = set(now)
    # Gifts and Giving are planned by the owner's gift and giving plans, a year at a time.
    elsewhere = {
        k: v
        for k, v in plan.planned_elsewhere(s, budget, tr, month.year).items()
        if k not in now and k in tr.by_id
    }
    # The lines that hold this month, each category's money counted against one (S7.1.2).
    lines_now = set(now) | set(elsewhere)
    for cat_id, ln in now.items():
        if cat_id not in tr.by_id:
            continue
        kind = tr.by_id[cat_id].kind
        mv = moved_by.get((month, cat_id), ZERO)
        e = env.envelopes.get(cat_id) if env else None
        if e is not None:
            available = e.start + e.assigned + e.moved
            rows.append(
                Row(
                    categoryId=cat_id,
                    label=tr.label(cat_id),
                    kind=kind,
                    cadence=ln.cadence,
                    rollover=True,
                    planned=available,
                    carried=e.start,
                    actual=e.spent,
                    remaining=e.balance,
                    state=_state(available, e.spent)
                    if ln.target is None or e.balance < ln.target
                    else "funded",
                    overspend=ln.overspend,
                    moved=e.moved,
                    target=ln.target,
                    heldInId=ln.heldInId,
                    balance=e.balance if ln.target is not None else None,
                    putIn=e.assigned,
                    projectionId=ln.projectionId,
                    projection=plan.monthly_contribution(s, ln.projectionId)
                    if ln.projectionId
                    else None,
                )
            )
            continue
        if ln.target is not None and ln.cadence == "month":
            r = reserves.reserve(s, tr, mem, every, moved_by, cat_id, month)
            if r is not None:
                rows.append(
                    Row(
                        categoryId=cat_id,
                        label=tr.label(cat_id),
                        kind=kind,
                        cadence="month",
                        rollover=True,
                        planned=r.start + r.putIn + mv,
                        carried=r.start,
                        actual=r.spent,
                        remaining=r.balance,
                        state="funded" if r.funded else "over" if r.balance < 0 else "under",
                        moved=mv,
                        target=r.target,
                        heldInId=r.heldInId,
                        balance=r.balance,
                        putIn=r.putIn,
                    )
                )
                continue
        if ln.cadence == "year":
            # Compared with the year to date, its moves the year's so far too.
            mv = sum(
                (v for (m, k), v in moved_by.items() if k == cat_id and year_start <= m <= month),
                ZERO,
            )
            planned, carried = ln.amount + mv, ZERO
            actual = _actual(tr, ytd, cat_id, lines_now)
        else:
            carried = _carry(s, tr, mem, every, cat_id, month, moved_by) if ln.rollover else ZERO
            planned = ln.amount + carried + mv
            actual = _actual(tr, totals, cat_id, lines_now)
        rows.append(
            Row(
                categoryId=cat_id,
                label=tr.label(cat_id),
                kind=kind,
                cadence=ln.cadence,
                rollover=ln.rollover,
                planned=planned,
                carried=carried,
                actual=actual,
                remaining=planned - actual,
                state=_state(planned, actual) if kind == "expense" else "under",
                overspend=ln.overspend,
                moved=mv,
                putIn=ln.amount,
                projectionId=ln.projectionId,
                projection=plan.monthly_contribution(s, ln.projectionId)
                if ln.projectionId
                else None,
            )
        )
    for cat_id, amount in elsewhere.items():
        planned_cats.add(cat_id)
        actual = _actual(tr, ytd, cat_id, lines_now)
        rows.append(
            Row(
                categoryId=cat_id,
                label=tr.label(cat_id),
                kind=tr.by_id[cat_id].kind,
                cadence="year",
                rollover=False,
                planned=amount,
                carried=ZERO,
                actual=actual,
                remaining=amount - actual,
                state=_state(amount, actual),
                fromPlan=tr.by_id[cat_id].builtIn,
                putIn=amount,
            )
        )
    rows.sort(key=lambda r: (r.kind != "income", r.label))
    # Spending counted against no line: no plan of its own, nor under a planned parent.
    unplanned: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for cid, amt in totals.items():
        c = tr.by_id.get(cid)
        if c is None or c.kind != "expense" or line_of(tr, lines_now, cid) is not None:
            continue
        unplanned[cid] -= amt
    income = sum((amt for cid, amt in totals.items() if _kind(tr, cid) == "income"), ZERO)
    spent = -sum((amt for cid, amt in totals.items() if _kind(tr, cid) == "expense"), ZERO)
    saved = -sum((amt for cid, amt in totals.items() if _kind(tr, cid) == "savings"), ZERO)
    end = month_end(month)
    monthly = [r for r in rows if r.kind == "expense" and r.cadence == "month"]
    unplanned_rows = sorted(
        ((cid, tr.label(cid), amt) for cid, amt in unplanned.items() if amt != 0),
        key=lambda x: -x[2],
    )
    return Month(
        month=month,
        rows=rows,
        unplanned=unplanned_rows,
        income=income,
        expectedIncome=sum((r.planned for r in rows if r.kind == "income"), ZERO),
        spent=spent,
        saved=saved,
        moved=sorted(moved, key=lambda x: (x.date, x.transactionId)),
        available=sum((r.planned for r in monthly), ZERO),
        left=sum((r.remaining for r in monthly), ZERO) - sum((x[2] for x in unplanned_rows), ZERO),
        yearlySpent=sum(
            (
                _actual(tr, totals, r.categoryId, lines_now)
                for r in rows
                if r.kind == "expense" and r.cadence == "year"
            ),
            ZERO,
        ),
        uncategorised=uncategorised(s, accts, month, end),
        toBudget=env.toBudget if env else None,
        assigned=env.assigned if env else None,
        assignedByMoves=env.movedIn if env else None,
        cards=env.cards if env else [],
        daysLeft=max(0, (end - today).days + 1) if month <= today <= end else 0,
    )


def _kind(tr: Tree, cat_id: str) -> str | None:
    c = tr.by_id.get(cat_id)
    return c.kind if c else None


def _carry(
    s: Session,
    tr: Tree,
    mem: Members,
    every: list[BudgetLine],
    cat_id: str,
    month: dt.date,
    moved: dict | None = None,
) -> Decimal:
    """What rolls into a month: each earlier month's plan and moves less its actual, carried on
    while the category's plan rolls over."""
    moved = moved or {}
    mine = [ln for ln in every if ln.categoryId == cat_id]
    if not mine:
        return ZERO
    start = mine[0].fromMonth
    if start >= month:
        return ZERO
    totals = _monthly(s, mem, start, add_months(month, -1), tr)
    carry = ZERO
    m = start
    while m < month:
        ln = in_force(mine, m).get(cat_id)
        if ln is None or not ln.rollover or ln.cadence != "month":
            carry = ZERO
        else:
            carry = (
                ln.amount
                + carry
                + moved.get((m, cat_id), ZERO)
                - _actual(tr, totals.get(m, {}), cat_id, in_force(every, m))
            )
        m = add_months(m, 1)
    return carry


def _monthly(
    s: Session, mem: Members, first: dt.date, last: dt.date, tr: Tree | None = None
) -> dict[dt.date, dict[str, Decimal]]:
    """Each month's totals over the accounts the budget counted that month."""
    out: dict[dt.date, dict[str, Decimal]] = {}
    m = first
    while m <= last:
        out[m] = amounts(s, mem.at(m), m, month_end(m), tr=tr)
        m = add_months(m, 1)
    return out


def _summed(by_month: dict[dt.date, dict[str, Decimal]]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for totals in by_month.values():
        for k, v in totals.items():
            out[k] += v
    return dict(out)


# ---------- the other tabs (S7.4) ----------


def cash_flow(s: Session, budget: Budget, month: dt.date, viewer: str | None = None) -> dict:
    """Income by category into spending by top-level category, and what was left: the
    month's Sankey."""
    tr = tree(s, budget)
    totals = amounts(s, account_ids(s, budget, viewer, month), month, month_end(month), tr=tr)
    sources: dict[str, Decimal] = defaultdict(lambda: ZERO)
    uses: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for cid, amt in totals.items():
        c = tr.by_id.get(cid)
        if c is None:
            continue
        if c.kind == "income":
            sources[c.name] += amt
        elif c.kind in ("expense", "savings"):
            uses[tr.top(cid).name] -= amt
    income = sum(sources.values(), ZERO)
    spending = sum(uses.values(), ZERO)
    if income > spending:
        uses["Saved"] = income - spending
    return {
        "sources": sorted(((k, v) for k, v in sources.items() if v > 0), key=lambda x: -x[1]),
        "uses": sorted(((k, v) for k, v in uses.items() if v > 0), key=lambda x: -x[1]),
        "income": income,
        "spending": spending,
    }


def trends(
    s: Session,
    budget: Budget,
    last_month: dt.date,
    category: str | None,
    months: int = 12,
    viewer: str | None = None,
) -> list[tuple[dt.date, Decimal, Decimal]]:
    """For each of the last months: planned and actual spending, for one category (with its
    children) or every expense category."""
    tr = tree(s, budget)
    mem = members(s, budget, viewer)
    every = lines(s, budget)
    out = []
    first = add_months(last_month, -(months - 1))
    totals = _monthly(s, mem, first, last_month, tr)
    for i in range(months):
        m = add_months(first, i)
        plan = in_force(every, m)
        if category:
            ln = plan.get(category)
            planned = ln.amount if ln and ln.cadence == "month" else ZERO
            # The category's own money, and its children's that have no line that month.
            mine = set(plan) | {category}
            actual = _actual(tr, totals[m], category, mine) if category in tr.by_id else ZERO
        else:
            planned = sum(
                (
                    ln.amount
                    for cid, ln in plan.items()
                    if ln.cadence == "month" and _kind(tr, cid) == "expense"
                ),
                ZERO,
            )
            actual = -sum(
                (amt for cid, amt in totals[m].items() if _kind(tr, cid) == "expense"), ZERO
            )
        out.append((m, planned, actual))
    return out
