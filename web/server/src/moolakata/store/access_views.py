"""The `<Table>Access` views (docs/schema.md §7): who reads each record, and what more they may do.

Every table says how it is seen (`Seen`, in its `info`). A view has one row per record and user
who reads it, and four 0/1 columns: `writable` (changes what it holds), `deletable`,
`shareable` (changes its sharing) and `configurable` (its settings, what it covers, its
secrets). Every permission implies `writable`. Only live records have rows: the views read the
Effective views (§4.2). Roots, children, per-user tables and admin data have generated views;
the rest are written here by hand, one function each, citing their requirement.

A few base views hold what every rule uses once: `AccessUser` (the active, live users),
`AccessMember` (live memberships of active groups), `AccessAdmin` (the admins) and `ShareLevel`
(each user's share of each item, directly or through a group, at its highest).
"""

import re
from collections.abc import Callable
from functools import cache
from graphlib import TopologicalSorter

from sqlalchemy import Boolean, Column, MetaData, Table, Text

from .tables._base import Seen
from .views import view_name

PERMISSIONS = ("writable", "deletable", "shareable", "configurable")
SUFFIX = "Access"
_views = MetaData()


def access_name(table: str) -> str:
    return f"{table}{SUFFIX}"


def seen(table: Table) -> Seen:
    return table.info["seen"]


@cache
def access_table(table: Table) -> Table:
    """The view as a selectable, for Core and ORM joins."""
    return Table(
        access_name(table.name),
        _views,
        Column("targetId", Text, primary_key=True),
        Column("userId", Text, primary_key=True),
        *(Column(p, Boolean) for p in PERMISSIONS),
    )


def has_view(table: Table) -> bool:
    return seen(table).how in ("root", "child", "rule", "per-user", "admin")


def _src(table: Table, alias: str) -> tuple[str, str]:
    """FROM and WHERE for a table's live rows: its Effective view, or the table itself when it
    is never soft-deleted."""
    if table.info.get("softDelete"):
        return f'"{view_name(table.name)}" AS {alias}', f'NOT {alias}."effectiveDeleted"'
    return f'"{table.name}" AS {alias}', "1"


def _cols(*values: str) -> str:
    names = ("targetId", "userId", *PERMISSIONS)
    return ", ".join(f'{v} AS "{n}"' for v, n in zip(values, names, strict=True))


def _collapse(body: str) -> str:
    """One row per record and user, the highest of each permission over every path."""
    perms = ", ".join(f'max("{p}") AS "{p}"' for p in PERMISSIONS)
    return f'SELECT "targetId", "userId", {perms} FROM (\n{body}\n) GROUP BY "targetId", "userId"'


def _view(name: str, select: str) -> str:
    return f'CREATE VIEW "{name}" AS\n{select}'


# ---- Generated views ----


def _root(table: Table, share: str) -> str:
    """S10.3: the owner holds everything; a share gives read or write, never more."""
    src, live = _src(table, "t")
    owner = (
        f"SELECT {_cols('t.id', 't."ownerId"', '1', '1', '1', '1')}\nFROM {src}\n"
        f'JOIN "AccessUser" AS u ON u."userId" = t."ownerId" AND u.local\nWHERE {live}'
    )
    shared = (
        f"SELECT {_cols('t.id', 's."userId"', 's.writable', '0', '0', '0')}\nFROM {src}\n"
        f'JOIN "ShareLevel" AS s ON s.kind = \'{share}\' AND s."itemId" = t.id\nWHERE {live}'
    )
    return _collapse(f"{owner}\nUNION ALL\n{shared}")


def _child(table: Table, parent: Table, key: str) -> str:
    """Seen as its parent is; deleting it is a change of the parent (S10.3)."""
    src, live = _src(table, "c")
    return (
        f"SELECT {_cols('c.id', 'p."userId"', 'p.writable', 'p.writable', '0', 'p.configurable')}"
        f'\nFROM {src}\nJOIN "{access_name(parent.name)}" AS p ON p."targetId" = c."{key}"'
        f"\nWHERE {live}"
    )


def _per_user(table: Table, key: str, configurable: bool) -> str:
    src, live = _src(table, "t")
    cfg = "1" if configurable else "0"
    return (
        f"SELECT {_cols('t.id', f't."{key}"', '1', '1', '0', cfg)}\nFROM {src}\n"
        f'JOIN "AccessUser" AS u ON u."userId" = t."{key}" AND u.local\nWHERE {live}'
    )


def _admin(table: Table) -> str:
    src, live = _src(table, "t")
    return (
        f"SELECT {_cols('t.id', 'a."userId"', '1', '1', '1', '1')}\nFROM {src}\n"
        f'CROSS JOIN "AccessAdmin" AS a\nWHERE {live}'
    )


