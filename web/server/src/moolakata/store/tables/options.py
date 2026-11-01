"""Option contracts (requirements S3.2): what makes an option instrument one: its underlying,
call or put, strike, expiry and the shares a contract covers; and wash sales (S3.8)."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)

from ..types import Cents, Day, Dec, UtcTimestamp
from ._base import Seen, exception, record, unique_live

OptionContract = record(
    "OptionContract",
    "OptCt",
    Column("instrumentId", Text, ForeignKey("Instrument.id"), nullable=False),
    Column("underlyingId", Text, ForeignKey("Instrument.id"), nullable=False),
    Column("right", Text, nullable=False),  # call or put
    Column("strike", Dec, nullable=False),
    Column("expiry", Day, nullable=False),
    Column("multiplier", Integer, nullable=False, server_default=text("100")),
    # An adjusted contract's root (AAPL1, S3.10.2); none: its underlying's symbol.
    Column("root", Text),
    # What a contract delivers when adjusted, as JSON: [{"instrumentId", "shares"}], with the
    # cash; none: the multiplier's shares of its underlying.
    Column("deliverable", Text),
    Column("deliverableCash", Cents),
    CheckConstraint("\"right\" IN ('call', 'put')", name="right"),
    CheckConstraint("strike > 0", name="strike"),
    CheckConstraint("multiplier > 0", name="multiplier"),
    Index("ix_OptionContract_underlying", "underlyingId", "expiry"),
    seen=Seen.household(),
)
unique_live(OptionContract, "instrumentId")

# Legs held together and shown as one (S3.5): a label over the legs, whose lots, gains and wash
# sales stay their own. A dismissed one records a proposal turned down, not to be made again.
Strategy = record(
    "Strategy",
    "Strat",
    Column("accountId", Text, ForeignKey("Account.id", ondelete="CASCADE"), nullable=False),
    Column("underlyingId", Text, ForeignKey("Instrument.id"), nullable=False),
    Column("name", Text),  # the owner's; else its shape's
    Column("openedOn", Day, nullable=False),
    Column("cashSecured", Boolean, nullable=False, server_default=text("0")),
    # The broker's margin requirement, the capital at risk of an undefined-risk strategy.
    Column("marginRequirement", Cents),
    Column("dismissed", Boolean, nullable=False, server_default=text("0")),
    Index("ix_Strategy_accountId", "accountId"),
    seen=Seen.child("accountId"),
)

# A strategy's legs: each an instrument held in its account (an option contract, or the
# shares a covered call covers, `quantity` of them), joined when grouped or rolled into it.
StrategyLeg = record(
    "StrategyLeg",
    "StLeg",
    Column("strategyId", Text, ForeignKey("Strategy.id", ondelete="CASCADE"), nullable=False),
    Column("instrumentId", Text, ForeignKey("Instrument.id"), nullable=False),
    Column("quantity", Dec),  # shares, for a stock leg; none: the whole position
    Column("addedOn", Day, nullable=False),
    seen=Seen.child("strategyId"),
)
unique_live(StrategyLeg, "strategyId", "instrumentId")

# A wash sale (S3.8): a loss disallowed because the same instrument was bought within 30 days,
# moved to the replacement's basis with the sold shares' holding period. Worked out from the
# trades whenever they change, and replaced whole: a cache (schema.md §4.4.5).
WashSale = exception(
    "WashSale",
    "cache: worked out again from the transactions whenever they change (§4.4.5)",
    Column("ownerId", Text, ForeignKey("User.id", ondelete="CASCADE"), nullable=False),
    Column("saleId", Text, ForeignKey("Transaction.id", ondelete="CASCADE"), nullable=False),
    Column("replacementId", Text, ForeignKey("Transaction.id", ondelete="CASCADE"), nullable=False),
    Column("quantity", Dec, nullable=False),  # replacement shares used
    Column("disallowed", Cents, nullable=False),
    Column("heldFrom", Day, nullable=False),  # the replacement's holding period starts here
    Column("createdAt", UtcTimestamp, nullable=False),
    prefix="WashS",
    seen=Seen.rule(),
)
Index("ix_WashSale_owner", WashSale.c.ownerId)
Index("ix_WashSale_sale", WashSale.c.saleId)
Index("ix_WashSale_replacement", WashSale.c.replacementId)
