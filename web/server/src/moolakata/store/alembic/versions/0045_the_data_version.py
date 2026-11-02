"""The data version (docs/schema.md §8, requirements S7.3.10): one counter row that a trigger on
every table figures come from moves on, so a budget's kept months are keyed by the data they
were worked out from. The triggers and the row are made by the views' sync after every
migration, from the table declarations.

Revision: 0045
Follows: 0044
"""

import sqlalchemy as sa
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "DataVersion",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_DataVersion")),
    )


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