# ---- Base views ----


def _access_user() -> str:
    """The users who hold anything: live and active (S10.1.7; a linked server's user deactivated
    there is inactive here, S10.3.3)."""
    return (
        'SELECT u.id AS "userId", u."linkId" IS NULL AS local, u."linkId" AS "linkId", '
        'u."personId" AS "personId"\nFROM "UserEffective" AS u\n'
        'WHERE NOT u."effectiveDeleted" AND u.active'
    )


def _access_member() -> str:
    """Live memberships of active, live groups, for active users (S10.5)."""
    return (
        'SELECT m."userId" AS "userId", m."groupId" AS "groupId", g."builtIn" AS "builtIn"\n'
        'FROM "UserGroupsEffective" AS m\n'
        'JOIN "GroupEffective" AS g ON g.id = m."groupId" AND NOT g."effectiveDeleted" '
        "AND g.active\n"
        'JOIN "AccessUser" AS u ON u."userId" = m."userId" AND u.local\n'
        'WHERE NOT m."effectiveDeleted"'
    )


def _access_admin() -> str:
    """Being an admin is a live membership of the active Admins group (S10.1.8)."""
    return 'SELECT DISTINCT "userId" FROM "AccessMember" WHERE "builtIn" = \'admins\''


def _share_level() -> str:
    """Each user's share of each item, directly or through a group, at its highest (S10.3,
    S10.5). A linked server's user only ever reads (S10.3.3)."""
    return (
        'SELECT kind, "itemId", "userId", max(writable) AS writable, '
        'max("includeReceipts") AS "includeReceipts" FROM (\n'
        'SELECT s.kind, s."itemId", s."userId", s.level = \'write\' AND u.local AS writable, '
        's."includeReceipts"\nFROM "ShareEffective" AS s\n'
        'JOIN "AccessUser" AS u ON u."userId" = s."userId"\nWHERE NOT s."effectiveDeleted"\n'
        "UNION ALL\n"
        'SELECT s.kind, s."itemId", m."userId", s.level = \'write\', s."includeReceipts"\n'
        'FROM "ShareEffective" AS s\nJOIN "AccessMember" AS m ON m."groupId" = s."groupId"\n'
        'WHERE NOT s."effectiveDeleted"\n'
        ') GROUP BY kind, "itemId", "userId"'
    )


# ---- Written by hand ----


def _tax_book() -> str:
    """S8.14.1: the plain rule, and its accepted filers, who hold it as its owners."""
    body = _root_body("TaxBook", "tax-book")
    filers = (
        f"SELECT {_cols('b.id', 'f."userId"', '1', '1', '1', '1')}\n"
        'FROM "TaxBookEffective" AS b\n'
        'JOIN "TaxBookFilerEffective" AS f ON f."bookId" = b.id AND NOT f."effectiveDeleted" '
        'AND f."acceptedAt" IS NOT NULL\n'
        'JOIN "AccessUser" AS u ON u."userId" = f."userId" AND u.local\n'
        'WHERE NOT b."effectiveDeleted"'
    )
    return _collapse(f"{body}\nUNION ALL\n{filers}")


def _root_body(table: str, share: str) -> str:
    owner = (
        f"SELECT {_cols('t.id', 't."ownerId"', '1', '1', '1', '1')}\n"
        f'FROM "{view_name(table)}" AS t\n'
        'JOIN "AccessUser" AS u ON u."userId" = t."ownerId" AND u.local\n'
        'WHERE NOT t."effectiveDeleted"'
    )
    shared = (
        f"SELECT {_cols('t.id', 's."userId"', 's.writable', '0', '0', '0')}\n"
        f'FROM "{view_name(table)}" AS t\n'
        f'JOIN "ShareLevel" AS s ON s.kind = \'{share}\' AND s."itemId" = t.id\n'
        'WHERE NOT t."effectiveDeleted"'
    )
    return f"{owner}\nUNION ALL\n{shared}"


