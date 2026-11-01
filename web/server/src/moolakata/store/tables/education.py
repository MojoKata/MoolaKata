"""529 plans (requirements S1.8): a 529 account's plan and beneficiary, who each contribution
came from, and the qualified expenses its withdrawals are matched with."""

from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Index, Integer, Text, text

from ..types import Cents, Day
from ._base import Seen, record, unique_live

EducationPlan = record(
    "EducationPlan",
    "EdPln",
    Column("accountId", Text, ForeignKey("Account.id", ondelete="CASCADE"), nullable=False),
    Column("planState", Text),  # the sponsoring state: Utah, Nevada…
    Column("planName", Text),  # my529, Bright Start…
    Column("beneficiaryId", Text, ForeignKey("Person.id")),  # a person (S10.10)
    Column("openedOn", Day),
    Column("stateDeduction", Cents),  # what the owner expects a year, typed (S8.18)
    seen=Seen.child("accountId"),
)
unique_live(EducationPlan, "accountId")

# Who a contribution (a deposit into a 529) came from: the owner (none set) or a person; a
# five-year election spreads it over five years of gift exclusions (S1.8.2).
Contribution = record(
    "Contribution",
    "Cntrb",
    Column("transactionId", Text, ForeignKey("Transaction.id", ondelete="CASCADE"), nullable=False),
    Column("fromPersonId", Text, ForeignKey("Person.id")),
    Column("fiveYear", Boolean, nullable=False, server_default=text("0")),
    seen=Seen.child("transactionId"),
)
unique_live(Contribution, "transactionId")

# A qualified education expense a 529's withdrawals are matched with (S1.8.3).
QualifiedExpense = record(
    "QualifiedExpense",
    "QExpn",
    Column("accountId", Text, ForeignKey("Account.id", ondelete="CASCADE"), nullable=False),
    Column("date", Day, nullable=False),
    Column("year", Integer, nullable=False),  # the tax year it counts in
    Column("kind", Text, nullable=False),
    Column("description", Text),
    Column("amount", Cents, nullable=False),
    Column("transactionId", Text, ForeignKey("Transaction.id")),  # how it was paid, if recorded
    CheckConstraint(
        "kind IN ('tuition', 'room-board', 'books', 'computer', 'k12', 'apprenticeship', "
        "'student-loan')",
        name="kind",
    ),
    CheckConstraint("amount > 0", name="amount"),
    Index("ix_QualifiedExpense_account", "accountId", "year"),
    seen=Seen.child("accountId"),
)
