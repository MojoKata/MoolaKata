"""Every table with an id has `version`, `createdAt` and `updatedAt` (schema.md §2): the
thirteen server-kept tables that had none of them, or only `createdAt`, gain the rest. Each
row's times come from its own: when it was made, and the latest it was changed, where it
keeps one; the migration's time where it keeps none. Its version starts at 1.

Revision: 0066
Follows: 0065
"""

import datetime as dt
import re

from alembic import op

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def _latest(*columns: str) -> str:
    """The latest of several nullable times, NULL when none is set (a single argument would
    make SQLite's max an aggregate)."""
    return "NULLIF(max(" + ", ".join(f"COALESCE(\"{c}\", '')" for c in columns) + "), '')"


# Each table: (createdAt, updatedAt) as SQL over its own columns; None where it has its own
# createdAt already. NOW stands for the migration's time.
TABLES = {
    "Activity": ('"at"', '"at"'),
    "Alert": ('"seenSince"', _latest("seenSince", "openedAt", "resolvedAt")),
    "AlertState": (
        'COALESCE("seenAt", "emailedAt", "dismissedAt", NOW)',
        f"COALESCE({_latest('seenAt', 'emailedAt', 'dismissedAt')}, NOW)",
    ),
    "LinkFile": ('"missedAt"', '"missedAt"'),
    "LinkSent": ("NOW", "NOW"),
    "LinkedItem": (None, _latest("createdAt", "sharedAt")),
    "OneTimeToken": (None, '"createdAt"'),
    "QueuedEmail": ('"queuedAt"', _latest("queuedAt", "refusedAt")),
    "RecoveryCode": (None, '"createdAt"'),
    "Secret": ('"setAt"', '"setAt"'),
    "Session": (None, _latest("createdAt", "lastSeenAt", "authAt")),
    "WalletAddress": (None, _latest("createdAt", "checkedAt")),
    "WashSale": (None, '"createdAt"'),
}
# The id's line, however the revision that made the table spaced it.
FIRST = re.compile(r"^\s*id TEXT NOT NULL,[ ]*\n", re.M)
VERSION = "\tversion INTEGER DEFAULT 1 NOT NULL, \n"
CREATED = '\t"createdAt" TEXT NOT NULL, \n'
UPDATED = '\t"updatedAt" TEXT NOT NULL, \n'


def upgrade() -> None:
    """Each table made again with the columns, its rows and indexes kept."""
    conn = op.get_bind()
    now = "'" + dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ") + "'"
    for table, (created, updated) in TABLES.items():
        sql = conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).scalar_one()
        first = FIRST.findall(sql)
        if len(first) != 1 or (created is None) != ('"createdAt" TEXT NOT NULL' in sql):
            raise RuntimeError(f"{table}: unexpected declarations")
        added = VERSION + (CREATED if created else "") + UPDATED
        new = sql.replace(first[0], first[0] + added)
        stored = [
            r[1]
            for r in conn.exec_driver_sql(f'PRAGMA table_xinfo("{table}")').fetchall()
            if r[6] == 0
        ]
        indexes = conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? "
            "AND sql IS NOT NULL",
            (table,),
        ).fetchall()
        head = f'CREATE TABLE "{table}" ('
        conn.exec_driver_sql(f'CREATE TABLE "_new_{table}" (' + new[len(head) :])
        listed = ", ".join(f'"{c}"' for c in stored)
        names = '"version", ' + ('"createdAt", ' if created else "") + '"updatedAt"'
        values = "1, " + (f"{created}, " if created else "") + updated
        # The names come from sqlite_master and this file, not from input.
        conn.exec_driver_sql(
            f'INSERT INTO "_new_{table}" ({listed}, {names}) '  # noqa: S608
            f'SELECT {listed}, {values.replace("NOW", now)} FROM "{table}"'
        )
        conn.exec_driver_sql(f'DROP TABLE "{table}"')
        conn.exec_driver_sql(f'ALTER TABLE "_new_{table}" RENAME TO "{table}"')
        for (index_sql,) in indexes:
            conn.exec_driver_sql(index_sql)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