def _person() -> str:
    """S10.10.2: the person's own user, admins, and whoever added them until they join (or
    for good, when they are a linked server's user) hold them; every local user reads one who
    isn't private; a share of them, or of a gift plan for them, shows them, read only."""
    holders = (
        f"SELECT {_cols('p.id', 'u."userId"', '1', '1', '1', '1')}\n"
        'FROM "PersonEffective" AS p\n'
        'JOIN "AccessUser" AS u ON u.local AND (\n'
        '  u."personId" = p.id\n'
        '  OR u."userId" IN (SELECT "userId" FROM "AccessAdmin")\n'
        '  OR (u."userId" = p."ownerId" AND NOT EXISTS (\n'
        '    SELECT 1 FROM "UserEffective" AS x WHERE x."personId" = p.id\n'
        '    AND NOT x."effectiveDeleted" AND x."linkId" IS NULL)))\n'
        'WHERE NOT p."effectiveDeleted"'
    )
    public = (
        f"SELECT {_cols('p.id', 'u."userId"', '0', '0', '0', '0')}\n"
        'FROM "PersonEffective" AS p\nJOIN "AccessUser" AS u ON u.local\n'
        'WHERE NOT p."effectiveDeleted" AND NOT p.private'
    )
    shared = (
        f"SELECT {_cols('p.id', 's."userId"', '0', '0', '0', '0')}\n"
        'FROM "PersonEffective" AS p\n'
        'JOIN "ShareLevel" AS s ON s.kind = \'person\' AND s."itemId" = p.id\n'
        'WHERE NOT p."effectiveDeleted"'
    )
    through_plans = (
        f"SELECT {_cols('p.id', 's."userId"', '0', '0', '0', '0')}\n"
        'FROM "PersonEffective" AS p\n'
        'JOIN "GiftPlanEffective" AS g ON g."personId" = p.id AND NOT g."effectiveDeleted"\n'
        'JOIN "ShareLevel" AS s ON s.kind = \'gift-plan\' AND s."itemId" = g.id\n'
        'WHERE NOT p."effectiveDeleted"'
    )
    return _collapse("\nUNION ALL\n".join((holders, public, shared, through_plans)))


def _gift_plan() -> str:
    """S7.8.5, S10.3: the plain rule, while its person is there; a plan for a user of a linked
    server never reaches that server's users."""
    return (
        "SELECT a.* FROM (\n"
        + _collapse(_root_body("GiftPlan", "gift-plan"))
        + '\n) AS a\nJOIN "GiftPlanEffective" AS g ON g.id = a."targetId"\n'
        'JOIN "PersonEffective" AS p ON p.id = g."personId" AND NOT p."effectiveDeleted"\n'
        'JOIN "AccessUser" AS u ON u."userId" = a."userId"\n'
        "WHERE u.local OR NOT EXISTS (\n"
        '  SELECT 1 FROM "AccessUser" AS x WHERE x."linkId" = u."linkId" '
        'AND x."personId" = g."personId")'
    )


def _for_recipient(gift: str, user: str) -> str:
    """A gift not yet received is for someone who never sees it (S7.8.5)."""
    return (
        f"NOT ({gift}.status <> 'received' AND EXISTS (\n"
        f'  SELECT 1 FROM "GiftPersonsEffective" AS w WHERE w."giftId" = {gift}.id\n'
        f'  AND NOT w."effectiveDeleted" AND w."personId" = {user}."personId"))'
    )


def _gift() -> str:
    """S7.8.5: its owner holds it; others see it through the owner's gift plans for its
    people, reading when any is theirs and changing it when all are writable; the person it is
    for never sees it until it is received."""
    owner = (
        f"SELECT {_cols('g.id', 'g."ownerId"', '1', '1', '0', '0')}\n"
        'FROM "GiftEffective" AS g\n'
        'JOIN "AccessUser" AS u ON u."userId" = g."ownerId" AND u.local\n'
        f'WHERE NOT g."effectiveDeleted" AND {_for_recipient("g", "u")}'
    )
    whole = (
        'CASE WHEN count(DISTINCT gp."personId") = (SELECT count(*) FROM "GiftPersonsEffective"'
        ' AS n WHERE n."giftId" = g.id AND NOT n."effectiveDeleted") THEN min(a.writable)'
        " ELSE 0 END"
    )
    others = (
        f"SELECT {_cols('g.id', 'a."userId"', whole, whole, '0', '0')}\n"
        'FROM "GiftEffective" AS g\n'
        'JOIN "GiftPersonsEffective" AS gp ON gp."giftId" = g.id AND NOT gp."effectiveDeleted"\n'
        'JOIN "GiftPlanEffective" AS pl ON pl."ownerId" = g."ownerId" '
        'AND pl."personId" = gp."personId" AND NOT pl."effectiveDeleted"\n'
        'JOIN "GiftPlanAccess" AS a ON a."targetId" = pl.id AND a."userId" <> g."ownerId"\n'
        'JOIN "AccessUser" AS u ON u."userId" = a."userId"\n'
        f'WHERE NOT g."effectiveDeleted" AND {_for_recipient("g", "u")}\n'
        'GROUP BY g.id, a."userId"'
    )
    return f"{owner}\nUNION ALL\n{others}"


