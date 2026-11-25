"""What this server sent that its peer refused (requirements S11.7): `Link.peerRefusal`, the
peer's reason, kept apart from `refusal` (what the peer sent, refused here) and from
`failingSince` (no answer). It starts empty: no link is refused by its peer until a delivery is.

Revision: 0069
Follows: 0068
"""

from alembic import op

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None

TABLE = "Link"
REFUSAL = "\trefusal TEXT, \n"
PEER_REFUSAL = '\t"peerRefusal" TEXT, \n'


def upgrade() -> None:
    """The table made again with the column, its rows and indexes kept."""
    conn = op.get_bind()
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (TABLE,)
    ).scalar_one()
    if sql.count(REFUSAL) != 1:
        raise RuntimeError(f"{TABLE}: unexpected declarations")
    stored = [
        r[1] for r in conn.exec_driver_sql(f'PRAGMA table_xinfo("{TABLE}")').fetchall() if r[6] == 0
    ]
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL",
        (TABLE,),
    ).fetchall()
    head = f'CREATE TABLE "{TABLE}" ('
    new = sql.replace(REFUSAL, REFUSAL + PEER_REFUSAL)
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
