import datetime as dt
from dataclasses import dataclass, field

from ...ids import new_id
from . import Record, SoftDeleted


@dataclass(kw_only=True, eq=False)
class Portfolio(Record):
    id: str
    ownerId: str
    name: str
    benchmark: str = "VT"
    notes: str | None = None


@dataclass(kw_only=True, eq=False)
class PortfolioAccount(SoftDeleted):
    portfolioId: str
    accountId: str
    createdAt: dt.datetime
    deletedAt: dt.datetime | None = None
    deletedById: str | None = None


@dataclass(kw_only=True, eq=False)
class Share(Record):
    id: str
    kind: str
    itemId: str
    level: str
    userId: str | None = None
    groupId: str | None = None
    createdById: str | None = None
    includeReceipts: bool = False


@dataclass(kw_only=True, eq=False)
class CountedAccount(Record):
    id: str = field(default_factory=lambda: new_id("CntAc"))
    userId: str
    accountId: str
    counted: bool = True