def _donation() -> str:
    """S7.9.1: its owner's; read by whoever reads the owner's giving plan for its year."""
    owner = (
        f"SELECT {_cols('d.id', 'd."ownerId"', '1', '1', '0', '0')}\n"
        'FROM "DonationEffective" AS d\n'
        'JOIN "AccessUser" AS u ON u."userId" = d."ownerId" AND u.local\n'
        'WHERE NOT d."effectiveDeleted"'
    )
    readers = (
        f"SELECT DISTINCT {_cols('d.id', 'a."userId"', '0', '0', '0', '0')}\n"
        'FROM "DonationEffective" AS d\n'
        'JOIN "GivingPlanEffective" AS p ON p."ownerId" = d."ownerId" '
        'AND p.year = CAST(substr(d.date, 1, 4) AS INTEGER) AND NOT p."effectiveDeleted"\n'
        'JOIN "GivingPlanAccess" AS a ON a."targetId" = p.id AND a."userId" <> d."ownerId"\n'
        'WHERE NOT d."effectiveDeleted"'
    )
    return f"{owner}\nUNION ALL\n{readers}"


def _organisation() -> str:
    """S7.9.1: its owner's; read by whoever reads one of the owner's giving plans."""
    owner = (
        f"SELECT {_cols('o.id', 'o."ownerId"', '1', '1', '0', '0')}\n"
        'FROM "OrganisationEffective" AS o\n'
        'JOIN "AccessUser" AS u ON u."userId" = o."ownerId" AND u.local\n'
        'WHERE NOT o."effectiveDeleted"'
    )
    readers = (
        f"SELECT DISTINCT {_cols('o.id', 'a."userId"', '0', '0', '0', '0')}\n"
        'FROM "OrganisationEffective" AS o\n'
        'JOIN "GivingPlanEffective" AS p ON p."ownerId" = o."ownerId" '
        'AND NOT p."effectiveDeleted"\n'
        'JOIN "GivingPlanAccess" AS a ON a."targetId" = p.id AND a."userId" <> o."ownerId"\n'
        'WHERE NOT o."effectiveDeleted"'
    )
    return f"{owner}\nUNION ALL\n{readers}"


# What a receipt's link of each kind names, and the share that carries receipts across a link
# with it (S11.5): the account it is in, or the gift's or donation's plan.
_TARGETS = {
    "transaction": ("Transaction", '"TransactionEffective"', "accountId"),
    "account": ("Account", None, None),
    "item": ("Item", '"ItemEffective"', "accountId"),
    "expense": ("QualifiedExpense", '"QualifiedExpenseEffective"', "accountId"),
}


def _receipt_target() -> str:
    """Each live link of a receipt, with each user who reads what it names, whether they may
    change that, and whether it carries receipts to them (always here; across a link only
    with *Include receipts*, S11.5)."""
    parts = []
    for kind, (table, src, key) in _TARGETS.items():
        account = 'ln."itemId"' if key is None else f'x."{key}"'
        join = "" if key is None else f'JOIN {src} AS x ON x.id = ln."itemId"\n'
        parts.append(
            'SELECT ln.id AS "linkId", ln."receiptId" AS "receiptId", t."userId" AS "userId", '
            "t.writable AS writable,\n"
            f"  u.local OR EXISTS (SELECT 1 FROM \"ShareLevel\" AS s WHERE s.kind = 'account' "
            f'AND s."itemId" = {account} AND s."userId" = t."userId" AND s."includeReceipts")'
            " AS carried\n"
            'FROM "ReceiptLinkEffective" AS ln\n'
            f"{join}"
            f'JOIN "{access_name(table)}" AS t ON t."targetId" = ln."itemId"\n'
            'JOIN "AccessUser" AS u ON u."userId" = t."userId"\n'
            f"WHERE NOT ln.\"effectiveDeleted\" AND ln.kind = '{kind}'"
        )
    parts.append(
        'SELECT ln.id, ln."receiptId", t."userId", t.writable,\n'
        '  u.local OR EXISTS (SELECT 1 FROM "GiftPersonsEffective" AS gp\n'
        '    JOIN "GiftPlanEffective" AS pl ON pl."personId" = gp."personId" '
        'AND pl."ownerId" = g."ownerId"\n'
        '    JOIN "ShareLevel" AS s ON s.kind = \'gift-plan\' AND s."itemId" = pl.id '
        'AND s."userId" = t."userId" AND s."includeReceipts"\n'
        '    WHERE gp."giftId" = g.id AND NOT gp."effectiveDeleted")\n'
        'FROM "ReceiptLinkEffective" AS ln\nJOIN "GiftEffective" AS g ON g.id = ln."itemId"\n'
        'JOIN "GiftAccess" AS t ON t."targetId" = ln."itemId"\n'
        'JOIN "AccessUser" AS u ON u."userId" = t."userId"\n'
        "WHERE NOT ln.\"effectiveDeleted\" AND ln.kind = 'gift'"
    )
    parts.append(
        'SELECT ln.id, ln."receiptId", t."userId", t.writable,\n'
        '  u.local OR EXISTS (SELECT 1 FROM "GivingPlanEffective" AS pl\n'
        '    JOIN "ShareLevel" AS s ON s.kind = \'giving-plan\' AND s."itemId" = pl.id '
        'AND s."userId" = t."userId" AND s."includeReceipts"\n'
        '    WHERE pl."ownerId" = d."ownerId" '
        "AND pl.year = CAST(substr(d.date, 1, 4) AS INTEGER))\n"
        'FROM "ReceiptLinkEffective" AS ln\nJOIN "DonationEffective" AS d ON d.id = ln."itemId"\n'
        'JOIN "DonationAccess" AS t ON t."targetId" = ln."itemId"\n'
        'JOIN "AccessUser" AS u ON u."userId" = t."userId"\n'
        "WHERE NOT ln.\"effectiveDeleted\" AND ln.kind = 'donation'"
    )
    return "\nUNION ALL\n".join(parts)


