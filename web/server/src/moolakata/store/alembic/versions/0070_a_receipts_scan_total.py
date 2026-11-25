"""A receipt's total checked against the scan (requirements S9.8.2.1.1): `Receipt.scanTotal`,
the scan's reading of a total its text layer disagrees with, and `totalChecked`, a nullable
boolean: none with nothing to check, false while waiting for a person, true once confirmed. A
scan's total is never kept without it. Every receipt read before starts with neither.

Revision: 0070
Follows: 0069
"""

from alembic import op

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None

TABLE = "Receipt"
EDITS = (
    (
        "\tfilled TEXT DEFAULT '[]' NOT NULL, \n",
        "\tfilled TEXT DEFAULT '[]' NOT NULL, \n"
        '\t"scanTotal" INTEGER, \n\t"totalChecked" BOOLEAN, \n',
    ),
    (
        '\tCONSTRAINT "pk_Receipt" PRIMARY KEY (id), \n',
        '\tCONSTRAINT "pk_Receipt" PRIMARY KEY (id), \n'
        '\tCONSTRAINT "ck_Receipt_scan_total" CHECK ("scanTotal" IS NULL OR '
        '"totalChecked" IS NOT NULL), \n',
    ),
)


def upgrade() -> None:
    """The table made again with the columns and their check, its rows and indexes kept."""
    conn = op.get_bind()
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (TABLE,)
    ).scalar_one()
    new = sql
    for old, added in EDITS:
        if new.count(old) != 1:
            raise RuntimeError(f"{TABLE}: unexpected declarations")
        new = new.replace(old, added)
    stored = [
        r[1] for r in conn.exec_driver_sql(f'PRAGMA table_xinfo("{TABLE}")').fetchall() if r[6] == 0
    ]
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL",
        (TABLE,),
    ).fetchall()
    head = f'CREATE TABLE "{TABLE}" ('
    conn.exec_driver_sql(f'CREATE TABLE "_new_{TABLE}" (' + new[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(f'INSERT INTO "_new_{TABLE}" ({listed}) SELECT {listed} FROM "{TABLE}"')  # noqa: S608
    conn.exec_driver_sql(f'DROP TABLE "{TABLE}"')
    conn.exec_driver_sql(f'ALTER TABLE "_new_{TABLE}" RENAME TO "{TABLE}"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
