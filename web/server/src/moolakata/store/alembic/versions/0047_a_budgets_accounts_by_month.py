"""A budget's accounts by month (requirements S7.1.7, R3.10): each membership gains its first and
last month, so taking an account out keeps it in earlier months; an account counted again is a
row of its own, so one budget and account may have several rows, never sharing a month. The
memberships kept so far count from the budget's start, as they did.

Revision: 0047
Follows: 0046
"""

from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None

MONTHS = (
    '\t"paidFromId" TEXT,\n',
    '\t"paidFromId" TEXT,\n\t"fromMonth" TEXT,\n\t"untilMonth" TEXT,\n',
)
CHECK = (
    '\tCONSTRAINT "pk_BudgetAccount" PRIMARY KEY (id),\n',
    '\tCONSTRAINT "pk_BudgetAccount" PRIMARY KEY (id),\n'
    '\tCONSTRAINT "ck_BudgetAccount_months" CHECK (("fromMonth" IS NULL OR '
    "strftime('%d', \"fromMonth\") = '01') AND (\"untilMonth\" IS NULL OR "
    'strftime(\'%d\', "untilMonth") = \'01\') AND ("fromMonth" IS NULL OR "untilMonth" IS NULL '
    'OR "untilMonth" >= "fromMonth")),\n',
)


def upgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql('DROP INDEX "ux_BudgetAccount_budgetId_accountId"')
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'BudgetAccount'"
    ).scalar_one()
    stored = [
        r[1]
        for r in conn.exec_driver_sql('PRAGMA table_xinfo("BudgetAccount")').fetchall()
        if r[6] == 0
    ]
    new = sql
    for old, replacement in (MONTHS, CHECK):
        if new.count(old) != 1:
            raise RuntimeError("BudgetAccount: unexpected declarations")
        new = new.replace(old, replacement)
    head = 'CREATE TABLE "BudgetAccount" ('
    conn.exec_driver_sql('CREATE TABLE "_new_BudgetAccount" (' + new[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(
        f'INSERT INTO "_new_BudgetAccount" ({listed}) SELECT {listed} FROM "BudgetAccount"'  # noqa: S608
    )
    conn.exec_driver_sql('DROP TABLE "BudgetAccount"')
    conn.exec_driver_sql('ALTER TABLE "_new_BudgetAccount" RENAME TO "BudgetAccount"')


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
