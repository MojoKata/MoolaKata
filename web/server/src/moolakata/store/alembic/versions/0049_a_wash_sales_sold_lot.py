"""A wash sale names the sold lot whose loss it disallows (requirements S3.8.2, CR3-390): the
W adjustment goes on that lot's row of Form 8949, never spread over the sale's other lots, so a
sale of a long-term and a short-term lot keeps each term's figure. Rows worked out before name
none, and are spread as before until the household's wash sales are next worked out.

Revision: 0049
Follows: 0048
"""

from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None

SALE = ('\t"saleId" TEXT NOT NULL, \n', '\t"saleId" TEXT NOT NULL, \n\t"lotId" TEXT, \n')
FK = '\tCONSTRAINT "fk_WashSale_replacementId_Transaction"'
LOT_FK = (
    '\tCONSTRAINT "fk_WashSale_lotId_Lot" FOREIGN KEY("lotId") REFERENCES "Lot" (id) '
    "ON DELETE CASCADE, \n"
)


def upgrade() -> None:
    conn = op.get_bind()
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'WashSale'"
    ).scalar_one()
    if sql.count(SALE[0]) != 1 or sql.count(FK) != 1:
        raise RuntimeError("WashSale: unexpected declarations")
    stored = [
        r[1] for r in conn.exec_driver_sql('PRAGMA table_xinfo("WashSale")').fetchall() if r[6] == 0
    ]
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'WashSale' "
        "AND sql IS NOT NULL"
    ).fetchall()
    head = 'CREATE TABLE "WashSale" ('
    new = sql.replace(*SALE).replace(FK, LOT_FK + FK)
    conn.exec_driver_sql('CREATE TABLE "_new_WashSale" (' + new[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(
        f'INSERT INTO "_new_WashSale" ({listed}) SELECT {listed} FROM "WashSale"'  # noqa: S608
    )
    conn.exec_driver_sql('DROP TABLE "WashSale"')
    conn.exec_driver_sql('ALTER TABLE "_new_WashSale" RENAME TO "WashSale"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
