"""Envelope budgets (requirements S7.13): the money in the budget's accounts is handed out to
categories each month until none is left to hand out.

- **To Budget** is the cash in the budget's accounts, less what its categories hold and what is
  set aside for its cards. Income adds to the cash, spending takes from cash and category
  alike, so only assigning money moves it out of To Budget.
- **A category's balance** carries from month to month: what it held, plus what the plan and
  moves assign, less what is spent. Overspent at the month's end, it is carried negative, or
  set back to nothing when its line takes the shortfall from the next month's To Budget.
- **A card's payment line**: a charge from a category with money in it moves that much from the
  category to the line, and a payment to the card takes from it. A charge beyond what its
  category held leaves the category at nothing and is owed, not backed: debt no category set
  aside for, shown on the card until a move into its line covers it.
- A yearly line assigns a twelfth of its amount each month.
"""

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
    add_months,
    amounts,
    in_force,
    month_end,
    other_halves,
)

CARD = "credit-card"


@dataclass
class Card:
    accountId: str
    name: str
    setAside: Decimal  # the payment line
    owed: Decimal  # what the card owes at the month's end
    paid: Decimal  # payments to it this month

    @property
    def notBacked(self) -> Decimal:
        return max(self.owed - self.setAside, ZERO)


@dataclass
class Envelope:
    categoryId: str
    start: Decimal  # the balance the month began with
    assigned: Decimal  # by the plan
    moved: Decimal  # by moves, To Budget's among them
    spent: Decimal
    # Charged to a card beyond what the envelope held: owed on the card, not backed, and never
    # out of the envelope, which stops at nothing (S7.13.2).
    unbacked: Decimal = ZERO

    @property
    def balance(self) -> Decimal:
        return self.start + self.assigned + self.moved - self.spent


@dataclass
class EnvelopeMonth:
    month: dt.date
    toBudget: Decimal
    assigned: Decimal  # by the plan, this month
    movedIn: Decimal  # from To Budget by moves, this month
    envelopes: dict[str, Envelope] = field(default_factory=dict)
    cards: list[Card] = field(default_factory=list)


def _cash(s: Session, accounts: list[Account], day: dt.date) -> Decimal:
    from ..store.repos import ledger

    return sum((ledger.load(s, a).balance(day) for a in accounts), ZERO)


def month(
    s: Session,
    b: Budget,
    mem: Members,
    tr: Tree,
    every: list[BudgetLine],
    moves: list[BudgetMove],
    target: dt.date,
) -> EnvelopeMonth:
    every_account = list(s.scalars(select(Account).where(Account.id.in_(mem.ever()))))
    first = b.startMonth or (every[0].fromMonth if every else target)
    first = min(first, target)
    bal: dict[str, Decimal] = defaultdict(lambda: ZERO)
    line: dict[str, Decimal] = defaultdict(lambda: ZERO)
    m = first
    out = None
    while m <= target:
        # The accounts the budget counted that month (S7.1.7).
        now = set(mem.at(m))
        rows = [a for a in every_account if a.id in now]
        cards = [a for a in rows if a.type == CARD]
        cash_accts = [a for a in rows if a.type != CARD]
        cash_ids, card_ids = [a.id for a in cash_accts], [a.id for a in cards]
        plan = in_force(every, m)
        cash_spend = amounts(s, cash_ids, m, month_end(m), tr=tr)
        per_card = {cid: amounts(s, [cid], m, month_end(m), tr=tr) for cid in card_ids}
        mv: dict[str, Decimal] = defaultdict(lambda: ZERO)
        to_card: dict[str, Decimal] = defaultdict(lambda: ZERO)
        from_tb = ZERO
        for x in moves:
            if x.month != m or x.transactionId:
                continue
            if x.toCategoryId:
                mv[x.toCategoryId] += x.amount
            if x.fromCategoryId:
                mv[x.fromCategoryId] -= x.amount
            if x.cardId:
                to_card[x.cardId] += x.amount
            if x.fromCategoryId is None:
                from_tb += x.amount
        envs: dict[str, Envelope] = {}
        assigned_total = ZERO
        for cat_id, ln in plan.items():
            if cat_id not in tr.by_id or tr.by_id[cat_id].kind == "income":
                continue
            assigned = (
                ln.amount if ln.cadence == "month" else (ln.amount / 12).quantize(Decimal("0.01"))
            )
            start = bal[cat_id]
            if ln.target is not None:  # a reserve assigns no more than reaches its target
                assigned = min(assigned, max(ln.target - start, ZERO))
            assigned_total += assigned
            available = start + assigned + mv[cat_id] - _actual(tr, cash_spend, cat_id, plan)
            charged = unbacked = ZERO
            for cid in card_ids:
                charge = _actual(tr, per_card[cid], cat_id, plan)
                covered = min(max(charge, ZERO), max(available - charged, ZERO))
                if charge < 0:  # a refund to the card comes back to the category
                    covered = charge
                line[cid] += covered
                charged += covered
                unbacked += charge - covered
            spent = _actual(tr, cash_spend, cat_id, plan) + charged
            env = Envelope(cat_id, start, assigned, mv[cat_id], spent, unbacked)
            envs[cat_id] = env
            end = env.balance
            if end < 0 and ln.overspend == "next":
                end = ZERO  # the shortfall comes from next month's To Budget
            bal[cat_id] = end
        # Categories that left the plan keep no balance.
        for cat_id in list(bal):
            if cat_id not in plan:
                bal[cat_id] = ZERO
        payments = _payments(s, card_ids, now, m)
        card_rows = []
        for a in cards:
            line[a.id] = max(line[a.id] + to_card[a.id] - payments.get(a.id, ZERO), ZERO)
            from ..store.repos import ledger

            card_rows.append(
                Card(
                    accountId=a.id,
                    name=a.name,
                    setAside=line[a.id],
                    owed=-ledger.load(s, a).balance(month_end(m)),
                    paid=payments.get(a.id, ZERO),
                )
            )
        held = sum(bal.values(), ZERO)
        to_budget = _cash(s, cash_accts, month_end(m)) - held - sum(line.values(), ZERO)
        if m == target:
            out = EnvelopeMonth(m, to_budget, assigned_total, from_tb, envs, card_rows)
        m = add_months(m, 1)
    return out or EnvelopeMonth(target, ZERO, ZERO, ZERO)


def _payments(s: Session, card_ids: list[str], inside: set[str], m: dt.date) -> dict[str, Decimal]:
    """Payments to each card in the month: transfers in from the budget's other accounts."""
    if not card_ids:
        return {}
    ins = s.scalars(
        select(Transaction).where(
            Transaction.accountId.in_(card_ids),
            Transaction.deleted == false(),
            Transaction.transferId.is_not(None),
            Transaction.amount > 0,
            Transaction.date >= m,
            Transaction.date <= month_end(m),
        )
    ).all()
    others = {k: o.accountId for k, o in other_halves(s, [t.transferId for t in ins]).items()}
    out: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for t in ins:
        if others.get(t.transferId) in inside:
            out[t.accountId] += t.amount
    return dict(out)