def _receipt() -> str:
    """S9.6: its owner's; read by whoever reads what it is kept with, and changed (attached,
    filled in) by whoever may change that; a tax document's file by the book's filers
    (S8.16). Only its owner deletes it."""
    owner = (
        f"SELECT {_cols('r.id', 'r."ownerId"', '1', '1', '0', '0')}\n"
        'FROM "ReceiptEffective" AS r\n'
        'JOIN "AccessUser" AS u ON u."userId" = r."ownerId" AND u.local\n'
        'WHERE NOT r."effectiveDeleted"'
    )
    kept = (
        f"SELECT {_cols('r.id', 't."userId"', 't.writable', '0', '0', '0')}\n"
        'FROM "ReceiptEffective" AS r\n'
        'JOIN "ReceiptTarget" AS t ON t."receiptId" = r.id AND t.carried\n'
        'WHERE NOT r."effectiveDeleted"'
    )
    documents = (
        f"SELECT {_cols('r.id', 'a."userId"', '0', '0', '0', '0')}\n"
        'FROM "ReceiptEffective" AS r\n'
        'JOIN "TaxDocumentEffective" AS d ON d."receiptId" = r.id AND NOT d."effectiveDeleted"\n'
        'JOIN "TaxDocumentAccess" AS a ON a."targetId" = d.id AND a.configurable\n'
        'WHERE NOT r."effectiveDeleted"'
    )
    return _collapse("\nUNION ALL\n".join((owner, kept, documents)))


def _receipt_link() -> str:
    """S9.3: a link is seen with the receipt by whoever reads what it names; whoever may
    change that detaches it."""
    return _collapse(
        f"SELECT {_cols('t."linkId"', 't."userId"', 't.writable', 't.writable', '0', '0')}\n"
        'FROM "ReceiptTarget" AS t\n'
        'JOIN "ReceiptAccess" AS r ON r."targetId" = t."receiptId" AND r."userId" = t."userId"'
    )


def _reimbursement() -> str:
    """S2: seen from either side's transaction; paired and unpaired by whoever may change
    both."""
    sides = (
        'SELECT r.id AS rid, t."userId" AS "userId", t.writable AS writable\n'
        'FROM "ReimbursementEffective" AS r\n'
        'JOIN "TransactionAccess" AS t ON t."targetId" = r."spendingId"\n'
        'WHERE NOT r."effectiveDeleted"\n'
        "UNION ALL\n"
        'SELECT r.id, t."userId", t.writable\nFROM "ReimbursementEffective" AS r\n'
        'JOIN "TransactionAccess" AS t ON t."targetId" = r."paybackId"\n'
        'WHERE NOT r."effectiveDeleted"'
    )
    both = "CASE WHEN count(*) = 2 THEN min(writable) ELSE 0 END"
    return (
        f"SELECT {_cols('rid', '"userId"', both, both, '0', '0')}\nFROM (\n{sides}\n)\n"
        'GROUP BY rid, "userId"'
    )


