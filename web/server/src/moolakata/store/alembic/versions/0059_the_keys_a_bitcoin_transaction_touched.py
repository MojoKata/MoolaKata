"""The wallet keys a recorded bitcoin transaction touched (requirements S1.6.1.3, S1.6.2.7):
`TransactionWalletKeys`, so a transaction none of whose keys is still in its wallet is no
longer checked against the chain. Transactions recorded before have none; nobody runs a
server yet, so none is filled here.

Revision: 0059
Follows: 0058
"""

from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None

TABLE = """CREATE TABLE "TransactionWalletKeys" (
	"transactionId" TEXT NOT NULL,
	"walletKeyId" TEXT NOT NULL,
	deleted BOOLEAN GENERATED ALWAYS AS ("deletedAt" IS NOT NULL) VIRTUAL,
	"deletedAt" TEXT,
	"deletedById" TEXT,
	"createdAt" TEXT NOT NULL,
	CONSTRAINT "pk_TransactionWalletKeys" PRIMARY KEY ("transactionId", "walletKeyId"),
	CONSTRAINT "ck_TransactionWalletKeys_deleted_by" CHECK ("deletedAt" IS NOT NULL OR "deletedById" IS NULL),
	CONSTRAINT "fk_TransactionWalletKeys_transactionId_Transaction" FOREIGN KEY("transactionId") REFERENCES "Transaction" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_TransactionWalletKeys_walletKeyId_WalletKey" FOREIGN KEY("walletKeyId") REFERENCES "WalletKey" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_TransactionWalletKeys_deletedById_User" FOREIGN KEY("deletedById") REFERENCES "User" (id)
)"""
INDEX = (
    'CREATE INDEX "ix_TransactionWalletKeys_walletKeyId" ON "TransactionWalletKeys" ("walletKeyId")'
)


def upgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(TABLE)
    conn.exec_driver_sql(INDEX)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
