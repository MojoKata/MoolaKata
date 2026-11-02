import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from ...ids import new_id
from . import Record, SoftDeleted


@dataclass(kw_only=True, eq=False)
class Budget(Record):
    id: str
    ownerId: str
    name: str
    method: str = "tracking"
    reserves: bool = False
    moves: bool = False
    startMonth: dt.date | None = None


@dataclass(kw_only=True, eq=False)
class BudgetAccount(Record):
    id: str = field(default_factory=lambda: new_id("BdgAc"))
    budgetId: str
    accountId: str
    movedFromId: str | None = None
    paidFromId: str | None = None
    fromMonth: dt.date | None = None
    untilMonth: dt.date | None = None


@dataclass(kw_only=True, eq=False)
class BudgetLine(Record):
    id: str
    budgetId: str
    categoryId: str
    fromMonth: dt.date
    amount: Decimal
    out: bool = False
    cadence: str = "month"
    rollover: bool = False
    overspend: str = "carry"
    projectionId: str | None = None
    target: Decimal | None = None
    heldInId: str | None = None


@dataclass(kw_only=True, eq=False)
class BudgetReview(Record):
    id: str
    budgetId: str
    month: dt.date
    figures: str
    reviewedById: str | None = None


@dataclass(kw_only=True, eq=False)
class BudgetLeaveOut(SoftDeleted):
    budgetId: str
    transactionId: str
    createdAt: dt.datetime
    deletedAt: dt.datetime | None = None
    deletedById: str | None = None


@dataclass(kw_only=True, eq=False)
class BudgetMove(Record):
    id: str
    budgetId: str
    month: dt.date
    amount: Decimal
    fromCategoryId: str | None = None
    toCategoryId: str | None = None
    note: str | None = None
    transactionId: str | None = None
    cardId: str | None = None
    createdById: str | None = None
