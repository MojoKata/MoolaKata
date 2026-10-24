"""A budget's leave-outs (requirements S7.3.5): a transaction it counts nowhere.

Revision: 0033
Follows: 0032
"""

import sqlalchemy as sa
from alembic import op

import moolakata.store.types

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "BudgetLeaveOuts",
        sa.Column("budgetId", sa.Text(), nullable=False),
        sa.Column("transactionId", sa.Text(), nullable=False),
        sa.Column(
            "deleted",
            sa.Boolean(),
            sa.Computed('"deletedAt" IS NOT NULL', persisted=False),
            nullable=True,
        ),
        sa.Column("deletedAt", moolakata.store.types.UtcTimestamp(), nullable=True),
        sa.Column("deletedById", sa.Text(), nullable=True),
        sa.Column("createdAt", moolakata.store.types.UtcTimestamp(), nullable=False),
        sa.CheckConstraint(
            '"deletedAt" IS NOT NULL OR "deletedById" IS NULL',
            name=op.f("ck_BudgetLeaveOuts_deleted_by"),
        ),
        sa.ForeignKeyConstraint(
            ["budgetId"],
            ["Budget.id"],
            name=op.f("fk_BudgetLeaveOuts_budgetId_Budget"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["deletedById"], ["User.id"], name=op.f("fk_BudgetLeaveOuts_deletedById_User")
        ),
        sa.ForeignKeyConstraint(
            ["transactionId"],
            ["Transaction.id"],
            name=op.f("fk_BudgetLeaveOuts_transactionId_Transaction"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("budgetId", "transactionId", name=op.f("pk_BudgetLeaveOuts")),
        info={"softDelete": True, "pairs": True},
    )


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
