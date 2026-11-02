"""A budget's plan beyond its own lines (requirements S7.1.5, S7.1.6, S7.2.1, S7.3.6): where
its money comes from, the Gifts and Giving lines its owner's plans set, a savings line's
projection, and a plan estimated from history."""

import datetime as dt
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from ..store.entities.accounts import Account, Transaction
from ..store.entities.budgets import Budget, BudgetAccount
from . import ZERO, Tree, add_months, amounts, month_end, month_of, recurring

YEAR = dt.timedelta(days=365)
CARDS = ("credit-card",)


# ---------- where money comes from (S7.1.6) ----------


@dataclass
class Role:
    accountId: str
    paidFromId: str | None  # a card's paying account
    paidFromLearned: bool  # from its payments, not chosen
    movedFromId: str | None  # where money for reserves held here moves from
    movedFromProposed: bool


def _transfers_in(s: Session, account_id: str, since: dt.date) -> Counter:
    """Where an account's matched transfers in came from, by account, over a year."""
    ins = s.scalars(
        select(Transaction).where(
            Transaction.accountId == account_id,
            Transaction.amount > 0,
            Transaction.transferId.is_not(None),
            Transaction.deleted == false(),
            Transaction.date >= since,
        )
    ).all()
    out: Counter = Counter()
    for o in s.scalars(select(Transaction).where(Transaction.id.in_([t.transferId for t in ins]))):
        out[o.accountId] += 1
    return out


def main_account(s: Session, accounts: list[str], today: dt.date) -> str | None:
    """The budget's account receiving the most income over a year: the default until its
    history says otherwise."""
    from . import tree

    tr = tree(s)
    best, most = None, ZERO
    for a in accounts:
        got = sum(
            (
                amt
                for cid, amt in amounts(s, [a], today - YEAR, today, tr=tr).items()
                if tr.by_id[cid].kind == "income"
            ),
            ZERO,
        )
        if got > most:
            best, most = a, got
    return best


def roles(s: Session, b: Budget, accounts: list[Account], today: dt.date) -> list[Role]:
    """Each card's paying account, learned from its payments unless one was chosen; and for
    each other account, where money moved into it comes from, proposed from its transfers in.
    Nothing to set while the history is clear."""
    ids = [a.id for a in accounts]
    chosen = {
        m.accountId: m
        for m in s.scalars(
            select(BudgetAccount)
            .where(BudgetAccount.budgetId == b.id, BudgetAccount.deleted == false())
            # An account counted more than once: its latest record holds its roles.
            .order_by(BudgetAccount.fromMonth)
        )
    }
    fallback = main_account(s, ids, today)
    out = []
    for a in accounts:
        came = _transfers_in(s, a.id, today - YEAR)
        inside = [(k, n) for k, n in came.most_common() if k in ids and k != a.id]
        learned = inside[0][0] if inside else (fallback if fallback != a.id else None)
        m = chosen.get(a.id)
        if a.type in CARDS:
            pick = m.paidFromId if m and m.paidFromId else learned
            out.append(Role(a.id, pick, not (m and m.paidFromId), None, False))
        else:
            pick = m.movedFromId if m and m.movedFromId else learned
            out.append(Role(a.id, None, False, pick, not (m and m.movedFromId)))
    return out


# ---------- Gifts and Giving (S7.3.6) ----------


def planned_elsewhere(s: Session, b: Budget, tr: Tree, year: int) -> dict[str, Decimal]:
    """The yearly amounts the owner's gift plans and giving plan set, by category id."""
    from .. import giving
    from ..gifts import occasions_of, visible_plans

    out: dict[str, Decimal] = {}
    gifts_cat, giving_cat = tr.key("gifts"), tr.key("giving")
    if gifts_cat:
        total, any_plan = ZERO, False
        plans = [x for x in visible_plans(s, b.ownerId) if x.plan.ownerId == b.ownerId]
        occs = occasions_of(s, [x.plan.id for x in plans])
        for x in plans:
            any_plan = True
            if x.plan.giftBudget:
                total += x.plan.giftBudget
            else:
                total += sum((o.budget or ZERO for o in occs.get(x.plan.id, [])), ZERO)
        if any_plan:
            out[gifts_cat] = total
    if giving_cat:
        plan, _ = giving.plan_for(s, b.ownerId, year)
        if plan is not None and plan.ownerId == b.ownerId:
            earned = giving.income(s, plan, giving.givers(s, plan, b.ownerId), year)
            out[giving_cat] = giving.target(plan, earned)
    return out


