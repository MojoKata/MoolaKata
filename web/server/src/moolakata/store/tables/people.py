"""People and their relationships (requirements S10.10), each user's gift plans for them with
their occasions (S7.7), and the gifts given them or received from them (S7.8). A 529's
beneficiary is a person (S1.8.1)."""

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

from ..types import Cents, Day, UtcTimestamp
from ._base import Seen, pairs, record, unique_live

# Someone in the household's life: every user is one (User.personId), and so are people who
# never sign in. Seen by every local user unless `private` (S10.10.2).
Person = record(
    "Person",
    "Persn",
    # Who added it; none for a user's own person, made with the user.
    Column("ownerId", Text, ForeignKey("User.id")),
    Column("name", Text, nullable=False),
    Column("sex", Text, nullable=False),
    # The birthday: the year is optional, for their age.
    Column("birthMonth", Integer),
    Column("birthDay", Integer),
    Column("birthYear", Integer),
    Column("diedOn", Day),
    Column("private", Boolean, nullable=False, server_default=text("0")),
    CheckConstraint("sex IN ('male', 'female')", name="sex"),
    CheckConstraint('"birthMonth" IS NULL OR "birthMonth" BETWEEN 1 AND 12', name="birth_month"),
    CheckConstraint('"birthDay" IS NULL OR "birthDay" BETWEEN 1 AND 31', name="birth_day"),
    Index("ix_Person_name", "name"),
    seen=Seen.rule("person"),
)

# A dated link between two people (S10.10.4). A child runs from the parent (person1) to the
# child (person2); the others run both ways, with person1Id < person2Id.
Relationship = record(
    "Relationship",
    "Rltn",
    Column("person1Id", Text, ForeignKey("Person.id"), nullable=False),
    Column("person2Id", Text, ForeignKey("Person.id"), nullable=False),
    Column("relation", Text, nullable=False),
    Column("label", Text),  # family's: godmother
    Column("fromDate", Day),
    Column("toDate", Day),  # empty while it holds
    # A spouse's confirmations, by each of the two (S10.10.4): until both are set, the marriage
    # counts for gifts only. Empty for the other relations.
    Column("confirmed1At", UtcTimestamp),
    Column("confirmed2At", UtcTimestamp),
    CheckConstraint(
        "relation IN ('spouse', 'couple', 'child', 'friend', 'colleague', 'family')",
        name="relation",
    ),
    CheckConstraint('"person1Id" <> "person2Id"', name="two_people"),
    CheckConstraint('relation = \'child\' OR "person1Id" < "person2Id"', name="ordered"),
    CheckConstraint(
        '"toDate" IS NULL OR "fromDate" IS NULL OR "toDate" >= "fromDate"', name="dates"
    ),
    Index("ix_Relationship_person2Id", "person2Id"),
    seen=Seen.rule(),
)
unique_live(Relationship, "person1Id", "person2Id", "relation", "fromDate")

# One user's gift plan for a person (S7.7.1): their budget, lead time and notes, with the
# holidays and anniversaries they give for.
GiftPlan = record(
    "GiftPlan",
    "GfPln",
    Column("ownerId", Text, ForeignKey("User.id"), nullable=False),
    Column("personId", Text, ForeignKey("Person.id", ondelete="CASCADE"), nullable=False),
    Column("giftBudget", Cents),  # a year
    Column("leadDays", Integer, nullable=False, server_default=text("14")),
    Column("notes", Text),
    CheckConstraint('"leadDays" >= 0', name="lead_days"),
    Index("ix_GiftPlan_personId", "personId"),
    seen=Seen.rule("gift-plan"),
)
unique_live(GiftPlan, "ownerId", "personId")

# A dated occasion in a gift plan: an anniversary, a holiday they get gifts for (its date from
# the shipped list), or a custom one; each may have its own gift budget (S7.7.1).
Occasion = record(
    "Occasion",
    "Occsn",
    Column("giftPlanId", Text, ForeignKey("GiftPlan.id", ondelete="CASCADE"), nullable=False),
    Column("kind", Text, nullable=False),
    Column("name", Text),  # an anniversary's or a custom occasion's
    Column("holiday", Text),  # a shipped holiday's key
    Column("month", Integer),
    Column("day", Integer),
    Column("year", Integer),  # an anniversary's first year, for its count
    Column("budget", Cents),
    CheckConstraint("kind IN ('anniversary', 'holiday', 'custom')", name="kind"),
    CheckConstraint("(kind = 'holiday') = (holiday IS NOT NULL)", name="holiday"),
    CheckConstraint(
        "kind = 'holiday' OR (month BETWEEN 1 AND 12 AND day BETWEEN 1 AND 31)", name="date"
    ),
    Index("ix_Occasion_giftPlanId", "giftPlanId"),
    seen=Seen.child("giftPlanId"),
)

# A gift, from idea to given, for one or more people and an occasion of a year; or one received
# from someone (S7.8). Its cost is linked to a transaction or typed.
Gift = record(
    "Gift",
    "Gift",
    Column("ownerId", Text, ForeignKey("User.id"), nullable=False),
    Column("occasion", Text),  # birthday, holiday:<key>, occasion:<id>; none for an idea
    Column("occasionYear", Integer),
    Column("description", Text, nullable=False),
    Column("status", Text, nullable=False, server_default=text("'idea'")),
    Column("cost", Cents),
    Column("transactionId", Text, ForeignKey("Transaction.id", ondelete="SET NULL")),
    Column("store", Text),  # where it was bought
    Column("link", Text),
    Column("notes", Text),
    Column("cash", Boolean, nullable=False, server_default=text("0")),  # money, for Form 709
    Column("thankYou", Boolean, nullable=False, server_default=text("0")),  # a received one's
    CheckConstraint("status IN ('idea', 'planned', 'bought', 'given', 'received')", name="status"),
    Index("ix_Gift_ownerId", "ownerId"),
    seen=Seen.rule(),
)

# Who a gift is for, or for a received one, who it came from.
GiftPersons = pairs(
    "GiftPersons",
    Column("giftId", Text, ForeignKey("Gift.id", ondelete="CASCADE"), nullable=False),
    Column("personId", Text, ForeignKey("Person.id"), nullable=False),
    PrimaryKeyConstraint("giftId", "personId"),
    Index("ix_GiftPersons_personId", "personId"),
)
