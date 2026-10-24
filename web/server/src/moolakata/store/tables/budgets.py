"""Budgets (requirements S7): a user's plan per category over chosen accounts, by its method,
shared with a group at write for a household budget."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    Text,
    text,
)

from ..types import Cents, Day
from ._base import pairs, record, unique_live

Budget = record(
    "Budget",
    "Bdgt",
    Column("ownerId", Text, ForeignKey("User.id"), nullable=False),
    Column("name", Text, nullable=False),
    # Tracking or envelope, chosen when it is made (S7.1.3); its options (S7.1.4).
    Column("method", Text, nullable=False, server_default=text("'tracking'")),
    Column("reserves", Boolean, nullable=False, server_default=text("0")),
    Column("moves", Boolean, nullable=False, server_default=text("0")),
    # The month it starts in: an envelope budget's first To Budget is that day's cash (S7.13.1).
    Column("startMonth", Day),
    CheckConstraint("method IN ('tracking', 'envelope')", name="method"),
    Index("ix_Budget_ownerId", "ownerId"),
)

BudgetAccounts = pairs(
    "BudgetAccounts",
    Column("budgetId", Text, ForeignKey("Budget.id", ondelete="CASCADE"), nullable=False),
    Column("accountId", Text, ForeignKey("Account.id", ondelete="CASCADE"), nullable=False),
    # Where money comes from (S7.1.6): for an account reserves are held in, the account to move
    # from; for a card, the account paying it when its payments' history is mixed. Each is
    # worked out when not set.
    Column("movedFromId", Text, ForeignKey("Account.id")),
    Column("paidFromId", Text, ForeignKey("Account.id")),
    PrimaryKeyConstraint("budgetId", "accountId"),
)

# One category's plan from a month on. A change to the plan starts a new line from the month
# it is made in, so past months keep the plan they had.
BudgetLine = record(
    "BudgetLine",
    "BdgLn",
    Column("budgetId", Text, ForeignKey("Budget.id", ondelete="CASCADE"), nullable=False),
    Column("categoryId", Text, ForeignKey("Category.id"), nullable=False),
    Column("fromMonth", Day, nullable=False),
    Column("amount", Cents, nullable=False),
    Column("cadence", Text, nullable=False, server_default=text("'month'")),
    Column("rollover", Boolean, nullable=False, server_default=text("0")),
    # In an envelope budget, what an overspent line does at the month's end (S7.13.3).
    Column("overspend", Text, nullable=False, server_default=text("'carry'")),
    # A savings line's active projection, its monthly contribution shown beside (S7.2.1).
    Column("projectionId", Text, ForeignKey("Projection.id")),
    # A reserve's target, and the account its money is held in (S7.10).
    Column("target", Cents),
    Column("heldInId", Text, ForeignKey("Account.id")),
    CheckConstraint("cadence IN ('month', 'year')", name="cadence"),
    CheckConstraint("overspend IN ('carry', 'next')", name="overspend"),
    CheckConstraint("strftime('%d', \"fromMonth\") = '01'", name="from_month"),
    Index("ix_BudgetLine_budgetId", "budgetId"),
)
unique_live(BudgetLine, "budgetId", "categoryId", "fromMonth")

# A budget's month marked reviewed (S7.14): by whom, when, and the figures it had then, so a
# later change to them is flagged.
BudgetReview = record(
    "BudgetReview",
    "BdgRv",
    Column("budgetId", Text, ForeignKey("Budget.id", ondelete="CASCADE"), nullable=False),
    Column("month", Day, nullable=False),
    Column("figures", Text, nullable=False),
    Column("reviewedById", Text, ForeignKey("User.id")),
    CheckConstraint("strftime('%d', month) = '01'", name="month"),
)
unique_live(BudgetReview, "budgetId", "month")

# A transaction a budget leaves out (S7.3.5): a one-off it counts nowhere, the budget's choice.
BudgetLeaveOuts = pairs(
    "BudgetLeaveOuts",
    Column("budgetId", Text, ForeignKey("Budget.id", ondelete="CASCADE"), nullable=False),
    Column("transactionId", Text, ForeignKey("Transaction.id", ondelete="CASCADE"), nullable=False),
    PrimaryKeyConstraint("budgetId", "transactionId"),
)

# An amount put into a category for one month (S7.11): from another category, a reserve among
# them; from or to To Budget in an envelope budget (a category left empty); or landed money, a
# deposit in an account reserves are held in, given to one of them or kept as the account's own
# (S7.10.5).
BudgetMove = record(
    "BudgetMove",
    "BdgMv",
    Column("budgetId", Text, ForeignKey("Budget.id", ondelete="CASCADE"), nullable=False),
    Column("month", Day, nullable=False),
    Column("fromCategoryId", Text, ForeignKey("Category.id")),
    Column("toCategoryId", Text, ForeignKey("Category.id")),
    Column("amount", Cents, nullable=False),
    Column("note", Text),
    Column("transactionId", Text, ForeignKey("Transaction.id", ondelete="CASCADE")),
    # In an envelope budget, a card whose payment line the move puts money into (S7.13.2).
    Column("cardId", Text, ForeignKey("Account.id")),
    Column("createdById", Text, ForeignKey("User.id")),
    CheckConstraint("amount > 0", name="amount"),
    CheckConstraint("strftime('%d', month) = '01'", name="month"),
    CheckConstraint(
        '"fromCategoryId" IS NOT NULL OR "toCategoryId" IS NOT NULL OR "transactionId" IS NOT NULL'
        ' OR "cardId" IS NOT NULL',
        name="somewhere",
    ),
    Index("ix_BudgetMove_budgetId", "budgetId"),
)
