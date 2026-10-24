import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from . import Record, SoftDeleted


@dataclass(kw_only=True, eq=False)
class Category(Record):
    id: str
    name: str
    kind: str
    parentId: str | None = None
    taxTag: str | None = None
    builtIn: str | None = None
    createdById: str | None = None
    keepReceiptsYears: int | None = None


@dataclass(kw_only=True, eq=False)
class Account(Record):
    id: str
    ownerId: str
    name: str
    type: str
    institution: str | None = None
    mask: str | None = None
    active: bool = True
    notes: str | None = None
    keptBy: str = '["manual"]'
    lotMethod: str = "fifo"
    countInNetWorth: bool = True
    openingBalance: Decimal | None = None
    openingDate: dt.date | None = None
    statementInterval: str | None = None
    statementIntervalDismissed: str | None = None
    connectionId: str | None = None
    syncAccount: str | None = None


@dataclass(kw_only=True, eq=False)
class Instrument(Record):
    id: str
    symbol: str
    instrumentClass: str
    name: str | None = None
    cusip: str | None = None


@dataclass(kw_only=True, eq=False)
class ImportMapping(Record):
    id: str
    ownerId: str
    institution: str
    columns: str


@dataclass(kw_only=True, eq=False)
class Rule(Record):
    id: str
    ownerId: str
    position: int
    payeeMatch: str
    amountMin: Decimal | None = None
    amountMax: Decimal | None = None
    direction: str = "any"
    accountId: str | None = None
    categoryId: str | None = None
    payee: str | None = None
    tags: str = "[]"


@dataclass(kw_only=True, eq=False)
class StatementLayout(Record):
    id: str
    ownerId: str
    institution: str
    layout: str = "{}"


@dataclass(kw_only=True, eq=False)
class Import(Record):
    id: str
    accountId: str
    userId: str
    format: str
    fileName: str
    fileHash: str
    coveredFrom: dt.date | None = None
    coveredTo: dt.date | None = None
    added: int = 0
    matched: int = 0
    changed: int = 0


@dataclass(kw_only=True, eq=False)
class Transaction(Record):
    id: str
    accountId: str
    date: dt.date
    kind: str
    amount: Decimal
    payee: str | None = None
    payeeRaw: str | None = None
    memo: str | None = None
    categoryId: str | None = None
    instrumentId: str | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    fees: Decimal | None = None
    dividendType: str | None = None
    splitRatio: Decimal | None = None
    lotMethod: str | None = None
    contributionYear: int | None = None
    contributionSource: str | None = None
    transferId: str | None = None
    importId: str | None = None
    fitId: str | None = None
    runningBalance: Decimal | None = None
    amountWas: Decimal | None = None
    duplicateAnswer: str | None = None
    cleared: bool = False
    reconciliationId: str | None = None
    proceedsAdjustment: Decimal | None = None
    optionTransactionId: str | None = None
    createdById: str | None = None
    offChainAt: dt.datetime | None = None
    offChainMissedAt: dt.datetime | None = None
    offChainKeptAt: dt.datetime | None = None


@dataclass(kw_only=True, eq=False)
class Split(Record):
    id: str
    transactionId: str
    amount: Decimal
    categoryId: str | None = None
    memo: str | None = None


@dataclass(kw_only=True, eq=False)
class TransactionTag(SoftDeleted):
    transactionId: str
    userId: str
    tag: str
    createdAt: dt.datetime
    deletedAt: dt.datetime | None = None
    deletedById: str | None = None


@dataclass(kw_only=True, eq=False)
class Lot(Record):
    id: str
    accountId: str
    instrumentId: str
    acquiredOn: dt.date
    quantity: Decimal
    transactionId: str | None = None
    costBasis: Decimal | None = None
    basisMissing: bool = False


@dataclass(kw_only=True, eq=False)
class LotPick(SoftDeleted):
    saleId: str
    lotId: str
    quantity: Decimal
    createdAt: dt.datetime
    deletedAt: dt.datetime | None = None
    deletedById: str | None = None


@dataclass(kw_only=True, eq=False)
class Holding(Record):
    id: str
    accountId: str
    instrumentId: str
    asOf: dt.date
    quantity: Decimal
    marketValue: Decimal | None = None
    importId: str | None = None


@dataclass(kw_only=True, eq=False)
class TransferMatch(Record):
    id: str
    ownerId: str
    outId: str
    inId: str
    state: str = "proposed"


@dataclass(kw_only=True, eq=False)
class HoldingCheck(Record):
    id: str
    accountId: str
    asOf: dt.date
    label: str
    importId: str | None = None
    instrumentId: str | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    marketValue: Decimal | None = None
    costBasis: Decimal | None = None
    cash: bool = False


@dataclass(kw_only=True, eq=False)
class Anchor(Record):
    id: str
    accountId: str
    date: dt.date
    balance: Decimal
    source: str
    importId: str | None = None
    note: str | None = None
    createdById: str | None = None


@dataclass(kw_only=True, eq=False)
class Reconciliation(Record):
    id: str
    accountId: str
    statementDate: dt.date
    statementBalance: Decimal
    finishedAt: dt.datetime | None = None
    finishedById: str | None = None


@dataclass(kw_only=True, eq=False)
class Loan(Record):
    id: str
    accountId: str
    principal: Decimal
    startDate: dt.date
    termMonths: int
    rate: Decimal
    method: str = "amortized"
    payment: Decimal | None = None
    escrowTax: Decimal | None = None
    escrowInsurance: Decimal | None = None
    pmi: Decimal | None = None
    drawMonths: int | None = None
    resets: str = "[]"
    recasts: str = "[]"
    originalValue: Decimal | None = None
    securedById: str | None = None
    budgetCounting: str = "split"
    budgetCategoryId: str | None = None


@dataclass(kw_only=True, eq=False)
class PayoffPlan(Record):
    id: str
    accountId: str
    name: str
    inputs: str
    following: bool = False
    followingSince: dt.date | None = None
    createdById: str | None = None


@dataclass(kw_only=True, eq=False)
class OptionContract(Record):
    id: str
    instrumentId: str
    underlyingId: str
    right: str
    strike: Decimal
    expiry: dt.date
    multiplier: int = 100
    root: str | None = None
    deliverable: str | None = None
    deliverableCash: Decimal | None = None


@dataclass(kw_only=True, eq=False)
class Strategy(Record):
    id: str
    accountId: str
    underlyingId: str
    openedOn: dt.date
    name: str | None = None
    cashSecured: bool = False
    marginRequirement: Decimal | None = None
    dismissed: bool = False


@dataclass(kw_only=True, eq=False)
class StrategyLeg(SoftDeleted):
    strategyId: str
    instrumentId: str
    addedOn: dt.date
    createdAt: dt.datetime
    quantity: Decimal | None = None
    deletedAt: dt.datetime | None = None
    deletedById: str | None = None


@dataclass(kw_only=True, eq=False)
class WashSale:
    id: str
    ownerId: str
    saleId: str
    replacementId: str
    quantity: Decimal
    disallowed: Decimal
    heldFrom: dt.date
    createdAt: dt.datetime


@dataclass(kw_only=True, eq=False)
class WalletKey(Record):
    id: str
    accountId: str
    kind: str
    value: str
    script: str
    gapLimit: int = 20


@dataclass(kw_only=True, eq=False)
class WalletAddress:
    id: str
    accountId: str
    keyId: str
    address: str
    chain: int | None
    idx: int | None
    createdAt: dt.datetime
    used: bool = False
    txCount: int = 0
    balanceSats: int = 0
    checkedAt: dt.datetime | None = None
