"""Price sources and stored daily closes (requirements S4)."""

from sqlalchemy import Boolean, Column, ForeignKey, Index, Text, text

from ..types import Day, Dec, UtcTimestamp
from ._base import Seen, record, unique_live

PriceSource = record(
    "PriceSource",
    "Src",
    # The module that serves it (prices/<name>.py).
    Column("name", Text, nullable=False),
    Column("enabled", Boolean, nullable=False, server_default=text("0")),
    # Its place in the order of preference for each class it serves: {"equity": 1, ...}.
    Column("preference", Text, nullable=False, server_default=text("'{}'")),
    Column("lastRunAt", UtcTimestamp),
    Column("lastOkAt", UtcTimestamp),
    Column("lastError", Text),
    Column("createdById", Text, ForeignKey("User.id")),
    seen=Seen.admin(),
)
unique_live(PriceSource, "name")

# One close per instrument and market day, kept for ever (S4.6). Typed prices are kept apart,
# each its typer's (TypedPrice).
Price = record(
    "Price",
    "Price",
    Column("instrumentId", Text, ForeignKey("Instrument.id"), nullable=False),
    Column("date", Day, nullable=False),
    Column("close", Dec, nullable=False),
    Column("source", Text, nullable=False),
    Column("fetchedAt", UtcTimestamp, nullable=False),
    Column("enteredById", Text, ForeignKey("User.id")),
    Index("ix_Price_date", "date"),
    seen=Seen.household(),
)
unique_live(Price, "instrumentId", "date")

# A price a user typed (S4.10), with its date: it values their own accounts, and never another
# user's; kept for ever, as closes are.
TypedPrice = record(
    "TypedPrice",
    "TyPrc",
    Column("instrumentId", Text, ForeignKey("Instrument.id"), nullable=False),
    Column("userId", Text, ForeignKey("User.id"), nullable=False),
    Column("date", Day, nullable=False),
    Column("close", Dec, nullable=False),
    seen=Seen.per_user("userId"),
)
unique_live(TypedPrice, "userId", "instrumentId", "date")
