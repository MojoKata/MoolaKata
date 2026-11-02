"""A plan line taken out of the plan says so (requirements S7.1.2, S7.10.3): `out`, rather than
an amount of 0, so a line of 0 stays in the plan and keeps what it holds. A line of 0 written so
far meant out, and is marked so.

Revision: 0048
Follows: 0047
"""

from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None

AMOUNT = (
    "\tamount INTEGER NOT NULL, \n",
    "\tamount INTEGER NOT NULL, \n\tout BOOLEAN DEFAULT 0 NOT NULL, \n",
)


def upgrade() -> None:
    conn = op.get_bind()
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'BudgetLine'"
    ).scalar_one()
    if sql.count(AMOUNT[0]) != 1:
        raise RuntimeError("BudgetLine: unexpected declarations")
    stored = [
        r[1]
        for r in conn.exec_driver_sql('PRAGMA table_xinfo("BudgetLine")').fetchall()
        if r[6] == 0
    ]
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'BudgetLine' "
        "AND sql IS NOT NULL"
    ).fetchall()
    head = 'CREATE TABLE "BudgetLine" ('
    new = sql.replace(*AMOUNT)
    conn.exec_driver_sql('CREATE TABLE "_new_BudgetLine" (' + new[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(
        f'INSERT INTO "_new_BudgetLine" ({listed}, out) '  # noqa: S608
        f'SELECT {listed}, amount = 0 FROM "BudgetLine"'
    )
    conn.exec_driver_sql('DROP TABLE "BudgetLine"')
    conn.exec_driver_sql('ALTER TABLE "_new_BudgetLine" RENAME TO "BudgetLine"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
