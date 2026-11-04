"""A lot of shares moved in whose day bought isn't known yet (requirements S2.2; the values,
taxes and options walk, decision 9): `Lot.acquiredMissing`, its term unknown until the day is
typed. Lots made before are known as they were.

Revision: 0053
Follows: 0052
"""

from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None

FROM = '\t"basisMissing" BOOLEAN DEFAULT 0 NOT NULL, \n'
ADDED = FROM + '\t"acquiredMissing" BOOLEAN DEFAULT 0 NOT NULL, \n'


def upgrade() -> None:
    conn = op.get_bind()
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'Lot'"
    ).scalar_one()
    if sql.count(FROM) != 1:
        raise RuntimeError("Lot: unexpected declarations")
    stored = [
        r[1] for r in conn.exec_driver_sql('PRAGMA table_xinfo("Lot")').fetchall() if r[6] == 0
    ]
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'Lot' "
        "AND sql IS NOT NULL"
    ).fetchall()
    head = 'CREATE TABLE "Lot" ('
    conn.exec_driver_sql('CREATE TABLE "_new_Lot" (' + sql.replace(FROM, ADDED)[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(f'INSERT INTO "_new_Lot" ({listed}) SELECT {listed} FROM "Lot"')  # noqa: S608
    conn.exec_driver_sql('DROP TABLE "Lot"')
    conn.exec_driver_sql('ALTER TABLE "_new_Lot" RENAME TO "Lot"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
