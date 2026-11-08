"""Whether a traditional IRA contribution is deductible (requirements S8.6):
`Transaction.deductible` and `Split.deductible`, a nullable boolean, null until decided. The
nondeductible parts make Form 8606's line 1. Every row made before has none.

Revision: 0058
Follows: 0057
"""

from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None

AFTER = '\t"owedBy" TEXT, \n'
ADDED = '\t"owedBy" TEXT, \n\tdeductible BOOLEAN, \n'


def _rebuild(conn, table: str) -> None:
    """The table made again with the column after `owedBy`, its rows and indexes kept."""
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).scalar_one()
    if sql.count(AFTER) != 1:
        raise RuntimeError(f"{table}: unexpected declarations")
    new = sql.replace(AFTER, ADDED)
    stored = [
        r[1] for r in conn.exec_driver_sql(f'PRAGMA table_xinfo("{table}")').fetchall() if r[6] == 0
    ]
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL",
        (table,),
    ).fetchall()
    head = f'CREATE TABLE "{table}" ('
    conn.exec_driver_sql(f'CREATE TABLE "_new_{table}" (' + new[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(f'INSERT INTO "_new_{table}" ({listed}) SELECT {listed} FROM "{table}"')  # noqa: S608
    conn.exec_driver_sql(f'DROP TABLE "{table}"')
    conn.exec_driver_sql(f'ALTER TABLE "_new_{table}" RENAME TO "{table}"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)


def upgrade() -> None:
    conn = op.get_bind()
    for table in ("Transaction", "Split"):
        _rebuild(conn, table)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
