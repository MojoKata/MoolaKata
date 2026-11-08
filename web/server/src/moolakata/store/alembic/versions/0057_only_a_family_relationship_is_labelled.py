"""Only a `family` relationship carries a label (requirements S10.10.4: a family relation is
named by its label, godmother; the others by their relation): the label's column refuses one
on any other relation, and one left on any is cleared.

Revision: 0057
Follows: 0056
"""

from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None

TABLE = "Relationship"
EDITS = (
    (
        '\tCONSTRAINT "ck_Relationship_dates" CHECK ("toDate" IS NULL OR "fromDate" IS NULL OR '
        '"toDate" >= "fromDate"), \n',
        '\tCONSTRAINT "ck_Relationship_dates" CHECK ("toDate" IS NULL OR "fromDate" IS NULL OR '
        '"toDate" >= "fromDate"), \n'
        "\tCONSTRAINT \"ck_Relationship_label\" CHECK (label IS NULL OR relation = 'family'), \n",
    ),
)


def upgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql("UPDATE \"Relationship\" SET label = NULL WHERE relation <> 'family'")
    sql = conn.exec_driver_sql(
        f"SELECT sql FROM sqlite_master WHERE type = 'table' AND name = '{TABLE}'"  # noqa: S608
    ).scalar_one()
    new = sql
    for old, replacement in EDITS:
        if new.count(old) != 1:
            raise RuntimeError(f"{TABLE}: unexpected declarations")
        new = new.replace(old, replacement)
    stored = [
        r[1] for r in conn.exec_driver_sql(f'PRAGMA table_xinfo("{TABLE}")').fetchall() if r[6] == 0
    ]
    indexes = conn.exec_driver_sql(
        f"SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = '{TABLE}' "  # noqa: S608
        "AND sql IS NOT NULL"
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
