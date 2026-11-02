import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from ...ids import new_id
from . import Record, SoftDeleted


@dataclass(kw_only=True, eq=False)
class TaxBook(Record):
    id: str
    ownerId: str
    year: int
    bitcoinFees: str = "sale"
    fromLastYear: bool = False  # the choice made (S8.14.4)
    copyPending: bool = False  # the copy from last year, waiting for every filer
    carryoverShareShort: Decimal | None = None  # a joint carryover's share, typed (S8.18)
    carryoverShareLong: Decimal | None = None

    @property
    def name(self) -> str:
        """What the Share dialog calls it."""
        return f"Tax book {self.year}"


@dataclass(kw_only=True, eq=False)
class TaxBookFiler(Record):
    id: str = field(default_factory=lambda: new_id("TxBkF"))
    bookId: str
    userId: str
    acceptedAt: dt.datetime | None = None


@dataclass(kw_only=True, eq=False)
class TaxBookAccount(Record):
    id: str = field(default_factory=lambda: new_id("TxBkA"))
    bookId: str
    accountId: str
    counted: bool
    addedById: str | None = None


@dataclass(kw_only=True, eq=False)
class TaxBookDependent(Record):
    id: str
    bookId: str
    personId: str
    claimedAs: str
    months: int = 12
    student: bool = False


@dataclass(kw_only=True, eq=False)
class TaxDependentAccount(SoftDeleted):
    dependentId: str
    accountId: str
    createdAt: dt.datetime
    deletedAt: dt.datetime | None = None
    deletedById: str | None = None


@dataclass(kw_only=True, eq=False)
class Filing(Record):
    id: str
    bookId: str
    jurisdiction: str
    form: str
    place: str | None = None
    amendsId: str | None = None
    filingStatus: str | None = None
    preparedBy: str | None = None
    sentBy: str | None = None
    progress: str = "not started"
    dueDate: dt.date | None = None
    extensionFiledOn: dt.date | None = None
    extendedDue: dt.date | None = None
    filedOn: dt.date | None = None
    confirmation: str | None = None
    resultKind: str | None = None
    resultAmount: Decimal | None = None
    resultTransactionId: str | None = None
    carried: str = "{}"
    filedGains: str | None = None  # the book's gains when it closed the year, as JSON


@dataclass(kw_only=True, eq=False)
class TaxBookChange(Record):
    id: str
    bookId: str
    accountId: str
    gains: Decimal
    madeById: str | None = None
    settled: str | None = None
    settledAt: dt.datetime | None = None
    settledById: str | None = None


@dataclass(kw_only=True, eq=False)
class EstimatedPayment(Record):
    id: str
    filingId: str
    quarter: int
    amount: Decimal
    dueDate: dt.date | None = None
    paidOn: dt.date | None = None
    transactionId: str | None = None


@dataclass(kw_only=True, eq=False)
class TaxDocument(Record):
    id: str
    bookId: str
    direction: str
    form: str
    filingId: str | None = None
    issuer: str | None = None
    accountId: str | None = None
    receiptId: str | None = None
    notes: str | None = None
