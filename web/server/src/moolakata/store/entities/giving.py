import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from . import Record


@dataclass(kw_only=True, eq=False)
class GivingPlan(Record):
    id: str
    ownerId: str
    year: int
    targetKind: str = "percent"
    percent: Decimal | None = None
    amount: Decimal | None = None
    incomeBasis: str = "take-home"
    income: Decimal | None = None
    dafCounted: str = "funded"

    @property
    def name(self) -> str:
        """What the Share dialog calls it."""
        return f"Giving plan {self.year}"


@dataclass(kw_only=True, eq=False)
class Organisation(Record):
    id: str
    ownerId: str
    name: str
    ein: str | None = None
    deductible: bool = True
    causes: str = "[]"
    pledge: Decimal | None = None
    pledgeEvery: str | None = None
    pledgeFrom: dt.date | None = None  # the first day of the period the pledge was set in
    notes: str | None = None


@dataclass(kw_only=True, eq=False)
class Donation(Record):
    id: str
    ownerId: str
    date: dt.date
    kind: str
    amount: Decimal
    organisationId: str | None = None
    description: str | None = None
    transactionId: str | None = None
    dafAccountId: str | None = None
    fromAccountId: str | None = None
    instrumentId: str | None = None
    quantity: Decimal | None = None
    basis: Decimal | None = None
    longTerm: bool | None = None
    acknowledged: bool = False
    granted: bool | None = None
    notes: str | None = None
