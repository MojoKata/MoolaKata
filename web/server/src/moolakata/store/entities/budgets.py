import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

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
class BudgetAccount(SoftDeleted):
    budgetId: str
    accountId: str
    createdAt: dt.datetime
    movedFromId: str | None = None
    paidFromId: str | None = None
    deletedAt: dt.datetime | None = None
    deletedById: str | None = None


@dataclass(kw_only=True, eq=False)
class BudgetLine(Record):
    id: str
    budgetId: str
    categoryId: str
    fromMonth: dt.date
    amount: Decimal
    cadence: str = "month"
    rollover: bool = False
    overspend: str = "carry"
    projectionId: str | None = None
    target: Decimal | None = None
    heldInId: str | None = None
