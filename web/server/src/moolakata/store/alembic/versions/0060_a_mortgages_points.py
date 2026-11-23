"""A mortgage's points (requirements S1.9.6, S8.12): `Loan.points`, `pointsPaidOn` and
`pointsPurpose` (bought the home, or refinanced it), all three set or none. Every loan made
before has none.

Revision: 0060
Follows: 0059
"""

from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None

TABLE = "Loan"
EDITS = (
    (
        '\t"originalValue" INTEGER, \n',
        '\t"originalValue" INTEGER, \n\tpoints INTEGER, \n\t"pointsPaidOn" TEXT, \n'
        '\t"pointsPurpose" TEXT, \n',
    ),
    (
        '\tCONSTRAINT "pk_Loan" PRIMARY KEY (id), \n',
        '\tCONSTRAINT "pk_Loan" PRIMARY KEY (id), \n'
        '\tCONSTRAINT "ck_Loan_points_purpose" CHECK ("pointsPurpose" IS NULL OR '
        "\"pointsPurpose\" IN ('purchase', 'refinance')), \n"
        '\tCONSTRAINT "ck_Loan_points" CHECK ((points IS NULL) = ("pointsPaidOn" IS NULL) '
        'AND (points IS NULL) = ("pointsPurpose" IS NULL)), \n',
    ),
)


def upgrade() -> None:
    """The table made again with the columns and their checks, its rows and indexes kept."""
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
