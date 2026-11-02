"""Receipts (requirements S9): each file encrypted on disk, written once; the database holds
what is known about it, its thumbnail, and what it is attached to."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    Text,
    text,
)

from ..types import Cents, Day, UtcTimestamp
from ._base import AllOf, ByKind, Seen, Via, pairs, record, unique_live

Receipt = record(
    "Receipt",
    "Rcpt",
    Column("ownerId", Text, ForeignKey("User.id"), nullable=False),
    Column("fileName", Text, nullable=False),
    Column("mediaType", Text, nullable=False),
    Column("size", Integer, nullable=False),
    # The plaintext's SHA-256: identical files are stored once, found by it, never by name.
    Column("sha256", Text, nullable=False),
    # receipts/<fileId>.mkr: shared by every receipt with the same hash.
    Column("fileId", Text, nullable=False),
    Column("thumbnail", LargeBinary),
    Column("date", Day),
    Column("amount", Cents),
    Column("payee", Text),
    Column("notes", Text),
    # Reading it (S9.8): where it stands, how and with what it was read, the full text (also
    # in ReceiptSearch for search), the suggested fields with their confidences, and which of
    # its fields still hold a suggestion rather than what a person typed.
    Column("readStatus", Text, nullable=False, server_default=text("'waiting'")),
    Column("readError", Text),
    Column("readMethod", Text),
    Column("readEngine", Text),
    Column("readAt", UtcTimestamp),
    Column("text", Text),
    Column("suggested", Text, nullable=False, server_default=text("'{}'")),
    Column("filled", Text, nullable=False, server_default=text("'[]'")),
    # Kept for ever, whatever its retention (S14.10.1.3).
    Column("keep", Boolean, nullable=False, server_default=text("0")),
    # Its file removed by file pruning (S14.10.5); the row and its links stay.
    Column("filePrunedAt", UtcTimestamp),
    Column("filePrunedById", Text, ForeignKey("User.id")),
    CheckConstraint(
        "\"readStatus\" IN ('off', 'waiting', 'reading', 'read', 'failed')", name="read_status"
    ),
    CheckConstraint(
        "\"mediaType\" IN ('application/pdf', 'image/jpeg', 'image/png', 'image/webp', "
        "'image/heic')",
        name="media_type",
    ),
    Index("ix_Receipt_ownerId", "ownerId"),
    Index("ix_Receipt_sha256", "sha256"),
    seen=Seen.rule(creates="anyone"),
)

# A receipt's tags (S9.1), each its tagger's own (Tag).
ReceiptTags = pairs(
    "ReceiptTags",
    Column("receiptId", Text, ForeignKey("Receipt.id", ondelete="CASCADE"), nullable=False),
    Column("tagId", Text, ForeignKey("Tag.id", ondelete="CASCADE"), nullable=False),
    PrimaryKeyConstraint("receiptId", "tagId"),
)

# What a receipt is attached to (S9.3): transactions, an account (a statement kept as a
# receipt, S1.3.3), a physical-asset item's photos and documents (S1.10.1), a 529's qualified
# expenses (S1.8.3), gifts (S7.8.1), donations' acknowledgements (S8.9), and other kinds as
# they are built.
ReceiptLink = record(
    "ReceiptLink",
    "RcLnk",
    Column("receiptId", Text, ForeignKey("Receipt.id", ondelete="CASCADE"), nullable=False),
    Column("kind", Text, nullable=False),
    Column("itemId", Text, nullable=False),
    Column("linkedById", Text, ForeignKey("User.id")),
    CheckConstraint(
        "kind IN ('transaction', 'account', 'item', 'expense', 'gift', 'donation')",
        name="kind",
    ),
    Index("ix_ReceiptLink_item", "kind", "itemId"),
    seen=Seen.rule(
        creates=AllOf(
            (
                Via(
                    "receiptId",
                    refused=(
                        "receipt-read-only",
                        "That receipt is shared with you to read: it can't be attached to "
                        "anything else.",
                    ),
                ),
                ByKind(
                    "kind",
                    "itemId",
                    (
                        ("transaction", "Transaction"),
                        ("account", "Account"),
                        ("item", "Item"),
                        ("expense", "QualifiedExpense"),
                        ("gift", "Gift"),
                        ("donation", "Donation"),
                    ),
                    refused=("read-only", "That is shared with you to read."),
                    missing=("not-found", "That is not there."),
                ),
            )
        )
    ),
)
unique_live(ReceiptLink, "receiptId", "kind", "itemId")

# The full-text index of what was read (SQLite FTS5), kept by the reader, searched by the
# Receipts screen. A virtual table, made by revision 0007 rather than declared here.
SEARCH = "ReceiptSearch"


def is_search_table(name: str) -> bool:
    """FTS5's table and the shadow tables it keeps beside it."""
    return name == SEARCH or name.startswith(SEARCH + "_")
