"""A sign-up request's password hash is cleared once the request is decided or lapses
(requirements S10.1.4.2, schema.md §4.4): `SignupRequest.passwordHash` takes null.

Revision: 0074
Follows: 0073
"""

from alembic import op

revision = "0074"
down_revision = "0073"
branch_labels = None
depends_on = None

BEFORE = '\t"passwordHash" TEXT NOT NULL, \n'
AFTER = '\t"passwordHash" TEXT, \n'


def upgrade() -> None:
    """The table made again with the column nullable, its rows and indexes kept."""
    conn = op.get_bind()
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'SignupRequest'"
    ).scalar_one()
    if sql.count(BEFORE) != 1:
        raise RuntimeError("SignupRequest: unexpected declarations")
    stored = [
        r[1]
        for r in conn.exec_driver_sql('PRAGMA table_xinfo("SignupRequest")').fetchall()
        if r[6] == 0
    ]
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'SignupRequest' "
        "AND sql IS NOT NULL"
    ).fetchall()
    head = 'CREATE TABLE "SignupRequest" ('
    new = sql.replace(BEFORE, AFTER)
    conn.exec_driver_sql('CREATE TABLE "_new_SignupRequest" (' + new[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(
        f'INSERT INTO "_new_SignupRequest" ({listed}) SELECT {listed} FROM "SignupRequest"'  # noqa: S608
    )
    conn.exec_driver_sql('DROP TABLE "SignupRequest"')
    conn.exec_driver_sql('ALTER TABLE "_new_SignupRequest" RENAME TO "SignupRequest"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
