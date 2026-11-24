"""What a peer sent that was refused (requirements S11.7): `Link.refusal`, the reason, kept
apart from `failingSince`, which is for a peer that didn't answer. It starts empty: no link is
refusing until an exchange refuses what its peer sends.

Revision: 0068
Follows: 0067
"""

from alembic import op

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None

TABLE = "Link"
BROKEN = '\t"brokenAt" TEXT, \n'
REFUSAL = "\trefusal TEXT, \n"


def upgrade() -> None:
    """The table made again with the column, its rows and indexes kept."""
    conn = op.get_bind()
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (TABLE,)
    ).scalar_one()
    if sql.count(BROKEN) != 1:
        raise RuntimeError(f"{TABLE}: unexpected declarations")
    stored = [
        r[1] for r in conn.exec_driver_sql(f'PRAGMA table_xinfo("{TABLE}")').fetchall() if r[6] == 0
    ]
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL",
        (TABLE,),
    ).fetchall()
    head = f'CREATE TABLE "{TABLE}" ('
    new = sql.replace(BROKEN, BROKEN + REFUSAL)
    conn.exec_driver_sql(f'CREATE TABLE "_new_{TABLE}" (' + new[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(
        f'INSERT INTO "_new_{TABLE}" ({listed}) SELECT {listed} FROM "{TABLE}"'  # noqa: S608
    )
    conn.exec_driver_sql(f'DROP TABLE "{TABLE}"')
    conn.exec_driver_sql(f'ALTER TABLE "_new_{TABLE}" RENAME TO "{TABLE}"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
