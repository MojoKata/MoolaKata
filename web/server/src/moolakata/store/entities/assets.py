import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from . import Record


@dataclass(kw_only=True, eq=False)
class Item(Record):
    id: str
    accountId: str
    name: str
    acquiredOn: dt.date
    costBasis: Decimal
    category: str | None = None
    description: str | None = None
    acquiredHow: str = "bought"
    heldFrom: dt.date | None = None  # a gift's, from the giver's holding (S1.10.1)
    quantity: Decimal = Decimal(1)
    location: str | None = None
    serial: str | None = None
    condition: str | None = None
    insuredValue: Decimal | None = None
    policy: str | None = None
    notes: str | None = None
    valuation: str = "valuations"
    metal: str | None = None
    unitWeight: Decimal | None = None
    weightUnit: str | None = None
    purity: Decimal | None = None
    sellPremium: Decimal = Decimal(0)
    depreciationRate: Decimal | None = None
    address: str | None = None
    closingCosts: Decimal | None = None
    primaryResidence: bool = False
    personalUse: bool = False
    soldOn: dt.date | None = None
    proceeds: Decimal | None = None
    saleFees: Decimal | None = None
    createdById: str | None = None


@dataclass(kw_only=True, eq=False)
class ItemValuation(Record):
    id: str
    itemId: str
    date: dt.date
    value: Decimal
    source: str = "estimate"
    note: str | None = None
    createdById: str | None = None


@dataclass(kw_only=True, eq=False)
class Improvement(Record):
    id: str
    itemId: str
    date: dt.date
    description: str
    amount: Decimal
    createdById: str | None = None
