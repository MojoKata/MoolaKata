"""Reserves and moves (requirements S7.10, S7.11, S1.2): an amount put into a category for a
month, and a savings account's limit on withdrawals.

Revision: 0032
Follows: 0031
"""

import sqlalchemy as sa
from alembic import op

import moolakata.store.types

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

ACCOUNT = ('\t"syncAccount" TEXT, \n', '\t"syncAccount" TEXT, \n\t"withdrawalsAMonth" INTEGER, \n')


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
    rebuild(op.get_bind(), "Account", [ACCOUNT])
    op.create_table(
        "BudgetMove",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("budgetId", sa.Text(), nullable=False),
        sa.Column("month", moolakata.store.types.Day(), nullable=False),
        sa.Column("fromCategoryId", sa.Text(), nullable=True),
        sa.Column("toCategoryId", sa.Text(), nullable=True),
        sa.Column("amount", moolakata.store.types.Cents(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("transactionId", sa.Text(), nullable=True),
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
        sa.CheckConstraint("id GLOB 'BdgMv_*' AND length(id) = 32", name=op.f("ck_BudgetMove_id")),
        sa.CheckConstraint("amount > 0", name=op.f("ck_BudgetMove_amount")),
        sa.CheckConstraint("strftime('%d', month) = '01'", name=op.f("ck_BudgetMove_month")),
        sa.CheckConstraint(
            '"fromCategoryId" IS NOT NULL OR "toCategoryId" IS NOT NULL '
            'OR "transactionId" IS NOT NULL',
            name=op.f("ck_BudgetMove_somewhere"),
        ),
        sa.CheckConstraint(
            '"deletedAt" IS NOT NULL OR "deletedById" IS NULL',
            name=op.f("ck_BudgetMove_deleted_by"),
        ),
        sa.ForeignKeyConstraint(
            ["budgetId"],
            ["Budget.id"],
            name=op.f("fk_BudgetMove_budgetId_Budget"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["fromCategoryId"], ["Category.id"], name=op.f("fk_BudgetMove_fromCategoryId_Category")
        ),
        sa.ForeignKeyConstraint(
            ["toCategoryId"], ["Category.id"], name=op.f("fk_BudgetMove_toCategoryId_Category")
        ),
        sa.ForeignKeyConstraint(
            ["transactionId"],
            ["Transaction.id"],
            name=op.f("fk_BudgetMove_transactionId_Transaction"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["createdById"], ["User.id"], name=op.f("fk_BudgetMove_createdById_User")
        ),
        sa.ForeignKeyConstraint(
            ["deletedById"], ["User.id"], name=op.f("fk_BudgetMove_deletedById_User")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_BudgetMove")),
        info={"prefix": "BdgMv", "softDelete": True},
        sqlite_with_rowid=False,
    )
    with op.batch_alter_table("BudgetMove", schema=None) as batch_op:
        batch_op.create_index("ix_BudgetMove_budgetId", ["budgetId"], unique=False)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
