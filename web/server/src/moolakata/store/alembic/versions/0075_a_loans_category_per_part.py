"""A loan names a category for each part of a split payment (requirements S1.9.7.1):
`Loan.interestCategoryId`, `escrowCategoryId`, `pmiCategoryId`, `feesCategoryId` and
`principalCategoryId`. Each loan takes the shipped *Loan payments* ones its split counted in
before, and a loan counting whole in no category named takes *Loan payments* itself, which
that blank meant.

Revision: 0075
Follows: 0074
"""

from alembic import op

revision = "0075"
down_revision = "0074"
branch_labels = None
depends_on = None

# Each part's column and the shipped category it starts in.
PARTS = {
    "interestCategoryId": "loans.interest",
    "escrowCategoryId": "loans.escrow",
    "pmiCategoryId": "loans.pmi",
    "feesCategoryId": "loans.fees",
    "principalCategoryId": "loans.principal",
}
COLUMN_AFTER = '\t"budgetCategoryId" TEXT, \n'
FK_AFTER = (
    '\tCONSTRAINT "fk_Loan_budgetCategoryId_Category" FOREIGN KEY("budgetCategoryId") '
    'REFERENCES "Category" (id), \n'
)


def _shipped(key: str) -> str:
    """The shipped category's id, a live one first; none when the household has none. The
    keys are the constants above, not input."""
    where = f"\"builtIn\" = '{key}'"
    return f'(SELECT id FROM "Category" WHERE {where} ORDER BY "deletedAt" IS NOT NULL LIMIT 1)'  # noqa: S608


def upgrade() -> None:
    """The table made again with the columns added after `budgetCategoryId`, its rows and
    indexes kept; then each loan's parts filled in."""
    conn = op.get_bind()
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'Loan'"
    ).scalar_one()
    if sql.count(COLUMN_AFTER) != 1 or sql.count(FK_AFTER) != 1:
        raise RuntimeError("Loan: unexpected declarations")
    stored = [
        r[1] for r in conn.exec_driver_sql('PRAGMA table_xinfo("Loan")').fetchall() if r[6] == 0
    ]
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'Loan' "
        "AND sql IS NOT NULL"
    ).fetchall()
    columns = "".join(f'\t"{c}" TEXT, \n' for c in PARTS)
    keys = "".join(
        f'\tCONSTRAINT "fk_Loan_{c}_Category" FOREIGN KEY("{c}") REFERENCES "Category" (id), \n'
        for c in PARTS
    )
    new = sql.replace(COLUMN_AFTER, COLUMN_AFTER + columns).replace(FK_AFTER, FK_AFTER + keys)
    head = 'CREATE TABLE "Loan" ('
    conn.exec_driver_sql('CREATE TABLE "_new_Loan" (' + new[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master and the constants above, not from input.
    conn.exec_driver_sql(f'INSERT INTO "_new_Loan" ({listed}) SELECT {listed} FROM "Loan"')  # noqa: S608
    conn.exec_driver_sql('DROP TABLE "Loan"')
    conn.exec_driver_sql('ALTER TABLE "_new_Loan" RENAME TO "Loan"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)
    sets = ", ".join(f'"{c}" = {_shipped(k)}' for c, k in PARTS.items())
    conn.exec_driver_sql(f'UPDATE "Loan" SET {sets}')  # noqa: S608
    conn.exec_driver_sql(
        f'UPDATE "Loan" SET "budgetCategoryId" = {_shipped("loans")} '  # noqa: S608
        'WHERE "budgetCounting" = \'whole\' AND "budgetCategoryId" IS NULL'
    )


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
