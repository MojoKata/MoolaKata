"""A tax book's modified AGI (requirements S8.6): `TaxBook.magi`, typed from the return, which
its Roth IRA contributions are read against. Every book starts with none.

Revision: 0073
Follows: 0072
"""

from alembic import op

revision = "0073"
down_revision = "0072"
branch_labels = None
depends_on = None

AFTER = '\t"carryoverShareLong" INTEGER, \n'
COLUMN = "\tmagi INTEGER, \n"


def upgrade() -> None:
    """The table made again with its column added after `carryoverShareLong`, its rows and
    indexes kept."""
    conn = op.get_bind()
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'TaxBook'"
    ).scalar_one()
    if sql.count(AFTER) != 1:
        raise RuntimeError("TaxBook: unexpected declarations")
    stored = [
        r[1] for r in conn.exec_driver_sql('PRAGMA table_xinfo("TaxBook")').fetchall() if r[6] == 0
    ]
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'TaxBook' "
        "AND sql IS NOT NULL"
    ).fetchall()
    head = 'CREATE TABLE "TaxBook" ('
    new = sql.replace(AFTER, AFTER + COLUMN)
    conn.exec_driver_sql('CREATE TABLE "_new_TaxBook" (' + new[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(
        f'INSERT INTO "_new_TaxBook" ({listed}) SELECT {listed} FROM "TaxBook"'  # noqa: S608
    )
    conn.exec_driver_sql('DROP TABLE "TaxBook"')
    conn.exec_driver_sql('ALTER TABLE "_new_TaxBook" RENAME TO "TaxBook"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
