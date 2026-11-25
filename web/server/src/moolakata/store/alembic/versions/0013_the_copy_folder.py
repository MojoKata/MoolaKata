"""A linked copy's folder has a random name, never the link's id, which would date the link on
disk (schema.md §2, requirements S11.9.1): the name is kept on the Link.

`Link` is rebuilt to add the column where the table declares it, as 0012 rebuilds `Connector`.

Revision: 0013
Follows: 0012
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

COLUMN = (
    '"copyPublicKey" TEXT, \n',
    '"copyFolder" TEXT, \n\t"copyPublicKey" TEXT, \n',
)


def rebuild(conn, name: str, edits: list[tuple[str, str]], drop: tuple[str, ...] = ()) -> None:
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).scalar_one()
    # The stored columns: a generated one (hidden 2 or 3) is made again by the new table.
    stored = [
        r[1]
        for r in conn.exec_driver_sql(f'PRAGMA table_xinfo("{name}")').fetchall()
        if r[6] == 0 and r[1] not in drop
    ]
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL",
        (name,),
    ).fetchall()
    new = sql
    for old, replacement in edits:
        if new.count(old) != 1:
            raise RuntimeError(f"{name}: unexpected declarations")
        new = new.replace(old, replacement)
    head = f'CREATE TABLE "{name}" ('
    conn.exec_driver_sql(f'CREATE TABLE "_new_{name}" (' + new[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(f'INSERT INTO "_new_{name}" ({listed}) SELECT {listed} FROM "{name}"')  # noqa: S608
    conn.exec_driver_sql(f'DROP TABLE "{name}"')
    conn.exec_driver_sql(f'ALTER TABLE "_new_{name}" RENAME TO "{name}"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)


def upgrade() -> None:
    rebuild(op.get_bind(), "Link", [COLUMN])


def downgrade() -> None:
    rebuild(op.get_bind(), "Link", [(COLUMN[1], COLUMN[0])], drop=("copyFolder",))