def _transfer_match() -> str:
    """S1.6: a pair proposed to its owner, while both transactions are theirs to read;
    confirmed or turned down when both are theirs to change."""
    both = "o.writable AND i.writable"
    return (
        f"SELECT {_cols('m.id', 'm."ownerId"', both, both, '0', '0')}\n"
        'FROM "TransferMatchEffective" AS m\n'
        'JOIN "TransactionAccess" AS o ON o."targetId" = m."outId" AND o."userId" = m."ownerId"\n'
        'JOIN "TransactionAccess" AS i ON i."targetId" = m."inId" AND i."userId" = m."ownerId"\n'
        'WHERE NOT m."effectiveDeleted"'
    )


def _relationship() -> str:
    """S10.10.4: seen by whoever reads both people; added and changed by one of the two, or an
    admin."""
    mine = (
        'u."personId" IN (r."person1Id", r."person2Id") '
        'OR u."userId" IN (SELECT "userId" FROM "AccessAdmin")'
    )
    return (
        f"SELECT {_cols('r.id', 'a."userId"', mine, mine, '0', '0')}\n"
        'FROM "RelationshipEffective" AS r\n'
        'JOIN "PersonAccess" AS a ON a."targetId" = r."person1Id"\n'
        'JOIN "PersonAccess" AS b ON b."targetId" = r."person2Id" AND b."userId" = a."userId"\n'
        'JOIN "AccessUser" AS u ON u."userId" = a."userId"\n'
        'WHERE NOT r."effectiveDeleted"'
    )


def _wash_sale() -> str:
    """S3.8: part of its sale's figures, seen with the sale; worked out, never changed."""
    return (
        f"SELECT {_cols('w.id', 't."userId"', '0', '0', '0', '0')}\n"
        'FROM "WashSale" AS w\nJOIN "TransactionAccess" AS t ON t."targetId" = w."saleId"'
    )


def _alert() -> str:
    """S12.11.2: one's own; and for an admin the admins' alerts, but those they hold as the
    owner of what failed. Read only: what a user does with one is their AlertState."""
    own = (
        f"SELECT {_cols('a.id', 'a."userId"', '0', '0', '0', '0')}\n"
        'FROM "Alert" AS a\nJOIN "AccessUser" AS u ON u."userId" = a."userId" AND u.local'
    )
    admins = (
        f"SELECT {_cols('a.id', 'm."userId"', '0', '0', '0', '0')}\n"
        'FROM "Alert" AS a\nCROSS JOIN "AccessAdmin" AS m\n'
        'WHERE a."userId" IS NULL AND NOT EXISTS (\n'
        '  SELECT 1 FROM "Alert" AS x WHERE x."userId" = m."userId"\n'
        '  AND x."causeKey" = a."causeKey" || \':\' || m."userId"\n'
        '  AND x."openedAt" IS NOT NULL AND x."resolvedAt" IS a."resolvedAt")'
    )
    return f"{own}\nUNION ALL\n{admins}"


def _import_mapping() -> str:
    """S1.3.2: the owner's; read by whoever imports into one of the owner's accounts, as the
    import uses the account owner's mappings."""
    owner = (
        f"SELECT {_cols('m.id', 'm."ownerId"', '1', '1', '0', '0')}\n"
        'FROM "ImportMappingEffective" AS m\n'
        'JOIN "AccessUser" AS u ON u."userId" = m."ownerId" AND u.local\n'
        'WHERE NOT m."effectiveDeleted"'
    )
    writers = (
        f"SELECT DISTINCT {_cols('m.id', 'a."userId"', '0', '0', '0', '0')}\n"
        'FROM "ImportMappingEffective" AS m\n'
        'JOIN "AccountEffective" AS t ON t."ownerId" = m."ownerId" AND NOT t."effectiveDeleted"\n'
        'JOIN "AccountAccess" AS a ON a."targetId" = t.id AND a.writable '
        'AND a."userId" <> m."ownerId"\n'
        'WHERE NOT m."effectiveDeleted"'
    )
    return f"{owner}\nUNION ALL\n{writers}"


def _tax_book_filer() -> str:
    """S8.14.1: seen with its tax book; the user it names reads and answers it before they
    accept."""
    book = _child_body("TaxBookFiler", "TaxBook", "bookId")
    invited = (
        f"SELECT {_cols('f.id', 'f."userId"', '1', '0', '0', '0')}\n"
        'FROM "TaxBookFilerEffective" AS f\n'
        'JOIN "AccessUser" AS u ON u."userId" = f."userId" AND u.local\n'
        'WHERE NOT f."effectiveDeleted" AND f."acceptedAt" IS NULL'
    )
    return _collapse(f"{book}\nUNION ALL\n{invited}")


def _child_body(table: str, parent: str, key: str) -> str:
    return (
        f"SELECT {_cols('c.id', 'p."userId"', 'p.writable', 'p.writable', '0', 'p.configurable')}"
        f'\nFROM "{view_name(table)}" AS c\n'
        f'JOIN "{access_name(parent)}" AS p ON p."targetId" = c."{key}"\n'
        'WHERE NOT c."effectiveDeleted"'
    )


