"""Reimbursable spending (requirements S2.9): a transaction or split marked as to be paid back,
and the deposits paired with it.

Revision: 0030
Follows: 0029
"""

import sqlalchemy as sa
from alembic import op

import moolakata.store.types

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

TRANSACTION = (
    '\t"offChainKeptAt" TEXT, \n',
    '\t"offChainKeptAt" TEXT, \n\treimbursable INTEGER, \n\t"owedBy" TEXT, \n',
)
SPLIT = ("\tmemo TEXT, \n", '\tmemo TEXT, \n\treimbursable INTEGER, \n\t"owedBy" TEXT, \n')


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
    conn = op.get_bind()
    rebuild(conn, "Transaction", [TRANSACTION])
    rebuild(conn, "Split", [SPLIT])
    op.create_table(
        "Reimbursement",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("spendingId", sa.Text(), nullable=False),
        sa.Column("splitId", sa.Text(), nullable=True),
        sa.Column("paybackId", sa.Text(), nullable=False),
        sa.Column("amount", moolakata.store.types.Cents(), nullable=False),
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
            "id GLOB 'Rmbrs_*' AND length(id) = 32", name=op.f("ck_Reimbursement_id")
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_Reimbursement_amount")),
        sa.CheckConstraint(
            '"deletedAt" IS NOT NULL OR "deletedById" IS NULL',
            name=op.f("ck_Reimbursement_deleted_by"),
        ),
        sa.ForeignKeyConstraint(
            ["spendingId"],
            ["Transaction.id"],
            name=op.f("fk_Reimbursement_spendingId_Transaction"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["splitId"],
            ["Split.id"],
            name=op.f("fk_Reimbursement_splitId_Split"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paybackId"],
            ["Transaction.id"],
            name=op.f("fk_Reimbursement_paybackId_Transaction"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["createdById"], ["User.id"], name=op.f("fk_Reimbursement_createdById_User")
        ),
        sa.ForeignKeyConstraint(
            ["deletedById"], ["User.id"], name=op.f("fk_Reimbursement_deletedById_User")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_Reimbursement")),
        info={"prefix": "Rmbrs", "softDelete": True},
        sqlite_with_rowid=False,
    )
    with op.batch_alter_table("Reimbursement", schema=None) as batch_op:
        batch_op.create_index("ix_Reimbursement_spendingId", ["spendingId"], unique=False)
        batch_op.create_index("ix_Reimbursement_paybackId", ["paybackId"], unique=False)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
