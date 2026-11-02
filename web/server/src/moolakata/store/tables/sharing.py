"""Portfolios and shares (requirements S5.1, S10.3–S10.7)."""

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    Text,
    text,
)

from ._base import Seen, pairs, record, unique_live

Portfolio = record(
    "Portfolio",
    "Portf",
    Column("ownerId", Text, ForeignKey("User.id"), nullable=False),
    Column("name", Text, nullable=False),
    # What Performance compares it with: a symbol (SPY, VT) or "60-40" (VT and BND).
    Column("benchmark", Text, nullable=False, server_default=text("'VT'")),
    Column("notes", Text),
    Index("ix_Portfolio_ownerId", "ownerId"),
    seen=Seen.root("portfolio", "PfShr"),
)

PortfolioAccounts = pairs(
    "PortfolioAccounts",
    Column("portfolioId", Text, ForeignKey("Portfolio.id", ondelete="CASCADE"), nullable=False),
    Column("accountId", Text, ForeignKey("Account.id", ondelete="CASCADE"), nullable=False),
    PrimaryKeyConstraint("portfolioId", "accountId"),
)

# A receiver's "Count in my totals" on an account shared with them (S10.7).
CountedAccount = record(
    "CountedAccount",
    "CntAc",
    Column("userId", Text, ForeignKey("User.id", ondelete="CASCADE"), nullable=False),
    Column("accountId", Text, ForeignKey("Account.id", ondelete="CASCADE"), nullable=False),
    Column("counted", Boolean, nullable=False, server_default=text("1")),
    seen=Seen.per_user("userId"),
)
unique_live(CountedAccount, "userId", "accountId")
