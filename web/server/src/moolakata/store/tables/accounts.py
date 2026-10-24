"""Accounts, transactions, categories, instruments, lots, imports and reconciliation
(requirements S1, S2, S7.2)."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    text,
)

from ..types import Cents, Day, Dec, UtcTimestamp
from ._base import pairs, record, unique_live

ACCOUNT_TYPES = (
    "checking",
    "savings",
    "money-market",
    "cd",
    "cash",
    "payment-app",
    "credit-card",
    "brokerage",
    "ira",
    "roth-ira",
    "401k",
    "403b",
    "457b",
    "hsa",
    "mortgage",
    "heloc",
    "auto-loan",
    "student-loan",
    "personal-loan",
    "loan",
    "529",
    "daf",
    "crypto-exchange",
    "crypto-wallet",
    "precious-metals",
    "collectables",
    "real-estate",
    "vehicle",
    "other-asset",
)
LOT_METHODS = ("fifo", "lifo", "hifo", "specific", "average")
TXN_KINDS = (
    "deposit",
    "withdrawal",
    "interest",
    "dividend",
    "fee",
    "transfer",
    "adjustment",
    "buy",
    "sell",
    "reinvest",
    "capital-gain",
    "return-of-capital",
    "transfer-in",
    "transfer-out",
    "split",
    # Options (S3.2): the four opening and closing trades, expiry, assignment and exercise.
    "buy-to-open",
    "sell-to-open",
    "buy-to-close",
    "sell-to-close",
    "expire",
    "assign",
    "exercise",
    # An adjusted contract (S3.10): the lots of one carried to the other, nothing sold. A pair
    # linked by transferId: on the old contract, then on the new with the ratio of contracts.
    "option-adjust",
    # Corporate actions that move lots between instruments (S2.4), pairs in the same way.
    "symbol-change",
    "spin-off",
    "merger",
)
INSTRUMENT_CLASSES = (
    "cash",
    "equity",
    "etf",
    "mutual-fund",
    "money-market",
    "bond",
    "option",
    "crypto",
    "metal",
    "other",
)


def _in(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    listed = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f'"{column}" IN ({listed})', name=name)


Category = record(
    "Category",
    "Cat",
    Column("parentId", Text, ForeignKey("Category.id")),
    Column("name", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("taxTag", Text),
    # Shipped categories carry a key, so a later release can find and correct them.
    Column("builtIn", Text),
    Column("createdById", Text, ForeignKey("User.id")),
    # Keep receipts for so many years after their record ended (S14.10.1.1); none: for ever,
    # or a subcategory takes its parent's.
    Column("keepReceiptsYears", Integer),
    _in("kind", ("expense", "income", "savings", "transfer"), "kind"),
    CheckConstraint(
        '"keepReceiptsYears" IS NULL OR "keepReceiptsYears" >= 1', name="keep_receipts_years"
    ),
)
unique_live(Category, "parentId", "name")

Account = record(
    "Account",
    "Acct",
    Column("ownerId", Text, ForeignKey("User.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("type", Text, nullable=False),
    Column("institution", Text),
    Column("mask", Text),
    Column("active", Boolean, nullable=False, server_default=text("1")),
    Column("notes", Text),
    Column("keptBy", Text, nullable=False, server_default=text("'[\"manual\"]'")),
    Column("lotMethod", Text, nullable=False, server_default=text("'fifo'")),
    Column("countInNetWorth", Boolean, nullable=False, server_default=text("1")),
    # A typed balance before the first transaction. Without one, the opening balance is worked
    # out from the earliest balance the institution reported, and marked as a stand-in (R3.2).
    Column("openingBalance", Cents),
    Column("openingDate", Day),
    # How often its institution issues statements (S1.11.7); none set: the type's default.
    Column("statementInterval", Text),
    # A learned interval the owner dismissed, so it isn't proposed again.
    Column("statementIntervalDismissed", Text),
    # Sync using MoolaKata Connector (S18.6.2): the owner's Connection that keeps this account
    # current, and which of its institution accounts this is (as the driver names it). The
    # key is cleared when the Connection goes: its sync turns off (schema.md §6.4).
    Column("connectionId", Text, ForeignKey("Connection.id")),
    Column("syncAccount", Text),
    _in("type", ACCOUNT_TYPES, "type"),
    _in("lotMethod", LOT_METHODS, "lot_method"),
    CheckConstraint("mask IS NULL OR (length(mask) = 4 AND mask GLOB '[0-9]*')", name="mask"),
    CheckConstraint(
        '"statementInterval" IS NULL OR '
        "\"statementInterval\" IN ('monthly', 'quarterly', 'yearly', 'none')",
        name="statement_interval",
    ),
    Index("ix_Account_ownerId", "ownerId"),
)

Instrument = record(
    "Instrument",
    "Instr",
    Column("symbol", Text, nullable=False),
    Column("name", Text),
    Column("instrumentClass", Text, nullable=False),
    Column("cusip", Text),
    _in("instrumentClass", INSTRUMENT_CLASSES, "instrument_class"),
)
unique_live(Instrument, "symbol")

ImportMapping = record(
    "ImportMapping",
    "Map",
    Column("ownerId", Text, ForeignKey("User.id"), nullable=False),
    Column("institution", Text, nullable=False),
    Column("columns", Text, nullable=False),
)
unique_live(ImportMapping, "ownerId", "institution")

# A user's categorisation and payee rules (S2.7), in order: what a transaction must match
# (its payee as written, by text or `re:`, and an amount range, a direction and an account
# when given), and what the rule sets (a category, a payee shown, tags).
Rule = record(
    "Rule",
    "Rule",
    Column("ownerId", Text, ForeignKey("User.id"), nullable=False),
    Column("position", Integer, nullable=False),
    Column("payeeMatch", Text, nullable=False),
    Column("amountMin", Cents),
    Column("amountMax", Cents),
    Column("direction", Text, nullable=False, server_default=text("'any'")),
    Column("accountId", Text, ForeignKey("Account.id", ondelete="CASCADE")),
    Column("categoryId", Text, ForeignKey("Category.id")),
    Column("payee", Text),
    Column("tags", Text, nullable=False, server_default=text("'[]'")),
    CheckConstraint("direction IN ('any', 'in', 'out')", name="direction"),
    CheckConstraint(
        "\"categoryId\" IS NOT NULL OR payee IS NOT NULL OR tags != '[]'", name="sets_something"
    ),
    Index("ix_Rule_owner", "ownerId", "position"),
)

# What statement import has learned of one institution's layout (S1.3.3): which section
# heading means money in or out, and descriptions that are never transactions.
StatementLayout = record(
    "StatementLayout",
    "Lyout",
    Column("ownerId", Text, ForeignKey("User.id"), nullable=False),
    Column("institution", Text, nullable=False),
    Column("layout", Text, nullable=False, server_default=text("'{}'")),
)
unique_live(StatementLayout, "ownerId", "institution")

Import = record(
    "Import",
    "Imprt",
    Column("accountId", Text, ForeignKey("Account.id", ondelete="CASCADE"), nullable=False),
    Column("userId", Text, ForeignKey("User.id"), nullable=False),
    Column("format", Text, nullable=False),
    Column("fileName", Text, nullable=False),
    Column("fileHash", Text, nullable=False),
    Column("coveredFrom", Day),
    Column("coveredTo", Day),
    Column("added", Integer, nullable=False, server_default=text("0")),
    Column("matched", Integer, nullable=False, server_default=text("0")),
    Column("changed", Integer, nullable=False, server_default=text("0")),
    # kept: a statement kept without reading (S1.3.3.6), its period recorded, nothing added.
    _in("format", ("ofx", "csv", "statement", "kept"), "format"),
    Index("ix_Import_accountId", "accountId"),
)

Transaction = record(
    "Transaction",
    "Txn",
    Column("accountId", Text, ForeignKey("Account.id", ondelete="CASCADE"), nullable=False),
    Column("date", Day, nullable=False),
    Column("kind", Text, nullable=False),
    # The cash effect on the account: + in, − out.
    Column("amount", Cents, nullable=False),
    Column("payee", Text),
    Column("payeeRaw", Text),
    Column("memo", Text),
    Column("categoryId", Text, ForeignKey("Category.id")),
    Column("instrumentId", Text, ForeignKey("Instrument.id")),
    Column("quantity", Dec),
    Column("price", Dec),
    Column("fees", Cents),
    Column("dividendType", Text),
    Column("splitRatio", Dec),
    Column("lotMethod", Text),
    Column("contributionYear", Integer),
    Column("contributionSource", Text),
    # The other half of a matched transfer (S1.7).
    Column("transferId", Text, ForeignKey("Transaction.id")),
    Column("importId", Text, ForeignKey("Import.id")),
    Column("fitId", Text),
    Column("runningBalance", Cents),
    Column("amountWas", Cents),
    Column("duplicateAnswer", Text),
    Column("cleared", Boolean, nullable=False, server_default=text("0")),
    Column("reconciliationId", Text, ForeignKey("Reconciliation.id")),
    # Assignment and exercise (S3.4): a stock sale's proceeds take the option's premium (an
    # assigned call's credit added, an exercised put's premium taken off), and the stock trade
    # names the option's assignment or exercise it came from.
    Column("proceedsAdjustment", Cents),
    Column("optionTransactionId", Text, ForeignKey("Transaction.id")),
    Column("createdById", Text, ForeignKey("User.id")),
    # A bitcoin transaction the explorer or node no longer has (S1.6.2.7): marked once two
    # reads in a row miss it (the first miss is kept), until its owner keeps or deletes it;
    # one kept is never marked again.
    Column("offChainAt", UtcTimestamp),
    Column("offChainMissedAt", UtcTimestamp),
    Column("offChainKeptAt", UtcTimestamp),
    _in("kind", TXN_KINDS, "kind"),
    CheckConstraint(
        '"dividendType" IS NULL OR "dividendType" IN (\'ordinary\', '
        "'qualified', 'capital-gain', 'return-of-capital')",
        name="dividend_type",
    ),
    CheckConstraint(
        "\"lotMethod\" IS NULL OR \"lotMethod\" IN ('fifo', 'lifo', 'hifo', 'specific', 'average')",
        name="lot_method",
    ),
    CheckConstraint(
        '"contributionSource" IS NULL OR "contributionSource" IN '
        "('employee', 'employer', 'rollover')",
        name="contribution_source",
    ),
    CheckConstraint(
        '"duplicateAnswer" IS NULL OR "duplicateAnswer" = \'both-real\'', name="duplicate_answer"
    ),
    Index("ix_Transaction_account_date", "accountId", "date"),
    Index("ix_Transaction_instrument", "instrumentId"),
)
unique_live(Transaction, "accountId", "fitId")

Split = record(
    "Split",
    "Split",
    Column("transactionId", Text, ForeignKey("Transaction.id", ondelete="CASCADE"), nullable=False),
    Column("categoryId", Text, ForeignKey("Category.id")),
    Column("amount", Cents, nullable=False),
    Column("memo", Text),
    Index("ix_Split_transactionId", "transactionId"),
)

TransactionTags = pairs(
    "TransactionTags",
    Column("transactionId", Text, ForeignKey("Transaction.id", ondelete="CASCADE"), nullable=False),
    Column("userId", Text, ForeignKey("User.id", ondelete="CASCADE"), nullable=False),
    Column("tag", Text, nullable=False),
    PrimaryKeyConstraint("transactionId", "userId", "tag"),
)

Lot = record(
    "Lot",
    "Lot",
    Column("accountId", Text, ForeignKey("Account.id", ondelete="CASCADE"), nullable=False),
    Column("instrumentId", Text, ForeignKey("Instrument.id"), nullable=False),
    # The buy or transfer in that made it; null for a lot that stands in for missing history.
    Column("transactionId", Text, ForeignKey("Transaction.id", ondelete="CASCADE")),
    Column("acquiredOn", Day, nullable=False),
    Column("quantity", Dec, nullable=False),
    Column("costBasis", Cents),
    Column("basisMissing", Boolean, nullable=False, server_default=text("0")),
    Index("ix_Lot_account_instrument", "accountId", "instrumentId"),
)

LotPicks = pairs(
    "LotPicks",
    Column("saleId", Text, ForeignKey("Transaction.id", ondelete="CASCADE"), nullable=False),
    Column("lotId", Text, ForeignKey("Lot.id", ondelete="CASCADE"), nullable=False),
    Column("quantity", Dec, nullable=False),
    PrimaryKeyConstraint("saleId", "lotId"),
)

Holding = record(
    "Holding",
    "Hold",
    Column("accountId", Text, ForeignKey("Account.id", ondelete="CASCADE"), nullable=False),
    Column("instrumentId", Text, ForeignKey("Instrument.id"), nullable=False),
    Column("asOf", Day, nullable=False),
    Column("quantity", Dec, nullable=False),
    Column("marketValue", Cents),
    Column("importId", Text, ForeignKey("Import.id")),
    Index("ix_Holding_account_asOf", "accountId", "asOf"),
)

Anchor = record(
    "Anchor",
    "Anchr",
    Column("accountId", Text, ForeignKey("Account.id", ondelete="CASCADE"), nullable=False),
    Column("date", Day, nullable=False),
    Column("balance", Cents, nullable=False),
    Column("source", Text, nullable=False),
    Column("importId", Text, ForeignKey("Import.id")),
    Column("note", Text),
    Column("createdById", Text, ForeignKey("User.id")),
    # statement-value: a brokerage statement's ending value, cash and holdings together,
    # checked against the account's value rather than its cash (S1.3.3.8.1).
    _in("source", ("running-balance", "ofx", "statement", "typed", "statement-value"), "source"),
    Index("ix_Anchor_account_date", "accountId", "date"),
)

# A bitcoin transfer out of one of the owner's accounts and in to another, proposed as a pair
# (S1.7.1); once confirmed, the coins arrive with the lots they left with.
TransferMatch = record(
    "TransferMatch",
    "XfrMt",
    Column("ownerId", Text, ForeignKey("User.id"), nullable=False),
    Column("outId", Text, ForeignKey("Transaction.id", ondelete="CASCADE"), nullable=False),
    Column("inId", Text, ForeignKey("Transaction.id", ondelete="CASCADE"), nullable=False),
    Column("state", Text, nullable=False, server_default=text("'proposed'")),
    _in("state", ("proposed", "confirmed", "rejected"), "state"),
    Index("ix_TransferMatch_owner", "ownerId", "state"),
)
unique_live(TransferMatch, "outId", "inId")

# A position as a brokerage statement shows it on its last day (S1.3.3.8.2): checked against
# what MoolaKata holds then, never written over the lots.
HoldingCheck = record(
    "HoldingCheck",
    "HdChk",
    Column("accountId", Text, ForeignKey("Account.id", ondelete="CASCADE"), nullable=False),
    Column("importId", Text, ForeignKey("Import.id")),
    Column("asOf", Day, nullable=False),
    Column("instrumentId", Text, ForeignKey("Instrument.id")),  # none: not matched
    Column("label", Text, nullable=False),  # as the statement names it
    Column("quantity", Dec),
    Column("price", Dec),
    Column("marketValue", Cents),
    Column("costBasis", Cents),
    Column("cash", Boolean, nullable=False, server_default=text("0")),
    Index("ix_HoldingCheck_account_asOf", "accountId", "asOf"),
)

Reconciliation = record(
    "Reconciliation",
    "Recon",
    Column("accountId", Text, ForeignKey("Account.id", ondelete="CASCADE"), nullable=False),
    Column("statementDate", Day, nullable=False),
    Column("statementBalance", Cents, nullable=False),
    Column("finishedAt", UtcTimestamp),
    Column("finishedById", Text, ForeignKey("User.id")),
)
