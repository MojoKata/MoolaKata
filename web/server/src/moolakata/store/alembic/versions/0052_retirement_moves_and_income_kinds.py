"""An HSA's coverage, a Roth conversion as a contribution source, and two kinds of
transaction (requirements S8.5, S8.6; the values, taxes and options walk, decisions 7 and 8):
`Account.hsaCoverage` (self or family) sets an HSA's limit; `conversion` joins the sources of
money into a retirement account; `foreign-tax` and `reward` join the kinds.

Revision: 0052
Follows: 0051
"""

from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None

ACCOUNT = [
    (
        '\t"withdrawalsAMonth" INTEGER, \n',
        '\t"withdrawalsAMonth" INTEGER, \n\t"hsaCoverage" TEXT, \n',
    ),
    (
        '\tCONSTRAINT "ck_Account_statement_interval" CHECK ("statementInterval" IS NULL OR '
        "\"statementInterval\" IN ('monthly', 'quarterly', 'yearly', 'none')), \n",
        '\tCONSTRAINT "ck_Account_statement_interval" CHECK ("statementInterval" IS NULL OR '
        "\"statementInterval\" IN ('monthly', 'quarterly', 'yearly', 'none')), \n"
        '\tCONSTRAINT "ck_Account_hsa_coverage" CHECK ("hsaCoverage" IS NULL OR '
        "\"hsaCoverage\" IN ('self', 'family')), \n",
    ),
]
TRANSACTION = [
    (
        "\"contributionSource\" IN ('employee', 'employer', 'rollover'))",
        "\"contributionSource\" IN ('employee', 'employer', 'rollover', 'conversion'))",
    ),
    ("'spin-off', 'merger')", "'spin-off', 'merger', 'foreign-tax', 'reward')"),
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
    conn = op.get_bind()
    rebuild(conn, "Account", ACCOUNT)
    rebuild(conn, "Transaction", TRANSACTION)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
