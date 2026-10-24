"""An envelope budget's card payment lines (requirements S7.13.2): a move can put money into a
card's payment line, covering what it owes but no category held.

Revision: 0035
Follows: 0034
"""

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None

MOVE = [
    ('\t"transactionId" TEXT, \n', '\t"transactionId" TEXT, \n\t"cardId" TEXT, \n'),
    (
        'CHECK ("fromCategoryId" IS NOT NULL OR "toCategoryId" IS NOT NULL '
        'OR "transactionId" IS NOT NULL)',
        'CHECK ("fromCategoryId" IS NOT NULL OR "toCategoryId" IS NOT NULL '
        'OR "transactionId" IS NOT NULL OR "cardId" IS NOT NULL)',
    ),
    (
        '\tCONSTRAINT "fk_BudgetMove_transactionId_Transaction" FOREIGN KEY("transactionId") '
        'REFERENCES "Transaction" (id) ON DELETE CASCADE',
        '\tCONSTRAINT "fk_BudgetMove_cardId_Account" FOREIGN KEY("cardId") REFERENCES "Account" '
        "(id), \n"
        '\tCONSTRAINT "fk_BudgetMove_transactionId_Transaction" FOREIGN KEY("transactionId") '
        'REFERENCES "Transaction" (id) ON DELETE CASCADE',
    ),
]


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
    rebuild(op.get_bind(), "BudgetMove", MOVE)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
