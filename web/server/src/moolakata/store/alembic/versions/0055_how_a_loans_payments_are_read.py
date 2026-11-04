"""How a loan's payment days are read (requirements S1.9.3): `Loan.paymentsMode`, recorded here
(a payment day with none recorded is missed) or assumed as scheduled (it counts as paid); none
is Automatic, which every loan made before is.

Revision: 0055
Follows: 0054
"""

from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None

COLUMN = (
    '\t"budgetCategoryId" TEXT, \n',
    '\t"budgetCategoryId" TEXT, \n\t"paymentsMode" TEXT, \n',
)
CHECK = (
    "\tCONSTRAINT \"ck_Loan_budget_counting\" CHECK (\"budgetCounting\" IN ('split', 'whole')), \n",
    "\tCONSTRAINT \"ck_Loan_budget_counting\" CHECK (\"budgetCounting\" IN ('split', 'whole')), \n"
    '\tCONSTRAINT "ck_Loan_payments_mode" CHECK ("paymentsMode" IS NULL OR "paymentsMode" IN '
    "('recorded', 'assumed')), \n",
)


def upgrade() -> None:
    conn = op.get_bind()
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'Loan'"
    ).scalar_one()
    new = sql
    for old, replacement in (COLUMN, CHECK):
        if new.count(old) != 1:
            raise RuntimeError("Loan: unexpected declarations")
        new = new.replace(old, replacement)
    stored = [
        r[1] for r in conn.exec_driver_sql('PRAGMA table_xinfo("Loan")').fetchall() if r[6] == 0
    ]
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'Loan' "
        "AND sql IS NOT NULL"
    ).fetchall()
    head = 'CREATE TABLE "Loan" ('
    conn.exec_driver_sql('CREATE TABLE "_new_Loan" (' + new[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(f'INSERT INTO "_new_Loan" ({listed}) SELECT {listed} FROM "Loan"')  # noqa: S608
    conn.exec_driver_sql('DROP TABLE "Loan"')
    conn.exec_driver_sql('ALTER TABLE "_new_Loan" RENAME TO "Loan"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
