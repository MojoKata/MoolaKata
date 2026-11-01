"""Charitable giving (requirements S7.9): a yearly giving plan with its target, the
organisations given to, and donations of every type."""

from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Index, Integer, Text, text

from ..types import Cents, Day, Dec
from ._base import Seen, record

# A year's giving plan, a user's own or shared with a group as budgets are (S7.9.1).
GivingPlan = record(
    "GivingPlan",
    "GvPln",
    Column("ownerId", Text, ForeignKey("User.id"), nullable=False),
    Column("year", Integer, nullable=False),
    Column("targetKind", Text, nullable=False, server_default=text("'percent'")),
    Column("percent", Dec),  # of income
    Column("amount", Cents),  # a fixed target
    # The income the percentage is of: income transactions (take-home), or a typed gross
    # income or AGI estimate.
    Column("incomeBasis", Text, nullable=False, server_default=text("'take-home'")),
    Column("income", Cents),
    # A donor-advised fund counts toward the target when it is funded, or when it grants.
    Column("dafCounted", Text, nullable=False, server_default=text("'funded'")),
    CheckConstraint("\"targetKind\" IN ('percent', 'amount')", name="target_kind"),
    CheckConstraint("\"incomeBasis\" IN ('take-home', 'gross', 'agi')", name="income_basis"),
    CheckConstraint("\"dafCounted\" IN ('funded', 'granted')", name="daf_counted"),
    Index("ix_GivingPlan_owner", "ownerId", "year"),
    seen=Seen.root("giving-plan"),
)

# An organisation given to (S7.9.5).
Organisation = record(
    "Organisation",
    "Orgzn",
    Column("ownerId", Text, ForeignKey("User.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("ein", Text),
    # Gifts to it are deductible: a 501(c)(3) charity, not a campaign or a person.
    Column("deductible", Boolean, nullable=False, server_default=text("1")),
    Column("causes", Text, nullable=False, server_default=text("'[]'")),  # JSON list of tags
    Column("pledge", Cents),  # an amount promised each pledgeEvery
    Column("pledgeEvery", Text),
    Column("notes", Text),
    CheckConstraint(
        "\"pledgeEvery\" IS NULL OR \"pledgeEvery\" IN ('month', 'year')", name="pledge_every"
    ),
    Index("ix_Organisation_ownerId", "ownerId"),
    seen=Seen.rule(),
)

# A donation (S7.9.3): to an organisation, into a donor-advised fund, or a grant from one.
Donation = record(
    "Donation",
    "Dnatn",
    Column("ownerId", Text, ForeignKey("User.id"), nullable=False),
    Column("organisationId", Text, ForeignKey("Organisation.id")),
    Column("date", Day, nullable=False),
    Column("kind", Text, nullable=False),
    # What it is worth: cash given, goods' fair market value, shares' market value.
    Column("amount", Cents, nullable=False),
    Column("description", Text),  # goods given
    Column("transactionId", Text, ForeignKey("Transaction.id", ondelete="SET NULL")),
    Column("dafAccountId", Text, ForeignKey("Account.id")),  # the fund, for its kinds
    # Shares given: from which account, the instrument and quantity, their basis, and
    # whether they were held over a year (then the deduction is the market value).
    Column("fromAccountId", Text, ForeignKey("Account.id")),
    Column("instrumentId", Text, ForeignKey("Instrument.id")),
    Column("quantity", Dec),
    Column("basis", Cents),
    Column("longTerm", Boolean),
    Column("acknowledged", Boolean, nullable=False, server_default=text("0")),
    Column("granted", Boolean),  # a grant's: paid by the fund, else pending
    Column("notes", Text),
    CheckConstraint(
        "kind IN ('cash', 'goods', 'securities', 'qcd', 'daf-contribution', 'daf-grant')",
        name="kind",
    ),
    CheckConstraint("amount >= 0", name="amount"),
    Index("ix_Donation_owner", "ownerId", "date"),
    seen=Seen.rule(),
)
