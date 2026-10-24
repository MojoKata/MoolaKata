"""The active budget (requirements S7.12): the one each user follows.

Revision: 0034
Follows: 0033
"""

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None

USER = [
    ('\t"remoteId" TEXT, \n', '\t"remoteId" TEXT, \n\t"activeBudgetId" TEXT, \n'),
    (
        '\tCONSTRAINT "fk_User_linkId_Link" FOREIGN KEY("linkId") REFERENCES "Link" (id), \n',
        '\tCONSTRAINT "fk_User_linkId_Link" FOREIGN KEY("linkId") REFERENCES "Link" (id), \n'
        '\tCONSTRAINT "fk_User_activeBudgetId_Budget" FOREIGN KEY("activeBudgetId") '
        'REFERENCES "Budget" (id) ON DELETE SET NULL, \n',
    ),
]


def rebuild(conn, name: str, edits: list[tuple[str, str]]) -> None:
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).scalar_one()
    stored = [
        r[1] for r in conn.exec_driver_sql(f'PRAGMA table_xinfo("{name}")').fetchall() if r[6] == 0
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
    rebuild(op.get_bind(), "User", USER)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
