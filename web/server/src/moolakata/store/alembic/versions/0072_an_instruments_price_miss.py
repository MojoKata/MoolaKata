"""An instrument no price source knows.

`Instrument.priceMissedAt` (requirements S4.2.2): since when the refreshes have found that every
enabled source serving its class, asked for it, answered without a price, while none was stored.
Every instrument starts with none; the next refresh records each it misses.

Revision: 0072
Follows: 0071
"""

from alembic import op

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None

AFTER = "\tcusip TEXT, \n"
COLUMN = '\t"priceMissedAt" TEXT, \n'


def upgrade() -> None:
    """The table made again with its column added after `cusip`, its rows and indexes kept."""
    conn = op.get_bind()
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'Instrument'"
    ).scalar_one()
    if sql.count(AFTER) != 1:
        raise RuntimeError("Instrument: unexpected declarations")
    stored = [
        r[1]
        for r in conn.exec_driver_sql('PRAGMA table_xinfo("Instrument")').fetchall()
        if r[6] == 0
    ]
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'Instrument' "
        "AND sql IS NOT NULL"
    ).fetchall()
    head = 'CREATE TABLE "Instrument" ('
    new = sql.replace(AFTER, AFTER + COLUMN)
    conn.exec_driver_sql('CREATE TABLE "_new_Instrument" (' + new[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(
        f'INSERT INTO "_new_Instrument" ({listed}) SELECT {listed} FROM "Instrument"'  # noqa: S608
    )
    conn.exec_driver_sql('DROP TABLE "Instrument"')
    conn.exec_driver_sql('ALTER TABLE "_new_Instrument" RENAME TO "Instrument"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
