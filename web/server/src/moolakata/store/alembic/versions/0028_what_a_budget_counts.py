"""What a budget counts (requirements S7.2, S7.3, S1.9.7): savings categories, and how a loan's
payments count in budgets; the shipped loan categories under their new names.

Revision: 0028
Follows: 0027
"""

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

KIND = (
    "CHECK (\"kind\" IN ('expense', 'income', 'transfer'))",
    "CHECK (\"kind\" IN ('expense', 'income', 'savings', 'transfer'))",
)
LOAN_COLUMNS = (
    '\t"securedById" TEXT, \n',
    '\t"securedById" TEXT, \n\t"budgetCounting" TEXT DEFAULT \'split\' NOT NULL, \n'
    '\t"budgetCategoryId" TEXT, \n',
)
LOAN_CHECK = (
    '\tCONSTRAINT "ck_Loan_term" CHECK ("termMonths" > 0), \n',
    '\tCONSTRAINT "ck_Loan_term" CHECK ("termMonths" > 0), \n'
    "\tCONSTRAINT \"ck_Loan_budget_counting\" CHECK (\"budgetCounting\" IN ('split', 'whole')), \n",
)
LOAN_FK = (
    '\tCONSTRAINT "fk_Loan_accountId_Account" FOREIGN KEY("accountId") REFERENCES "Account" '
    "(id) ON DELETE CASCADE, \n",
    '\tCONSTRAINT "fk_Loan_accountId_Account" FOREIGN KEY("accountId") REFERENCES "Account" '
    "(id) ON DELETE CASCADE, \n"
    '\tCONSTRAINT "fk_Loan_budgetCategoryId_Category" FOREIGN KEY("budgetCategoryId") '
    'REFERENCES "Category" (id), \n',
)
# The shipped categories found by their keys, renamed where they still have the old names.
RENAMES = (
    ("loans", "Loans", "Loan payments"),
    ("loans.interest", "Loan interest", "Interest"),
    ("loans.pmi", "Mortgage insurance (PMI)", "PMI"),
    ("loans.fees", "Loan fees", "Fees"),
)


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
    conn = op.get_bind()
    rebuild(conn, "Category", [KIND])
    rebuild(conn, "Loan", [LOAN_COLUMNS, LOAN_CHECK, LOAN_FK])
    for key, old, new in RENAMES:
        conn.exec_driver_sql(
            'UPDATE "Category" SET name = ? WHERE "builtIn" = ? AND name = ?', (new, key, old)
        )


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
