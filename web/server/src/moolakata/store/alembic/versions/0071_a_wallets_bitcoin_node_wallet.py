"""A wallet account's Bitcoin node wallet (requirements S1.6.2.3): `Account.bitcoinNodeWallet`,
`moolakata-` and a random name kept with the account, never its id (schema.md §2). Each wallet
account whose keys were saved is given one; one never given keys gets its own when they are.

Revision: 0071
Follows: 0070
"""

from alembic import op

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None

TABLE = "Account"
HSA = '\t"hsaCoverage" TEXT, \n'
NODE = '\t"bitcoinNodeWallet" TEXT, \n'


def upgrade() -> None:
    """The table made again with the column, its rows and indexes kept, and the names given."""
    conn = op.get_bind()
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (TABLE,)
    ).scalar_one()
    if sql.count(HSA) != 1:
        raise RuntimeError(f"{TABLE}: unexpected declarations")
    stored = [
        r[1] for r in conn.exec_driver_sql(f'PRAGMA table_xinfo("{TABLE}")').fetchall() if r[6] == 0
    ]
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL",
        (TABLE,),
    ).fetchall()
    head = f'CREATE TABLE "{TABLE}" ('
    new = sql.replace(HSA, HSA + NODE)
    conn.exec_driver_sql(f'CREATE TABLE "_new_{TABLE}" (' + new[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(
        f'INSERT INTO "_new_{TABLE}" ({listed}) SELECT {listed} FROM "{TABLE}"'  # noqa: S608
    )
    conn.exec_driver_sql(f'DROP TABLE "{TABLE}"')
    conn.exec_driver_sql(f'ALTER TABLE "_new_{TABLE}" RENAME TO "{TABLE}"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)
    conn.exec_driver_sql(
        'UPDATE "Account" SET "bitcoinNodeWallet" = \'moolakata-\' || lower(hex(randomblob(8))) '
        'WHERE type = \'crypto-wallet\' AND id IN (SELECT "accountId" FROM "WalletKey")'
    )


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
