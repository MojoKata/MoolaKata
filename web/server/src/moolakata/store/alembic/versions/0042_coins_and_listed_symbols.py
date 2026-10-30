"""A coin and a listed share may share a ticker (SOL, LINK, COMP): an instrument's symbol is
unique among the coins and among the rest, not across both (requirements S2.1, CR3-174).

Revision: 0042
Follows: 0041
"""

from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('DROP INDEX "ux_Instrument_symbol"')
    op.execute(
        'CREATE UNIQUE INDEX "ux_Instrument_symbol" ON "Instrument" '
        "(symbol, \"instrumentClass\" = 'crypto') WHERE NOT deleted"
    )


def downgrade() -> None:
    op.execute('DROP INDEX "ux_Instrument_symbol"')
    op.execute(
        'CREATE UNIQUE INDEX "ux_Instrument_symbol" ON "Instrument" (symbol) WHERE NOT deleted'
    )
