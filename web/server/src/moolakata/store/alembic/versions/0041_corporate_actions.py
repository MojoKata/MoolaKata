"""Corporate actions are records (requirements S2.4): a split, symbol change, spin-off or
merger as typed, and the transactions made from it naming it. The Transaction table is rebuilt
the way SQLite documents (as 0030 does) for its new column and key; the transactions of
actions recorded before keep standing on their own.

Revision: 0041
Follows: 0040
"""

import sqlalchemy as sa
from alembic import op

import moolakata.store.types

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None

TRANSACTION = [
    ('\t"owedBy" TEXT, \n', '\t"owedBy" TEXT, \n\t"corporateActionId" TEXT, \n'),
    (
        '\tCONSTRAINT "fk_Transaction_transferId_Transaction" FOREIGN KEY("transferId") '
        'REFERENCES "Transaction" (id)\n',
        '\tCONSTRAINT "fk_Transaction_transferId_Transaction" FOREIGN KEY("transferId") '
        'REFERENCES "Transaction" (id), \n\tCONSTRAINT '
        '"fk_Transaction_corporateActionId_CorporateAction" FOREIGN KEY("corporateActionId") '
        'REFERENCES "CorporateAction" (id)\n',
    ),
]


def rebuild(conn, name: str, edits: list[tuple[str, str]]) -> None:
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).scalar_one()
    stored = [
        r[1] for r in conn.exec_driver_sql(f'PRAGMA table_xinfo("{name}")').fetchall() if r[6] == 0
    ]
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL",
        (name,),
    ).fetchall()
    new = sql
    for old, replacement in edits:
        if new.count(old) != 1:
            raise RuntimeError(f"{name}: unexpected declarations")
        new = new.replace(old, replacement)
    head = f'CREATE TABLE "{name}" ('
    conn.exec_driver_sql(f'CREATE TABLE "_new_{name}" (' + new[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(f'INSERT INTO "_new_{name}" ({listed}) SELECT {listed} FROM "{name}"')  # noqa: S608
    conn.exec_driver_sql(f'DROP TABLE "{name}"')
    conn.exec_driver_sql(f'ALTER TABLE "_new_{name}" RENAME TO "{name}"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)


def upgrade() -> None:
    op.create_table(
        "CorporateAction",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("accountId", sa.Text(), nullable=False),
        sa.Column("instrumentId", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("date", moolakata.store.types.Day(), nullable=False),
        sa.Column("ratio", moolakata.store.types.Dec(), nullable=True),
        sa.Column("newSymbol", sa.Text(), nullable=True),
        sa.Column("basisShare", moolakata.store.types.Dec(), nullable=True),
        sa.Column("cashPerShare", moolakata.store.types.Cents(), nullable=True),
        sa.Column("newPrice", moolakata.store.types.Dec(), nullable=True),
        sa.Column("createdById", sa.Text(), nullable=True),
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
            "id GLOB 'CorpA_*' AND length(id) = 32", name=op.f("ck_CorporateAction_id")
        ),
        sa.CheckConstraint(
            '"deletedAt" IS NOT NULL OR "deletedById" IS NULL',
            name=op.f("ck_CorporateAction_deleted_by"),
        ),
        sa.CheckConstraint(
            "\"kind\" IN ('split', 'symbol-change', 'spin-off', 'merger')",
            name=op.f("ck_CorporateAction_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["accountId"],
            ["Account.id"],
            name=op.f("fk_CorporateAction_accountId_Account"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["createdById"], ["User.id"], name=op.f("fk_CorporateAction_createdById_User")
        ),
        sa.ForeignKeyConstraint(
            ["deletedById"], ["User.id"], name=op.f("fk_CorporateAction_deletedById_User")
        ),
        sa.ForeignKeyConstraint(
            ["instrumentId"],
            ["Instrument.id"],
            name=op.f("fk_CorporateAction_instrumentId_Instrument"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_CorporateAction")),
        info={"prefix": "CorpA", "softDelete": True},
        sqlite_with_rowid=False,
    )
    with op.batch_alter_table("CorporateAction", schema=None) as batch_op:
        batch_op.create_index("ix_CorporateAction_accountId", ["accountId"], unique=False)
    rebuild(op.get_bind(), "Transaction", TRANSACTION)
    op.create_index(
        "ix_Transaction_corporateActionId", "Transaction", ["corporateActionId"], unique=False
    )


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
