"""An account's closed date (requirements S1.2, R3.10): the `active` switch becomes the day it
closed, so figures count a closed account up to that day. An account already closed takes the
day of its last transaction, or the day it was last changed when it has none.

Revision: 0046
Follows: 0045
"""

from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None

ACTIVE = "\tactive BOOLEAN DEFAULT 1 NOT NULL, \n"
CLOSED = '\t"closedOn" TEXT, \n'
CLOSED_ON = (
    "CASE WHEN active THEN NULL ELSE coalesce("
    '(SELECT max(t.date) FROM "Transaction" AS t WHERE t."accountId" = a.id), '
    'substr(a."updatedAt", 1, 10)) END'
)


def upgrade() -> None:
    conn = op.get_bind()
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'Account'"
    ).scalar_one()
    if sql.count(ACTIVE) != 1:
        raise RuntimeError("Account: unexpected declarations")
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'Account' "
        "AND sql IS NOT NULL"
    ).fetchall()
    head = 'CREATE TABLE "Account" ('
    conn.exec_driver_sql('CREATE TABLE "_new_Account" (' + sql.replace(ACTIVE, CLOSED)[len(head) :])
    kept = [
        r[1]
        for r in conn.exec_driver_sql('PRAGMA table_xinfo("Account")').fetchall()
        if r[6] == 0 and r[1] != "active"
    ]
    listed = ", ".join(f'"{c}"' for c in kept)
    picked = ", ".join(f'a."{c}"' for c in kept)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(
        f'INSERT INTO "_new_Account" ({listed}, "closedOn") '  # noqa: S608
        f'SELECT {picked}, {CLOSED_ON} FROM "Account" AS a'
    )
    conn.exec_driver_sql('DROP TABLE "Account"')
    conn.exec_driver_sql('ALTER TABLE "_new_Account" RENAME TO "Account"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
