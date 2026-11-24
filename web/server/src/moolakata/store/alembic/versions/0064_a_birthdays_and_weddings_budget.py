"""A gift plan's budgets for the birthday and the wedding anniversary (requirements S7.7.1):
`GiftPlan.birthdayBudget` and `weddingBudget`, for a plan budgeted per occasion, since those
two dates come from the person rather than from an `Occasion`. Every plan made before has
none.

Revision: 0064
Follows: 0063
"""

from alembic import op

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None

TABLE = "GiftPlan"
EDITS = (
    (
        '\t"giftBudget" INTEGER, \n',
        '\t"giftBudget" INTEGER, \n\t"birthdayBudget" INTEGER, \n\t"weddingBudget" INTEGER, \n',
    ),
)


def upgrade() -> None:
    """The table made again with the columns, its rows and indexes kept."""
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
    conn.exec_driver_sql(f'INSERT INTO "_new_{TABLE}" ({listed}) SELECT {listed} FROM "{TABLE}"')  # noqa: S608
    conn.exec_driver_sql(f'DROP TABLE "{TABLE}"')
    conn.exec_driver_sql(f'ALTER TABLE "_new_{TABLE}" RENAME TO "{TABLE}"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
