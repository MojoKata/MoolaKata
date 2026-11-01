"""Physical assets (requirements S1.10): the items a physical-asset account holds, their dated
valuations, and a property's improvements."""

from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Index, Text, text

from ..types import Cents, Day, Dec
from ._base import Seen, record

Item = record(
    "Item",
    "Item",
    Column("accountId", Text, ForeignKey("Account.id", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("category", Text),  # a collectable's kind (watch, art, wine…), or the metal's form
    Column("description", Text),
    Column("acquiredOn", Day, nullable=False),
    Column("acquiredHow", Text, nullable=False, server_default=text("'bought'")),
    # Price plus premium, fees and shipping; a gift's carried-over basis; an inherited item's
    # value at death. A property's improvements add to it (Improvement).
    Column("costBasis", Cents, nullable=False),
    Column("quantity", Dec, nullable=False, server_default=text("'1'")),
    Column("location", Text),  # where it is kept
    Column("serial", Text),  # a serial, certificate or VIN
    Column("condition", Text),  # condition or grade
    Column("insuredValue", Cents),
    Column("policy", Text),
    Column("notes", Text),  # Markdown
    # How it is valued: spot (metals), dated valuations, or depreciation (vehicles).
    Column("valuation", Text, nullable=False, server_default=text("'valuations'")),
    # Spot: the metal, the weight of one unit and its unit, and the purity (.9999, .925).
    Column("metal", Text),
    Column("unitWeight", Dec),
    Column("weightUnit", Text),
    Column("purity", Dec),
    # Spot: the premium (+) or discount (−) expected when selling, in percent.
    Column("sellPremium", Dec, nullable=False, server_default=text("'0'")),
    # Depreciation: a yearly percentage from the cost basis.
    Column("depreciationRate", Dec),
    # Real estate.
    Column("address", Text),
    Column("closingCosts", Cents),
    Column("primaryResidence", Boolean, nullable=False, server_default=text("0")),
    # Used personally (a car, a home): a loss on its sale is not deductible (S8.13).
    Column("personalUse", Boolean, nullable=False, server_default=text("0")),
    # A sale: its day, proceeds and fees.
    Column("soldOn", Day),
    Column("proceeds", Cents),
    Column("saleFees", Cents),
    Column("createdById", Text, ForeignKey("User.id")),
    CheckConstraint("acquiredHow IN ('bought', 'gift', 'inherited')", name="acquired_how"),
    CheckConstraint("valuation IN ('spot', 'valuations', 'depreciation')", name="valuation"),
    CheckConstraint(
        "metal IS NULL OR metal IN ('gold', 'silver', 'platinum', 'palladium')", name="metal"
    ),
    CheckConstraint("weightUnit IS NULL OR weightUnit IN ('ozt', 'g', 'kg')", name="weight_unit"),
    CheckConstraint(
        "valuation != 'spot' OR (metal IS NOT NULL AND \"unitWeight\" IS NOT NULL "
        'AND "weightUnit" IS NOT NULL AND purity IS NOT NULL)',
        name="spot",
    ),
    CheckConstraint("quantity > 0", name="quantity"),
    CheckConstraint('("soldOn" IS NULL) = (proceeds IS NULL)', name="sale"),
    Index("ix_Item_accountId", "accountId"),
    seen=Seen.child("accountId"),
)

ItemValuation = record(
    "ItemValuation",
    "Valtn",
    Column("itemId", Text, ForeignKey("Item.id", ondelete="CASCADE"), nullable=False),
    Column("date", Day, nullable=False),
    Column("value", Cents, nullable=False),
    Column("source", Text, nullable=False, server_default=text("'estimate'")),
    Column("note", Text),
    Column("createdById", Text, ForeignKey("User.id")),
    CheckConstraint("source IN ('appraisal', 'sale', 'guide', 'estimate')", name="source"),
    Index("ix_ItemValuation_item", "itemId", "date"),
    seen=Seen.child("itemId"),
)

Improvement = record(
    "Improvement",
    "Imprv",
    Column("itemId", Text, ForeignKey("Item.id", ondelete="CASCADE"), nullable=False),
    Column("date", Day, nullable=False),
    Column("description", Text, nullable=False),
    Column("amount", Cents, nullable=False),
    Column("createdById", Text, ForeignKey("User.id")),
    Index("ix_Improvement_item", "itemId"),
    seen=Seen.child("itemId"),
)