# ---------- a savings line's projection (S7.2.1) ----------


def monthly_contribution(s: Session, projection_id: str) -> tuple[str, Decimal] | None:
    """An active projection's name and what it assumes is put in a month."""
    from ..store.entities.projections import Projection

    p = s.get(Projection, projection_id)
    if p is None or p.deleted or not p.active:
        return None
    inputs = json.loads(p.inputs or "{}")
    if p.goal == "retirement":
        yearly = Decimal(str((inputs.get("contribution") or {}).get("amount") or 0))
        monthly = yearly / 12
    else:
        monthly = Decimal(str(inputs.get("monthly") or 0))
    return p.name, monthly.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


# ---------- a plan from history (S7.1.5) ----------


@dataclass
class Proposal:
    categoryId: str
    amount: Decimal  # a month's, or a year's for a yearly line
    cadence: str
    source: str  # history, recurring
    detail: str
    target: Decimal | None = None  # a yearly cost proposed as a reserve


def estimate(
    s: Session, b: Budget, accounts: list[str], tr: Tree, months: int, today: dt.date
) -> list[Proposal]:
    """A line per category from its average over the last complete months: monthly where it
    was spent in most of them, yearly otherwise; and the recurring transactions as lines of
    their own, a yearly one as a reserve when the budget has reserves. Gifts and Giving are
    planned by their own plans, so never proposed."""
    last = add_months(month_of(today), -1)
    first = add_months(last, -(months - 1))
    per: dict[str, list[Decimal]] = defaultdict(list)
    for i in range(months):
        m = add_months(first, i)
        for cid, amt in amounts(s, accounts, m, month_end(m), tr=tr).items():
            per[cid].append(amt)
    skip = {tr.key("gifts"), tr.key("giving")}
    out: dict[str, Proposal] = {}
    for cid, seen in per.items():
        c = tr.by_id.get(cid)
        if c is None or c.kind == "transfer" or cid in skip:
            continue
        total = sum(seen, ZERO)
        if c.kind in ("expense", "savings"):
            total = -total
        if total <= 0:
            continue
        spent_in = sum(1 for x in seen if x)
        if spent_in * 2 > months:
            amount, cadence = (total / months), "month"
            detail = f"spent in {spent_in} of {months} months"
        else:
            amount, cadence = (total * 12 / months), "year"
            detail = f"spent in {spent_in} of {months} months"
        out[cid] = Proposal(cid, _round(amount), cadence, "history", detail)
    txns = s.scalars(
        select(Transaction).where(
            Transaction.accountId.in_(accounts),
            Transaction.deleted == false(),
            # Three years back: a yearly bill needs three payments to be a series.
            Transaction.date >= today - dt.timedelta(days=3 * 366 + 15),
        )
    ).all()
    for x in recurring.detect(txns, today):
        cid = x.categoryId
        c = tr.by_id.get(cid) if cid else None
        if c is None or c.kind == "transfer" or cid in skip:
            continue
        per_year = {"week": 52, "2 weeks": 26, "twice a month": 24, "month": 12}.get(x.every)
        if per_year:
            continue  # a monthly series is in its category's average already
        yearly = abs(x.usual) * (4 if x.every == "quarter" else 1)
        out[cid] = Proposal(
            cid,
            _round(yearly / 12 if b.reserves else yearly),
            "month" if b.reserves else "year",
            "recurring",
            f"recurring: {x.payee}, every {x.every}",
            target=_round(yearly) if b.reserves else None,
        )
    return sorted(
        out.values(),
        key=lambda p: (tr.by_id[p.categoryId].kind != "income", tr.label(p.categoryId)),
    )


def _round(x: Decimal) -> Decimal:
    return x.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
