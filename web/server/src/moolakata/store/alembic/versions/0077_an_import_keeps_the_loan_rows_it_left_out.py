"""An import keeps the rows of a loan it left out, dated before the loan starts, each with why
(requirements S1.9.3, S1.3): `Import.leftOut`, a JSON list. The imports made so far left none
out.

Revision: 0077
Follows: 0076
"""

from alembic import op

revision = "0077"
down_revision = "0076"
branch_labels = None
depends_on = None

AFTER = "\tchanged INTEGER DEFAULT 0 NOT NULL, \n"
COLUMN = "\t\"leftOut\" TEXT DEFAULT '[]' NOT NULL, \n"


def upgrade() -> None:
    """The table made again with the column added, its rows and indexes kept."""
    conn = op.get_bind()
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'Import'"
    ).scalar_one()
    if sql.count(AFTER) != 1:
        raise RuntimeError("Import: unexpected declarations")
    stored = [
        r[1] for r in conn.exec_driver_sql('PRAGMA table_xinfo("Import")').fetchall() if r[6] == 0
    ]
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'Import' "
        "AND sql IS NOT NULL"
    ).fetchall()
    head = 'CREATE TABLE "Import" ('
    new = sql.replace(AFTER, AFTER + COLUMN)
    conn.exec_driver_sql('CREATE TABLE "_new_Import" (' + new[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(
        f'INSERT INTO "_new_Import" ({listed}) SELECT {listed} FROM "Import"'  # noqa: S608
    )
    conn.exec_driver_sql('DROP TABLE "Import"')
    conn.exec_driver_sql('ALTER TABLE "_new_Import" RENAME TO "Import"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
