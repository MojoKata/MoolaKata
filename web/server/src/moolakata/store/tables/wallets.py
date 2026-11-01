"""Self-custody bitcoin wallets (requirements S1.6): the public keys and addresses a wallet
account holds, and the addresses derived from its keys."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)

from ..types import UtcTimestamp
from ._base import Seen, exception, record, unique_live

# An extended public key (xpub, ypub, zpub) or one address, as entered (S1.6.1).
WalletKey = record(
    "WalletKey",
    "WKey",
    Column("accountId", Text, ForeignKey("Account.id"), nullable=False),
    Column("kind", Text, nullable=False),  # xpub, descriptor or address
    Column("value", Text, nullable=False),
    Column("script", Text, nullable=False),  # p2pkh, p2sh-p2wpkh, p2wpkh, p2sh, p2wsh, p2tr
    Column("gapLimit", Integer, nullable=False, server_default=text("20")),
    CheckConstraint("kind IN ('xpub', 'descriptor', 'address')", name="kind"),
    CheckConstraint('"gapLimit" BETWEEN 1 AND 1000', name="gapLimit"),
    seen=Seen.child("accountId"),
)
unique_live(WalletKey, "accountId", "value")

# Each address a wallet watches: a typed one, or one derived from a key on the receive (0) or
# change (1) chain, derived until `gapLimit` in a row are unused. Worked out again from the keys
# and what the explorer or node says: a cache (schema.md §4.4.5).
WalletAddress = exception(
    "WalletAddress",
    "cache: derived again from the wallet's keys and its explorer or node (§4.4.5)",
    Column("accountId", Text, ForeignKey("Account.id", ondelete="CASCADE"), nullable=False),
    Column("keyId", Text, ForeignKey("WalletKey.id", ondelete="CASCADE"), nullable=False),
    Column("address", Text, nullable=False),
    Column("chain", Integer),  # 0 receive, 1 change; null for a typed address
    Column("idx", Integer),
    Column("used", Boolean, nullable=False, server_default=text("0")),
    Column("txCount", Integer, nullable=False, server_default=text("0")),
    Column("balanceSats", BigInteger, nullable=False, server_default=text("0")),
    Column("checkedAt", UtcTimestamp),
    Column("createdAt", UtcTimestamp, nullable=False),
    CheckConstraint("chain IS NULL OR chain IN (0, 1)", name="chain"),
    prefix="WAddr",
    seen=Seen.child("accountId"),
)
Index(
    "ux_WalletAddress_account_address",
    WalletAddress.c.accountId,
    WalletAddress.c.address,
    unique=True,
)
Index("ix_WalletAddress_key", WalletAddress.c.keyId, WalletAddress.c.chain, WalletAddress.c.idx)
