"""A lot is made by its transaction (requirements S2.2): `Lot.transactionId` is required. Value
that arrives comes with the transaction that moved it in, so returns count it as money in, not
growth (S5.2); no code makes a lot without one, and none is kept.

Revision: 0054
Follows: 0053
"""

from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None

FROM = '\t"transactionId" TEXT, \n'
REQUIRED = '\t"transactionId" TEXT NOT NULL, \n'


def upgrade() -> None:
    conn = op.get_bind()
    if conn.exec_driver_sql('SELECT 1 FROM "Lot" WHERE "transactionId" IS NULL').first():
        raise RuntimeError("Lot: a lot without its transaction; none is made, so none is kept")
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
    conn.exec_driver_sql('CREATE TABLE "_new_Lot" (' + sql.replace(FROM, REQUIRED)[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(f'INSERT INTO "_new_Lot" ({listed}) SELECT {listed} FROM "Lot"')  # noqa: S608
    conn.exec_driver_sql('DROP TABLE "Lot"')
    conn.exec_driver_sql('ALTER TABLE "_new_Lot" RENAME TO "Lot"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