# An Activity entry's subject, by its kind: the root whose view says who reads it (S10.8).
SUBJECTS = {
    "account": "Account",
    "portfolio": "Portfolio",
    "budget": "Budget",
    "person": "Person",
    "gift-plan": "GiftPlan",
    "giving-plan": "GivingPlan",
    "tax-book": "TaxBook",
    "projection": "Projection",
}


def _activity() -> str:
    """S10.8: the changes concerning a user: those they made or own, those about what they
    read, a share of theirs removed, and for admins those about users, groups, links,
    Settings and keys. Read only."""
    zero = ("0", "0", "0", "0")
    mine = (
        f'SELECT {_cols("e.id", 'u."userId"', *zero)}\nFROM "Activity" AS e\n'
        'JOIN "AccessUser" AS u ON u.local AND u."userId" IN (e."actorId", e."ownerId")'
    )
    subjects = [
        f'SELECT {_cols("e.id", 'a."userId"', *zero)}\nFROM "Activity" AS e\n'
        f'JOIN "{access_name(table)}" AS a ON a."targetId" = e."subjectId"\n'
        f"WHERE e.\"subjectKind\" = '{kind}'"
        for kind, table in SUBJECTS.items()
    ]
    removed = (
        f'SELECT {_cols("e.id", 'u."userId"', *zero)}\nFROM "Activity" AS e\n'
        'JOIN "AccessUser" AS u ON u.local AND (\n'
        "  json_extract(e.detail, '$.granteeId') = u.\"userId\"\n"
        "  OR json_extract(e.detail, '$.granteeId') IN (\n"
        '    SELECT "groupId" FROM "AccessMember" AS m WHERE m."userId" = u."userId"))\n'
        "WHERE e.kind = 'share.removed'"
    )
    admins = (
        f'SELECT {_cols("e.id", 'm."userId"', *zero)}\nFROM "Activity" AS e\n'
        'CROSS JOIN "AccessAdmin" AS m\n'
        'WHERE e."forAdmins" AND (e."subjectKind" IS NULL '
        "OR e.\"subjectKind\" IN ('user', 'group', 'link'))"
    )
    return _collapse("\nUNION ALL\n".join((mine, *subjects, removed, admins)))


def _user() -> str:
    """S10.4, S11.3: every active user reads this household's active users, as a linked server
    is sent them; local users also read the linked servers' active users; admins read every
    user and change them; each user changes their own (Profile)."""
    zero = ("0", "0", "0", "0")
    local = (
        f"SELECT {_cols('x."userId"', 'u."userId"', *zero)}\n"
        'FROM "AccessUser" AS x\nJOIN "AccessUser" AS u ON x.local'
    )
    remote = (
        f"SELECT {_cols('x."userId"', 'u."userId"', *zero)}\n"
        'FROM "AccessUser" AS x\nJOIN "AccessUser" AS u ON NOT x.local AND u.local'
    )
    admins = (
        f"SELECT {_cols('x.id', 'm."userId"', '1', '1', '0', '0')}\n"
        'FROM "UserEffective" AS x\nCROSS JOIN "AccessAdmin" AS m\n'
        'WHERE NOT x."effectiveDeleted"'
    )
    own = (
        f"SELECT {_cols('u."userId"', 'u."userId"', '1', '0', '0', '0')}\n"
        'FROM "AccessUser" AS u WHERE u.local'
    )
    return _collapse("\nUNION ALL\n".join((local, remote, admins, own)))


def _group() -> str:
    """S10.4: every local user reads the active groups; admins read and change them all."""
    readers = (
        f"SELECT {_cols('g.id', 'u."userId"', '0', '0', '0', '0')}\n"
        'FROM "GroupEffective" AS g\nJOIN "AccessUser" AS u ON u.local\n'
        'WHERE NOT g."effectiveDeleted" AND g.active'
    )
    admins = (
        f"SELECT {_cols('g.id', 'm."userId"', '1', '1', '0', '0')}\n"
        'FROM "GroupEffective" AS g\nCROSS JOIN "AccessAdmin" AS m\n'
        'WHERE NOT g."effectiveDeleted"'
    )
    return _collapse(f"{readers}\nUNION ALL\n{admins}")


