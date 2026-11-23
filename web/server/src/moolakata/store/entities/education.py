import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from . import Record, SoftDeleted


@dataclass(kw_only=True, eq=False)
class Person(Record):
    id: str
    name: str
    sex: str
    ownerId: str | None = None
    birthMonth: int | None = None
    birthDay: int | None = None
    birthYear: int | None = None
    diedOn: dt.date | None = None
    private: bool = False


@dataclass(kw_only=True, eq=False)
class Relationship(Record):
    id: str
    person1Id: str
    person2Id: str
    relation: str
    label: str | None = None
    fromDate: dt.date | None = None
    toDate: dt.date | None = None
    confirmed1At: dt.datetime | None = None
    confirmed2At: dt.datetime | None = None


@dataclass(kw_only=True, eq=False)
class GiftPlan(Record):
    id: str
    ownerId: str
    personId: str
    giftBudget: Decimal | None = None
    birthdayBudget: Decimal | None = None
    weddingBudget: Decimal | None = None
    leadDays: int = 14
    notes: str | None = None


@dataclass(kw_only=True, eq=False)
class EducationPlan(Record):
    id: str
    accountId: str
    planState: str | None = None
    planName: str | None = None
    beneficiaryId: str | None = None
    openedOn: dt.date | None = None
    stateDeduction: Decimal | None = None


@dataclass(kw_only=True, eq=False)
class Contribution(Record):
    id: str
    transactionId: str
    fromPersonId: str | None = None
    fiveYear: bool = False


@dataclass(kw_only=True, eq=False)
class QualifiedExpense(Record):
    id: str
    accountId: str
    date: dt.date
    year: int
    kind: str
    amount: Decimal
    description: str | None = None
    transactionId: str | None = None


@dataclass(kw_only=True, eq=False)
class Occasion(Record):
    id: str
    giftPlanId: str
    kind: str
    name: str | None = None
    holiday: str | None = None
    month: int | None = None
    day: int | None = None
    year: int | None = None
    budget: Decimal | None = None


@dataclass(kw_only=True, eq=False)
class Gift(Record):
    id: str
    ownerId: str
    description: str
    occasion: str | None = None
    occasionYear: int | None = None
    status: str = "idea"
    cost: Decimal | None = None
    transactionId: str | None = None
    store: str | None = None
    link: str | None = None
    notes: str | None = None
    cash: bool = False
    thankYou: bool = False


@dataclass(kw_only=True, eq=False)
class GiftPerson(SoftDeleted):
    giftId: str
    personId: str
    createdAt: dt.datetime
    deletedAt: dt.datetime | None = None
    deletedById: str | None = None
