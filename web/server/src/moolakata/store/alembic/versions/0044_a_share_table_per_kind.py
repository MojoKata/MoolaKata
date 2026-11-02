"""Shares, a table per shareable kind (requirements S10.3, docs/schema.md §7): a share's item
is a real foreign key, and what it grants is an access class's (`read`, `write`). The one
`Share` table, which named its item by kind and id, goes, its grants moved across.

Revision: 0044
Follows: 0043
"""

import sqlalchemy as sa
from alembic import op

import moolakata.store.types

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None

READ = "AcCls_00000000000000000000000001"
WRITE = "AcCls_00000000000000000000000002"

# Share kind: (the table shared, its share table's prefix).
KINDS = {
    "account": ("Account", "AcShr"),
    "portfolio": ("Portfolio", "PfShr"),
    "budget": ("Budget", "BdShr"),
    "projection": ("Projection", "PjShr"),
    "person": ("Person", "PnShr"),
    "gift-plan": ("GiftPlan", "GpShr"),
    "giving-plan": ("GivingPlan", "GvShr"),
    "tax-book": ("TaxBook", "TbShr"),
}


def _record_columns(name: str, prefix: str) -> list:
    return [
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("createdAt", moolakata.store.types.UtcTimestamp(), nullable=False),
        sa.Column("updatedAt", moolakata.store.types.UtcTimestamp(), nullable=False),
        sa.Column(
            "deleted",
            sa.Boolean(),
            sa.Computed('"deletedAt" IS NOT NULL', persisted=False),
            nullable=True,
        ),
        sa.Column("deletedAt", moolakata.store.types.UtcTimestamp(), nullable=True),
        sa.Column("deletedById", sa.Text(), nullable=True),
        sa.CheckConstraint(
            f"id GLOB '{prefix}_*' AND length(id) = {len(prefix) + 27}", name=op.f(f"ck_{name}_id")
        ),
        sa.CheckConstraint(
            '"deletedAt" IS NOT NULL OR "deletedById" IS NULL', name=op.f(f"ck_{name}_deleted_by")
        ),
        sa.ForeignKeyConstraint(
            ["deletedById"], ["User.id"], name=op.f(f"fk_{name}_deletedById_User")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{name}")),
    ]


def _access_class() -> None:
    op.create_table(
        "AccessClass",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("writable", sa.Boolean(), nullable=False),
        sa.Column("deletable", sa.Boolean(), nullable=False),
        sa.Column("shareable", sa.Boolean(), nullable=False),
        sa.Column("configurable", sa.Boolean(), nullable=False),
        *_record_columns("AccessClass", "AcCls"),
        sa.CheckConstraint(
            "writable OR NOT (deletable OR shareable OR configurable)",
            name=op.f("ck_AccessClass_implies_writable"),
        ),
        sqlite_with_rowid=False,
    )
    op.create_index(
        "ux_AccessClass_name",
        "AccessClass",
        ["name"],
        unique=True,
        sqlite_where=sa.text("NOT deleted"),
    )
    conn = op.get_bind()
    now = conn.exec_driver_sql("SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now')").scalar_one()
    for id_, name, writable in ((READ, "read", 0), (WRITE, "write", 1)):
        conn.exec_driver_sql(
            'INSERT INTO "AccessClass" (id, name, writable, deletable, shareable, configurable, '
            '"createdAt", "updatedAt") VALUES (?, ?, ?, 0, 0, 0, ?, ?)',
            (id_, name, writable, now, now),
        )


def _share_table(target: str, prefix: str) -> str:
    name = f"{target}Share"
    op.create_table(
        name,
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("targetId", sa.Text(), nullable=False),
        sa.Column("userId", sa.Text(), nullable=True),
        sa.Column("groupId", sa.Text(), nullable=True),
        sa.Column("accessClassId", sa.Text(), nullable=False),
        sa.Column("createdById", sa.Text(), nullable=True),
        sa.Column("includeReceipts", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        *_record_columns(name, prefix),
        sa.CheckConstraint(
            '("userId" IS NULL) != ("groupId" IS NULL)', name=op.f(f"ck_{name}_one_grantee")
        ),
        sa.ForeignKeyConstraint(
            ["targetId"],
            [f"{target}.id"],
            name=op.f(f"fk_{name}_targetId_{target}"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["userId"], ["User.id"], name=op.f(f"fk_{name}_userId_User"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["groupId"], ["Group.id"], name=op.f(f"fk_{name}_groupId_Group"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["accessClassId"], ["AccessClass.id"], name=op.f(f"fk_{name}_accessClassId_AccessClass")
        ),
        sa.ForeignKeyConstraint(
            ["createdById"], ["User.id"], name=op.f(f"fk_{name}_createdById_User")
        ),
        sqlite_with_rowid=False,
    )
    op.create_index(f"ix_{name}_userId", name, ["userId"])
    op.create_index(f"ix_{name}_groupId", name, ["groupId"])
    for key in ("userId", "groupId"):
        op.create_index(
            f"ux_{name}_targetId_{key}",
            name,
            ["targetId", key],
            unique=True,
            sqlite_where=sa.text("NOT deleted"),
        )
    return name


def upgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql('DROP VIEW IF EXISTS "ShareLevel"')
    _access_class()
    for kind, (target, prefix) in KINDS.items():
        name = _share_table(target, prefix)
        # A grant keeps its id's time and random parts under its new table's prefix. Only
        # the live grant of an item to a grantee moves when there were several.
        # The names come from KINDS above, not from input.
        conn.exec_driver_sql(
            f'INSERT INTO "{name}" (id, "targetId", "userId", "groupId", "accessClassId", '  # noqa: S608
            '"createdById", "includeReceipts", version, "createdAt", "updatedAt", "deletedAt", '
            '"deletedById")\n'
            f'SELECT \'{prefix}\' || substr(s.id, 6), s."itemId", s."userId", s."groupId", '
            f"CASE s.level WHEN 'write' THEN '{WRITE}' ELSE '{READ}' END, s.\"createdById\", "
            's."includeReceipts", s.version, s."createdAt", s."updatedAt", s."deletedAt", '
            's."deletedById"\n'
            f'FROM "Share" AS s JOIN "{target}" AS t ON t.id = s."itemId"\n'
            'WHERE s.kind = ? AND (s."deletedAt" IS NOT NULL OR NOT EXISTS (\n'
            '  SELECT 1 FROM "Share" AS x WHERE x.kind = s.kind AND x."itemId" = s."itemId"\n'
            '  AND x."deletedAt" IS NULL AND x.id > s.id\n'
            '  AND coalesce(x."userId", x."groupId") = coalesce(s."userId", s."groupId")))',
            (kind,),
        )
    op.drop_table("Share")


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