def _share() -> str:
    """S10.4: whoever may share an item reads and changes its shares; a receiver reads the
    shares that reach them, directly or through a group (*via*)."""
    holders = [
        f"SELECT {_cols('s.id', 'a."userId"', '1', '1', '0', '0')}\n"
        'FROM "ShareEffective" AS s\n'
        f'JOIN "{access_name(table)}" AS a ON a."targetId" = s."itemId" AND a.shareable\n'
        f"WHERE NOT s.\"effectiveDeleted\" AND s.kind = '{kind}'"
        for kind, table in SUBJECTS.items()
    ]
    direct = (
        f"SELECT {_cols('s.id', 'u."userId"', '0', '0', '0', '0')}\n"
        'FROM "ShareEffective" AS s\nJOIN "AccessUser" AS u ON u."userId" = s."userId"\n'
        'WHERE NOT s."effectiveDeleted"'
    )
    grouped = (
        f"SELECT {_cols('s.id', 'm."userId"', '0', '0', '0', '0')}\n"
        'FROM "ShareEffective" AS s\nJOIN "AccessMember" AS m ON m."groupId" = s."groupId"\n'
        'WHERE NOT s."effectiveDeleted"'
    )
    return _collapse("\nUNION ALL\n".join((*holders, direct, grouped)))


def _linked_item() -> str:
    """S11.9: read by the local users the linked server names as its viewers, and admins."""
    viewers = (
        f"SELECT {_cols('i.id', 'u."userId"', '0', '0', '0', '0')}\n"
        'FROM "LinkedItem" AS i, json_each(i.viewers) AS v\n'
        'JOIN "AccessUser" AS u ON u."userId" = v.value AND u.local'
    )
    admins = (
        f"SELECT {_cols('i.id', 'm."userId"', '0', '0', '0', '0')}\n"
        'FROM "LinkedItem" AS i\nCROSS JOIN "AccessAdmin" AS m'
    )
    return _collapse(f"{viewers}\nUNION ALL\n{admins}")


BASES: dict[str, Callable[[], str]] = {
    "AccessUser": _access_user,
    "AccessMember": _access_member,
    "AccessAdmin": _access_admin,
    "ShareLevel": _share_level,
    "ReceiptTarget": _receipt_target,
}

WRITTEN: dict[str, Callable[[], str]] = {
    "TaxBook": _tax_book,
    "Person": _person,
    "GiftPlan": _gift_plan,
    "Gift": _gift,
    "Donation": _donation,
    "Organisation": _organisation,
    "Receipt": _receipt,
    "ReceiptLink": _receipt_link,
    "Reimbursement": _reimbursement,
    "TransferMatch": _transfer_match,
    "Relationship": _relationship,
    "WashSale": _wash_sale,
    "Alert": _alert,
    "ImportMapping": _import_mapping,
    "TaxBookFiler": _tax_book_filer,
    "Activity": _activity,
    "User": _user,
    "Group": _group,
    "Share": _share,
    "LinkedItem": _linked_item,
}


def select_sql(table: Table) -> str:
    """The SELECT a table's view is made of."""
    how = seen(table)
    if how.how == "root":
        return _root(table, how.share)
    if how.how == "child":
        fk = next(f for f in table.foreign_keys if f.parent.name == how.key)
        return _child(table, fk.column.table, how.key)
    if how.how == "per-user":
        return _per_user(table, how.key, how.configurable)
    if how.how == "admin":
        return _admin(table)
    if how.how == "rule":
        return WRITTEN[table.name]()
    raise ValueError(f"{table.name} is {how.how}: it has no view")


def all_sql(metadata: MetaData) -> dict[str, str]:
    """Every access view's CREATE VIEW, by view name, the bases first."""
    out = {name: _view(name, make()) for name, make in BASES.items()}
    for t in metadata.sorted_tables:
        if has_view(t):
            out[access_name(t.name)] = _view(access_name(t.name), select_sql(t))
    return out


_NAMES = re.compile(r'"([A-Za-z]+(?:Access|Level|Target)|AccessUser|AccessMember|AccessAdmin)"')


def ordered(metadata: MetaData) -> list[tuple[str, str]]:
    """The views with each after the views it reads."""
    sql = all_sql(metadata)
    graph = {
        name: {n for n in _NAMES.findall(text.split(" AS\n", 1)[1]) if n in sql and n != name}
        for name, text in sql.items()
    }
    return [(n, sql[n]) for n in TopologicalSorter(graph).static_order()]


def drop_all_sql(connection) -> list[str]:
    names = set(BASES)
    rows = connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'view'")
    return [
        f'DROP VIEW IF EXISTS "{r[0]}"'
        for r in rows.fetchall()
        if r[0] in names or r[0].endswith(SUFFIX)
    ]


def create_all_sql(metadata: MetaData) -> list[str]:
    return [text for _, text in ordered(metadata)]
