"""A receipt a linked server's change named that hasn't reached the copy yet (requirements
S11.4): asked for again at each exchange, so one receipt never holds back a change.

Revision: 0037
Follows: 0036
"""

import sqlalchemy as sa
from alembic import op

import moolakata.store.types

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "LinkFile",
        sa.Column("linkId", sa.Text(), nullable=False),
        sa.Column("fileId", sa.Text(), nullable=False),
        sa.Column("fileName", sa.Text(), nullable=True),
        sa.Column("tries", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("missedAt", moolakata.store.types.UtcTimestamp(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["linkId"], ["Link.id"], name=op.f("fk_LinkFile_linkId_Link"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("linkId", "fileId", name=op.f("pk_LinkFile")),
        info={
            "softDelete": False,
            "exception": "linked copies: a receipt not yet in the copy, until it is (§4.4.3)",
        },
    )


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
