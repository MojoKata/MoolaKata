import datetime as dt
from dataclasses import dataclass, field
from typing import ClassVar

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
class AccessClass(Record):
    """What a share grants beyond reading (docs/schema.md §7): `read` or `write`."""

    id: str
    name: str
    writable: bool
    deletable: bool = False
    shareable: bool = False
    configurable: bool = False


@dataclass(kw_only=True, eq=False)
class ItemShare(Record):
    """A grant of one item to one user or one group (S10.3), at an access class. Each
    shareable kind has its own table and class (`AccountShare`, …): `SHARE_ENTITIES`."""

    kind: ClassVar[str] = ""
    id: str
    targetId: str
    accessClassId: str
    userId: str | None = None
    groupId: str | None = None
    createdById: str | None = None
    includeReceipts: bool = False


def _share(name: str, kind: str) -> type[ItemShare]:
    cls = dataclass(kw_only=True, eq=False)(type(name, (ItemShare,), {"kind": kind}))
    return cls


SHARE_ENTITIES: dict[str, type[ItemShare]] = {
    kind: _share(name, kind)
    for kind, name in (
        ("account", "AccountShare"),
        ("portfolio", "PortfolioShare"),
        ("budget", "BudgetShare"),
        ("projection", "ProjectionShare"),
        ("person", "PersonShare"),
        ("gift-plan", "GiftPlanShare"),
        ("giving-plan", "GivingPlanShare"),
        ("tax-book", "TaxBookShare"),
    )
}


@dataclass(kw_only=True, eq=False)
class CountedAccount(Record):
    id: str = field(default_factory=lambda: new_id("CntAc"))
    userId: str
    accountId: str
    counted: bool = True
