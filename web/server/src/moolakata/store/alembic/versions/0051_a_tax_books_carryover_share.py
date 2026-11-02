"""A tax book keeps whether it starts from last year apart from the copy still to do, and a
filer's share of a joint return's capital-loss carryover (requirements S8.14.4, S8.17, S8.18;
the filed tax years walk, decision 2): `fromLastYear` is the choice made, `copyPending` the
copy waiting for every filer to accept, `carryoverShareShort`/`Long` the share typed. A book
whose copy is waiting keeps waiting.

Revision: 0051
Follows: 0050
"""

from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None

FROM = '\t"fromLastYear" BOOLEAN DEFAULT 0 NOT NULL, \n'
ADDED = (
    FROM + '\t"copyPending" BOOLEAN DEFAULT 0 NOT NULL, \n'
    '\t"carryoverShareShort" INTEGER, \n\t"carryoverShareLong" INTEGER, \n'
)


def upgrade() -> None:
    conn = op.get_bind()
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'TaxBook'"
    ).scalar_one()
    if sql.count(FROM) != 1:
        raise RuntimeError("TaxBook: unexpected declarations")
    stored = [
        r[1] for r in conn.exec_driver_sql('PRAGMA table_xinfo("TaxBook")').fetchall() if r[6] == 0
    ]
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'TaxBook' "
        "AND sql IS NOT NULL"
    ).fetchall()
    head = 'CREATE TABLE "TaxBook" ('
    conn.exec_driver_sql('CREATE TABLE "_new_TaxBook" (' + sql.replace(FROM, ADDED)[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(
        f'INSERT INTO "_new_TaxBook" ({listed}, "copyPending") '  # noqa: S608
        f'SELECT {listed}, "fromLastYear" FROM "TaxBook"'
    )
    conn.exec_driver_sql('DROP TABLE "TaxBook"')
    conn.exec_driver_sql('ALTER TABLE "_new_TaxBook" RENAME TO "TaxBook"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
