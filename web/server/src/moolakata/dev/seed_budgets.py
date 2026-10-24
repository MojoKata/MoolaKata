"""Dev mode's budget (requirements S17.7): Alice's household budget over her banking, shared
with the Household group at write, planned from a year ago with one change since; and a hotel
her employer pays back, with the deposit that may pay it (S2.9)."""

import datetime as dt
from decimal import Decimal as D

from sqlalchemy import select

from .. import clock, ids
from ..budgets import add_months, month_of
from ..store.entities.accounts import Account, Category, Transaction
from ..store.entities.budgets import Budget, BudgetAccount, BudgetLine
from ..store.entities.sharing import Share
from ..store.entities.users import Group


def seed_budgets(s, people: dict) -> None:
    alice = people["alice"]
    acct = {a.name: a for a in s.scalars(select(Account))}
    cat = {c.builtIn: c for c in s.scalars(select(Category).where(Category.builtIn.is_not(None)))}
    household = s.scalars(select(Group).where(Group.name == "Household")).one()
    now = clock.now()
    b = Budget(id=ids.new_id("Bdgt"), ownerId=alice.id, name="Household")
    s.add(b)
    s.flush()
    for name in ("Everyday checking", "Emergency savings", "Travel Visa"):
        s.add(BudgetAccount(budgetId=b.id, accountId=acct[name].id, createdAt=now))
    start = add_months(month_of(clock.today()), -11)
    plan = [
        ("income.salary", "5720.00", "month", False),
        ("housing.rent", "2150.00", "month", False),
        ("housing.utilities", "160.00", "month", True),
        ("food", "520.00", "month", False),
        ("transport.fuel", "120.00", "month", False),
        ("personal", "200.00", "month", False),
        ("travel", "2400.00", "year", False),
    ]
    for key, amount, cadence, rollover in plan:
        s.add(
            BudgetLine(
                id=ids.new_id("BdgLn"),
                budgetId=b.id,
                categoryId=cat[key].id,
                fromMonth=start,
                amount=D(amount),
                cadence=cadence,
                rollover=rollover,
            )
        )
    # Food went up three months ago: the months before keep the old plan.
    s.add(
        BudgetLine(
            id=ids.new_id("BdgLn"),
            budgetId=b.id,
            categoryId=cat["food"].id,
            fromMonth=add_months(month_of(clock.today()), -2),
            amount=D("600.00"),
        )
    )
    today = clock.today()
    for account, days, amount, payee, key, extra in (
        ("Travel Visa", 12, "-389.20", "Hilton Chicago", "travel", {"owedBy": "Acme Corp"}),
        ("Everyday checking", 5, "389.20", "Acme Corp expense report", "income.other", {}),
    ):
        s.add(
            Transaction(
                id=ids.new_id("Txn"),
                accountId=acct[account].id,
                date=today - dt.timedelta(days=days),
                kind="deposit" if amount[0] != "-" else "withdrawal",
                amount=D(amount),
                payee=payee,
                payeeRaw=payee.upper(),
                categoryId=cat[key].id,
                reimbursable=D("389.20") if extra else None,
                **extra,
            )
        )
    s.add(
        Share(
            id=ids.new_id("Share"),
            kind="budget",
            itemId=b.id,
            level="write",
            groupId=household.id,
            createdById=alice.id,
        )
    )
