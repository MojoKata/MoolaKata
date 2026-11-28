"""A receipt kept on an account says whether it is one of its statements (requirements S9.3,
S14.10.1.2): `ReceiptLink.statement`. A statement comes by an import or the connector; a loan's
other documents (a closing disclosure) are kept until it is paid off. Every account link made
so far is a statement, which an import or the connector made.

Revision: 0076
Follows: 0075
"""

from alembic import op

revision = "0076"
down_revision = "0075"
branch_labels = None
depends_on = None

COLUMN_AFTER = '\t"linkedById" TEXT,\n'
COLUMN = "\tstatement BOOLEAN DEFAULT 0 NOT NULL,\n"
CHECK_AFTER = (
    "\tCONSTRAINT \"ck_ReceiptLink_kind\" CHECK (kind IN ('transaction', 'account', 'item', "
    "'expense', 'gift', 'donation')),\n"
)
CHECK = "\tCONSTRAINT \"ck_ReceiptLink_statement\" CHECK (NOT statement OR kind = 'account'),\n"


def upgrade() -> None:
    """The table made again with the column and its check added, its rows and indexes kept;
    then every account link marked a statement."""
    conn = op.get_bind()
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'ReceiptLink'"
    ).scalar_one()
    if sql.count(COLUMN_AFTER) != 1 or sql.count(CHECK_AFTER) != 1:
        raise RuntimeError("ReceiptLink: unexpected declarations")
    stored = [
        r[1]
        for r in conn.exec_driver_sql('PRAGMA table_xinfo("ReceiptLink")').fetchall()
        if r[6] == 0
    ]
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'ReceiptLink' "
        "AND sql IS NOT NULL"
    ).fetchall()
    new = sql.replace(COLUMN_AFTER, COLUMN_AFTER + COLUMN).replace(CHECK_AFTER, CHECK_AFTER + CHECK)
    head = 'CREATE TABLE "ReceiptLink" ('
    conn.exec_driver_sql('CREATE TABLE "_new_ReceiptLink" (' + new[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(
        f'INSERT INTO "_new_ReceiptLink" ({listed}) SELECT {listed} FROM "ReceiptLink"'  # noqa: S608
    )
    conn.exec_driver_sql('DROP TABLE "ReceiptLink"')
    conn.exec_driver_sql('ALTER TABLE "_new_ReceiptLink" RENAME TO "ReceiptLink"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)
    conn.exec_driver_sql("UPDATE \"ReceiptLink\" SET statement = 1 WHERE kind = 'account'")


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
