"""A return that closes a tax year keeps the book's realized gains by account as they were
when it did (requirements S2.8, S8.15; the filed tax years walk, decision 1): later changes are
measured from them, so a difference no change made here explains is listed too.

Revision: 0050
Follows: 0049
"""

import re

from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None

CARRIED = re.compile(r"(\tcarried TEXT DEFAULT '\{\}' NOT NULL, ?\n)")


def upgrade() -> None:
    conn = op.get_bind()
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'Filing'"
    ).scalar_one()
    if len(CARRIED.findall(sql)) != 1:
        raise RuntimeError("Filing: unexpected declarations")
    stored = [
        r[1] for r in conn.exec_driver_sql('PRAGMA table_xinfo("Filing")').fetchall() if r[6] == 0
    ]
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'Filing' "
        "AND sql IS NOT NULL"
    ).fetchall()
    head = 'CREATE TABLE "Filing" ('
    new = CARRIED.sub(lambda m: m.group(1) + '\t"filedGains" TEXT, \n', sql)
    conn.exec_driver_sql('CREATE TABLE "_new_Filing" (' + new[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(
        f'INSERT INTO "_new_Filing" ({listed}) SELECT {listed} FROM "Filing"'  # noqa: S608
    )
    conn.exec_driver_sql('DROP TABLE "Filing"')
    conn.exec_driver_sql('ALTER TABLE "_new_Filing" RENAME TO "Filing"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
