"""Projections and assumptions (requirements S6), and the tax tables' corrections (S16.11)."""

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

from ..types import UtcTimestamp
from ._base import Seen, pairs, record, unique_live

# A user's expected returns and volatility per asset class, inflation and bitcoin model (S6.3).
AssumptionSet = record(
    "AssumptionSet",
    "Asmpt",
    Column("ownerId", Text, ForeignKey("User.id"), nullable=False),
    Column("figures", Text, nullable=False, server_default=text("'{}'")),
    seen=Seen.per_user("ownerId"),
)
unique_live(AssumptionSet, "ownerId")

# How money will grow toward a goal (S6.1). Its inputs and what it is built on are JSON; an
# active one keeps the baseline it is tracked against (S6.7).
Projection = record(
    "Projection",
    "Prjct",
    Column("ownerId", Text, ForeignKey("User.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("goal", Text, nullable=False),
    Column("builtOn", Text, nullable=False, server_default=text("'{}'")),
    Column("inputs", Text, nullable=False, server_default=text("'{}'")),
    Column("active", Boolean, nullable=False, server_default=text("0")),
    Column("baseline", Text),
    Column("baselineAt", UtcTimestamp),
    CheckConstraint("goal IN ('retirement', 'savings', 'education')", name="goal"),
    Index("ix_Projection_ownerId", "ownerId"),
    seen=Seen.root("projection", "PjShr", settings=("active", "baseline", "baselineAt")),
)

# A receiver's "Show on my Dashboard" on an active projection shared with them (S6.8.3).
ShownProjections = pairs(
    "ShownProjections",
    Column("userId", Text, ForeignKey("User.id", ondelete="CASCADE"), nullable=False),
    Column("projectionId", Text, ForeignKey("Projection.id", ondelete="CASCADE"), nullable=False),
    PrimaryKeyConstraint("userId", "projectionId"),
)

# An admin's correction of a shipped tax-table figure for a year (S16.11).
TaxFigure = record(
    "TaxFigure",
    "TaxFg",
    Column("year", Integer, nullable=False),
    Column("key", Text, nullable=False),
    Column("value", Text, nullable=False),
    Column("changedById", Text, ForeignKey("User.id")),
    seen=Seen.household(creates="admin"),
)
unique_live(TaxFigure, "year", "key")
