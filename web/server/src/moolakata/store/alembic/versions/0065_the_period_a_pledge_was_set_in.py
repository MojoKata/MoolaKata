"""The period a pledge was set in (requirements S7.9.5): `Organisation.pledgeFrom`, the first
day of the month or year what is due is counted from, and a check that a pledge has one and
nothing else does. A pledge made before counts from the period it was last changed in.

Revision: 0065
Follows: 0064
"""

from alembic import op

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None

TABLE = "Organisation"
EDITS = (
    ('\t"pledgeEvery" TEXT, \n', '\t"pledgeEvery" TEXT, \n\t"pledgeFrom" TEXT, \n'),
    (
        "IN ('month', 'year')), \n",
        "IN ('month', 'year')), \n"
        '\tCONSTRAINT "ck_Organisation_pledge_from" CHECK (("pledge" IS NULL) = '
        '("pledgeFrom" IS NULL)), \n',
    ),
)
# The first day of the month, or of the year, of its last change.
FROM = (
    "CASE WHEN pledge IS NULL THEN NULL WHEN \"pledgeEvery\" = 'month' "
    "THEN substr(\"updatedAt\", 1, 7) || '-01' ELSE substr(\"updatedAt\", 1, 4) || '-01-01' END"
)


def upgrade() -> None:
    """The table made again with the column and its check, its rows and indexes kept."""
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
    conn.exec_driver_sql(
        f'INSERT INTO "_new_{TABLE}" ({listed}, "pledgeFrom") '  # noqa: S608
        f'SELECT {listed}, {FROM} FROM "{TABLE}"'
    )
    conn.exec_driver_sql(f'DROP TABLE "{TABLE}"')
    conn.exec_driver_sql(f'ALTER TABLE "_new_{TABLE}" RENAME TO "{TABLE}"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
