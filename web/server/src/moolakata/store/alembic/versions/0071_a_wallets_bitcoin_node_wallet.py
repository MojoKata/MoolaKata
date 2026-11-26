"""A wallet's Bitcoin node wallet, and a bitcoin transaction dated in its owner's time zone then.

1. `Account.bitcoinNodeWallet` (requirements S1.6.2.3): `moolakata-` and a random name kept
   with the account, never its id (schema.md §2). Each wallet account whose keys were saved is
   given one; one never given keys gets its own when they are. No two accounts share one (a
   unique index over the accounts that have one).
2. `Transaction.confirmedAt` (S1.6.2.6.1): a bitcoin transaction's moment, on its transfer row.
   Those recorded before have none until the wallet's next read fills it.
3. `UserTimeZone` (S14.9.2): a user's time zones and the dates each is in effect from. A user
   with none has `User.timeZone` at every moment, until their first change.

Revision: 0071
Follows: 0070
"""

from alembic import op

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None

# Each table made again with its columns added after the one named, its rows and indexes kept.
ADDED = (
    ("Account", '\t"hsaCoverage" TEXT, \n', '\t"bitcoinNodeWallet" TEXT, \n'),
    ("Transaction", '\t"offChainKeptAt" TEXT, \n', '\t"confirmedAt" TEXT, \n'),
)
# One account to a node wallet: no other is ever read under its name.
INDEX = (
    'CREATE UNIQUE INDEX "ux_Account_bitcoinNodeWallet" ON "Account" ("bitcoinNodeWallet") '
    'WHERE "bitcoinNodeWallet" IS NOT NULL'
)
ZONES = """CREATE TABLE "UserTimeZone" (
	id TEXT NOT NULL,
	"userId" TEXT NOT NULL,
	"timeZone" TEXT NOT NULL,
	since TEXT NOT NULL,
	version INTEGER DEFAULT 1 NOT NULL,
	"createdAt" TEXT NOT NULL,
	"updatedAt" TEXT NOT NULL,
	deleted BOOLEAN GENERATED ALWAYS AS ("deletedAt" IS NOT NULL) VIRTUAL,
	"deletedAt" TEXT,
	"deletedById" TEXT,
	CONSTRAINT "pk_UserTimeZone" PRIMARY KEY (id),
	CONSTRAINT "ck_UserTimeZone_deleted_by" CHECK ("deletedAt" IS NOT NULL OR "deletedById" IS NULL),
	CONSTRAINT "ck_UserTimeZone_id" CHECK (id GLOB 'UsrTz_*' AND length(id) = 32),
	CONSTRAINT "fk_UserTimeZone_userId_User" FOREIGN KEY("userId") REFERENCES "User" (id),
	CONSTRAINT "fk_UserTimeZone_deletedById_User" FOREIGN KEY("deletedById") REFERENCES "User" (id)
)
 WITHOUT ROWID"""
ZONES_INDEX = (
    'CREATE UNIQUE INDEX "ux_UserTimeZone_userId_since" ON "UserTimeZone" ("userId", since) '
    "WHERE NOT deleted"
)


def _add_column(conn, table: str, after: str, column: str) -> None:
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).scalar_one()
    if sql.count(after) != 1:
        raise RuntimeError(f"{table}: unexpected declarations")
    stored = [
        r[1] for r in conn.exec_driver_sql(f'PRAGMA table_xinfo("{table}")').fetchall() if r[6] == 0
    ]
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL",
        (table,),
    ).fetchall()
    head = f'CREATE TABLE "{table}" ('
    new = sql.replace(after, after + column)
    conn.exec_driver_sql(f'CREATE TABLE "_new_{table}" (' + new[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(
        f'INSERT INTO "_new_{table}" ({listed}) SELECT {listed} FROM "{table}"'  # noqa: S608
    )
    conn.exec_driver_sql(f'DROP TABLE "{table}"')
    conn.exec_driver_sql(f'ALTER TABLE "_new_{table}" RENAME TO "{table}"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)


def upgrade() -> None:
    """The columns added, the node wallets named, and the time zones' table made."""
    conn = op.get_bind()
    for table, after, column in ADDED:
        _add_column(conn, table, after, column)
    conn.exec_driver_sql(
        'UPDATE "Account" SET "bitcoinNodeWallet" = \'moolakata-\' || lower(hex(randomblob(8))) '
        'WHERE type = \'crypto-wallet\' AND id IN (SELECT "accountId" FROM "WalletKey")'
    )
    conn.exec_driver_sql(INDEX)
    conn.exec_driver_sql(ZONES)
    conn.exec_driver_sql(ZONES_INDEX)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
