"""A budget's month marked reviewed (requirements S7.14), with the figures it had then.

Revision: 0036
Follows: 0035
"""

import sqlalchemy as sa
from alembic import op

import moolakata.store.types

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "BudgetReview",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("budgetId", sa.Text(), nullable=False),
        sa.Column("month", moolakata.store.types.Day(), nullable=False),
        sa.Column("figures", sa.Text(), nullable=False),
        sa.Column("reviewedById", sa.Text(), nullable=True),
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
            "id GLOB 'BdgRv_*' AND length(id) = 32", name=op.f("ck_BudgetReview_id")
        ),
        sa.CheckConstraint("strftime('%d', month) = '01'", name=op.f("ck_BudgetReview_month")),
        sa.CheckConstraint(
            '"deletedAt" IS NOT NULL OR "deletedById" IS NULL',
            name=op.f("ck_BudgetReview_deleted_by"),
        ),
        sa.ForeignKeyConstraint(
            ["budgetId"],
            ["Budget.id"],
            name=op.f("fk_BudgetReview_budgetId_Budget"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewedById"], ["User.id"], name=op.f("fk_BudgetReview_reviewedById_User")
        ),
        sa.ForeignKeyConstraint(
            ["deletedById"], ["User.id"], name=op.f("fk_BudgetReview_deletedById_User")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_BudgetReview")),
        info={"prefix": "BdgRv", "softDelete": True},
        sqlite_with_rowid=False,
    )
    with op.batch_alter_table("BudgetReview", schema=None) as batch_op:
        batch_op.create_index(
            "ux_BudgetReview_budgetId_month",
            ["budgetId", "month"],
            unique=True,
            sqlite_where=sa.text("NOT deleted"),
        )


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
