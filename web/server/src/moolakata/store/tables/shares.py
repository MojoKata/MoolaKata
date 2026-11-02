"""Shares (requirements S10.3–S10.6): an item of a shareable kind granted to a user or a
group, at an access class. One table per shareable kind, `<Table>Share`, made from the kind's
declaration (`Seen.root` or `Seen.rule` with a share kind), so a share's item is a real
foreign key; its class says what more than reading the grant gives (docs/schema.md §7).

The share tables follow the tables they share, so this module imports every other table
module first.
"""

from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Index, Table, Text, text

from . import (  # noqa: F401 - every table a share table may follow, first
    accounts,
    activity,
    alerts,
    assets,
    budgets,
    connector,
    core,
    education,
    giving,
    links,
    loans,
    options,
    people,
    prices,
    projections,
    receipts,
    sharing,
    taxes,
    users,
    wallets,
)
from ._base import Seen, metadata, record, unique_live

# The classes a share can grant, as the Share dialog offers them (S10.3): fixed rows, made by
# the migration that adds the table. A further class is a change of the requirements.
READ = "AcCls_00000000000000000000000001"
WRITE = "AcCls_00000000000000000000000002"
CLASSES = {"read": READ, "write": WRITE}
CLASS_NAMES = {v: k for k, v in CLASSES.items()}

AccessClass = record(
    "AccessClass",
    "AcCls",
    Column("name", Text, nullable=False),
    Column("writable", Boolean, nullable=False),
    Column("deletable", Boolean, nullable=False),
    Column("shareable", Boolean, nullable=False),
    Column("configurable", Boolean, nullable=False),
    # Every permission implies `writable` (§7.2).
    CheckConstraint(
        "writable OR NOT (deletable OR shareable OR configurable)", name="implies_writable"
    ),
    seen=Seen.household(creates="never"),  # fixed rows, made by a migration
)
unique_live(AccessClass, "name")


def _share_table(target: Table) -> Table:
    how: Seen = target.info["seen"]
    name = f"{target.name}Share"
    table = record(
        name,
        how.share_prefix,
        Column(
            "targetId", Text, ForeignKey(f"{target.name}.id", ondelete="CASCADE"), nullable=False
        ),
        Column("userId", Text, ForeignKey("User.id", ondelete="CASCADE")),
        Column("groupId", Text, ForeignKey("Group.id", ondelete="CASCADE")),
        Column("accessClassId", Text, ForeignKey("AccessClass.id"), nullable=False),
        Column("createdById", Text, ForeignKey("User.id")),
        # A share with a linked server's user: whether its receipts (and a tax book's document
        # files) cross too (S11.5.1), the same for every user of that server.
        Column("includeReceipts", Boolean, nullable=False, server_default=text("0")),
        CheckConstraint('("userId" IS NULL) != ("groupId" IS NULL)', name="one_grantee"),
        Index(f"ix_{name}_userId", "userId"),
        Index(f"ix_{name}_groupId", "groupId"),
        seen=Seen.shares(how.share),
    )
    # One grant of an item to each grantee (a NULL key never clashes).
    unique_live(table, "targetId", "userId")
    unique_live(table, "targetId", "groupId")
    return table


# Each shareable kind's share table, by its share kind (`account`, `gift-plan`, …).
SHARES: dict[str, Table] = {
    t.info["seen"].share: _share_table(t)
    for t in list(metadata.sorted_tables)
    if t.info["seen"].how in ("root", "rule") and t.info["seen"].share
}
