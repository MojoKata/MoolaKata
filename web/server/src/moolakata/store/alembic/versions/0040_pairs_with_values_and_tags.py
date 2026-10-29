"""Every table with values of its own has a synthetic id (docs/schema.md §2), so the pairs that
carry more than their two keys are records: a budget's accounts and their roles, the accounts
a user counts, a tax book's accounts and filers, a linked household's colour, a strategy's
legs, a sale's lot picks, and what a receipt is attached to. And a tag is a record of its own
(Tag): each user's tags, from their transactions, their receipts and the tags their rules set,
become Tag rows, joined by id.

Revision: 0040
Follows: 0039
"""

import json

from alembic import op

from moolakata import ids

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

# Each pair with values, rebuilt as a record under its singular name: its prefix, the table
# as the declarations make it, and its indexes.
PAIRS = {
    "BudgetAccounts": (
        "BudgetAccount",
        "BdgAc",
        """CREATE TABLE "_new_BudgetAccount" (
	id TEXT NOT NULL,
	"budgetId" TEXT NOT NULL,
	"accountId" TEXT NOT NULL,
	"movedFromId" TEXT,
	"paidFromId" TEXT,
	version INTEGER DEFAULT 1 NOT NULL,
	"createdAt" TEXT NOT NULL,
	"updatedAt" TEXT NOT NULL,
	deleted BOOLEAN GENERATED ALWAYS AS ("deletedAt" IS NOT NULL) VIRTUAL,
	"deletedAt" TEXT,
	"deletedById" TEXT,
	CONSTRAINT "pk_BudgetAccount" PRIMARY KEY (id),
	CONSTRAINT "ck_BudgetAccount_deleted_by" CHECK ("deletedAt" IS NOT NULL OR "deletedById" IS NULL),
	CONSTRAINT "ck_BudgetAccount_id" CHECK (id GLOB 'BdgAc_*' AND length(id) = 32),
	CONSTRAINT "fk_BudgetAccount_budgetId_Budget" FOREIGN KEY("budgetId") REFERENCES "Budget" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_BudgetAccount_accountId_Account" FOREIGN KEY("accountId") REFERENCES "Account" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_BudgetAccount_movedFromId_Account" FOREIGN KEY("movedFromId") REFERENCES "Account" (id),
	CONSTRAINT "fk_BudgetAccount_paidFromId_Account" FOREIGN KEY("paidFromId") REFERENCES "Account" (id),
	CONSTRAINT "fk_BudgetAccount_deletedById_User" FOREIGN KEY("deletedById") REFERENCES "User" (id)
)
 WITHOUT ROWID""",
        [
            'CREATE UNIQUE INDEX "ux_BudgetAccount_budgetId_accountId" ON "BudgetAccount" ("budgetId", "accountId") WHERE NOT deleted'
        ],
    ),
    "CountedAccounts": (
        "CountedAccount",
        "CntAc",
        """CREATE TABLE "_new_CountedAccount" (
	id TEXT NOT NULL,
	"userId" TEXT NOT NULL,
	"accountId" TEXT NOT NULL,
	counted BOOLEAN DEFAULT 1 NOT NULL,
	version INTEGER DEFAULT 1 NOT NULL,
	"createdAt" TEXT NOT NULL,
	"updatedAt" TEXT NOT NULL,
	deleted BOOLEAN GENERATED ALWAYS AS ("deletedAt" IS NOT NULL) VIRTUAL,
	"deletedAt" TEXT,
	"deletedById" TEXT,
	CONSTRAINT "pk_CountedAccount" PRIMARY KEY (id),
	CONSTRAINT "ck_CountedAccount_deleted_by" CHECK ("deletedAt" IS NOT NULL OR "deletedById" IS NULL),
	CONSTRAINT "ck_CountedAccount_id" CHECK (id GLOB 'CntAc_*' AND length(id) = 32),
	CONSTRAINT "fk_CountedAccount_userId_User" FOREIGN KEY("userId") REFERENCES "User" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_CountedAccount_accountId_Account" FOREIGN KEY("accountId") REFERENCES "Account" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_CountedAccount_deletedById_User" FOREIGN KEY("deletedById") REFERENCES "User" (id)
)
 WITHOUT ROWID""",
        [
            'CREATE UNIQUE INDEX "ux_CountedAccount_userId_accountId" ON "CountedAccount" ("userId", "accountId") WHERE NOT deleted'
        ],
    ),
    "TaxBookAccounts": (
        "TaxBookAccount",
        "TxBkA",
        """CREATE TABLE "_new_TaxBookAccount" (
	id TEXT NOT NULL,
	"bookId" TEXT NOT NULL,
	"accountId" TEXT NOT NULL,
	counted BOOLEAN NOT NULL,
	"addedById" TEXT,
	version INTEGER DEFAULT 1 NOT NULL,
	"createdAt" TEXT NOT NULL,
	"updatedAt" TEXT NOT NULL,
	deleted BOOLEAN GENERATED ALWAYS AS ("deletedAt" IS NOT NULL) VIRTUAL,
	"deletedAt" TEXT,
	"deletedById" TEXT,
	CONSTRAINT "pk_TaxBookAccount" PRIMARY KEY (id),
	CONSTRAINT "ck_TaxBookAccount_deleted_by" CHECK ("deletedAt" IS NOT NULL OR "deletedById" IS NULL),
	CONSTRAINT "ck_TaxBookAccount_id" CHECK (id GLOB 'TxBkA_*' AND length(id) = 32),
	CONSTRAINT "fk_TaxBookAccount_bookId_TaxBook" FOREIGN KEY("bookId") REFERENCES "TaxBook" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_TaxBookAccount_accountId_Account" FOREIGN KEY("accountId") REFERENCES "Account" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_TaxBookAccount_addedById_User" FOREIGN KEY("addedById") REFERENCES "User" (id),
	CONSTRAINT "fk_TaxBookAccount_deletedById_User" FOREIGN KEY("deletedById") REFERENCES "User" (id)
)
 WITHOUT ROWID""",
        [
            'CREATE UNIQUE INDEX "ux_TaxBookAccount_bookId_accountId" ON "TaxBookAccount" ("bookId", "accountId") WHERE NOT deleted'
        ],
    ),
    "TaxBookFilers": (
        "TaxBookFiler",
        "TxBkF",
        """CREATE TABLE "_new_TaxBookFiler" (
	id TEXT NOT NULL,
	"bookId" TEXT NOT NULL,
	"userId" TEXT NOT NULL,
	"acceptedAt" TEXT,
	version INTEGER DEFAULT 1 NOT NULL,
	"createdAt" TEXT NOT NULL,
	"updatedAt" TEXT NOT NULL,
	deleted BOOLEAN GENERATED ALWAYS AS ("deletedAt" IS NOT NULL) VIRTUAL,
	"deletedAt" TEXT,
	"deletedById" TEXT,
	CONSTRAINT "pk_TaxBookFiler" PRIMARY KEY (id),
	CONSTRAINT "ck_TaxBookFiler_deleted_by" CHECK ("deletedAt" IS NOT NULL OR "deletedById" IS NULL),
	CONSTRAINT "ck_TaxBookFiler_id" CHECK (id GLOB 'TxBkF_*' AND length(id) = 32),
	CONSTRAINT "fk_TaxBookFiler_bookId_TaxBook" FOREIGN KEY("bookId") REFERENCES "TaxBook" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_TaxBookFiler_userId_User" FOREIGN KEY("userId") REFERENCES "User" (id),
	CONSTRAINT "fk_TaxBookFiler_deletedById_User" FOREIGN KEY("deletedById") REFERENCES "User" (id)
)
 WITHOUT ROWID""",
        [
            'CREATE INDEX "ix_TaxBookFiler_user" ON "TaxBookFiler" ("userId")',
            'CREATE UNIQUE INDEX "ux_TaxBookFiler_bookId_userId" ON "TaxBookFiler" ("bookId", "userId") WHERE NOT deleted',
        ],
    ),
    "LinkColours": (
        "LinkColour",
        "LkCol",
        """CREATE TABLE "_new_LinkColour" (
	id TEXT NOT NULL,
	"userId" TEXT NOT NULL,
	"linkId" TEXT NOT NULL,
	colour TEXT NOT NULL,
	version INTEGER DEFAULT 1 NOT NULL,
	"createdAt" TEXT NOT NULL,
	"updatedAt" TEXT NOT NULL,
	deleted BOOLEAN GENERATED ALWAYS AS ("deletedAt" IS NOT NULL) VIRTUAL,
	"deletedAt" TEXT,
	"deletedById" TEXT,
	CONSTRAINT "pk_LinkColour" PRIMARY KEY (id),
	CONSTRAINT "ck_LinkColour_colour" CHECK (colour IN ('teal', 'violet', 'amber', 'rose', 'green', 'blue')),
	CONSTRAINT "ck_LinkColour_deleted_by" CHECK ("deletedAt" IS NOT NULL OR "deletedById" IS NULL),
	CONSTRAINT "ck_LinkColour_id" CHECK (id GLOB 'LkCol_*' AND length(id) = 32),
	CONSTRAINT "fk_LinkColour_userId_User" FOREIGN KEY("userId") REFERENCES "User" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_LinkColour_linkId_Link" FOREIGN KEY("linkId") REFERENCES "Link" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_LinkColour_deletedById_User" FOREIGN KEY("deletedById") REFERENCES "User" (id)
)
 WITHOUT ROWID""",
        [
            'CREATE UNIQUE INDEX "ux_LinkColour_userId_linkId" ON "LinkColour" ("userId", "linkId") WHERE NOT deleted'
        ],
    ),
    "StrategyLegs": (
        "StrategyLeg",
        "StLeg",
        """CREATE TABLE "_new_StrategyLeg" (
	id TEXT NOT NULL,
	"strategyId" TEXT NOT NULL,
	"instrumentId" TEXT NOT NULL,
	quantity TEXT,
	"addedOn" TEXT NOT NULL,
	version INTEGER DEFAULT 1 NOT NULL,
	"createdAt" TEXT NOT NULL,
	"updatedAt" TEXT NOT NULL,
	deleted BOOLEAN GENERATED ALWAYS AS ("deletedAt" IS NOT NULL) VIRTUAL,
	"deletedAt" TEXT,
	"deletedById" TEXT,
	CONSTRAINT "pk_StrategyLeg" PRIMARY KEY (id),
	CONSTRAINT "ck_StrategyLeg_deleted_by" CHECK ("deletedAt" IS NOT NULL OR "deletedById" IS NULL),
	CONSTRAINT "ck_StrategyLeg_id" CHECK (id GLOB 'StLeg_*' AND length(id) = 32),
	CONSTRAINT "fk_StrategyLeg_strategyId_Strategy" FOREIGN KEY("strategyId") REFERENCES "Strategy" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_StrategyLeg_instrumentId_Instrument" FOREIGN KEY("instrumentId") REFERENCES "Instrument" (id),
	CONSTRAINT "fk_StrategyLeg_deletedById_User" FOREIGN KEY("deletedById") REFERENCES "User" (id)
)
 WITHOUT ROWID""",
        [
            'CREATE UNIQUE INDEX "ux_StrategyLeg_strategyId_instrumentId" ON "StrategyLeg" ("strategyId", "instrumentId") WHERE NOT deleted'
        ],
    ),
    "LotPicks": (
        "LotPick",
        "LotPk",
        """CREATE TABLE "_new_LotPick" (
	id TEXT NOT NULL,
	"saleId" TEXT NOT NULL,
	"lotId" TEXT NOT NULL,
	quantity TEXT NOT NULL,
	version INTEGER DEFAULT 1 NOT NULL,
	"createdAt" TEXT NOT NULL,
	"updatedAt" TEXT NOT NULL,
	deleted BOOLEAN GENERATED ALWAYS AS ("deletedAt" IS NOT NULL) VIRTUAL,
	"deletedAt" TEXT,
	"deletedById" TEXT,
	CONSTRAINT "pk_LotPick" PRIMARY KEY (id),
	CONSTRAINT "ck_LotPick_deleted_by" CHECK ("deletedAt" IS NOT NULL OR "deletedById" IS NULL),
	CONSTRAINT "ck_LotPick_id" CHECK (id GLOB 'LotPk_*' AND length(id) = 32),
	CONSTRAINT "fk_LotPick_saleId_Transaction" FOREIGN KEY("saleId") REFERENCES "Transaction" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_LotPick_lotId_Lot" FOREIGN KEY("lotId") REFERENCES "Lot" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_LotPick_deletedById_User" FOREIGN KEY("deletedById") REFERENCES "User" (id)
)
 WITHOUT ROWID""",
        [
            'CREATE UNIQUE INDEX "ux_LotPick_saleId_lotId" ON "LotPick" ("saleId", "lotId") WHERE NOT deleted'
        ],
    ),
    "ReceiptLinks": (
        "ReceiptLink",
        "RcLnk",
        """CREATE TABLE "_new_ReceiptLink" (
	id TEXT NOT NULL,
	"receiptId" TEXT NOT NULL,
	kind TEXT NOT NULL,
	"itemId" TEXT NOT NULL,
	"linkedById" TEXT,
	version INTEGER DEFAULT 1 NOT NULL,
	"createdAt" TEXT NOT NULL,
	"updatedAt" TEXT NOT NULL,
	deleted BOOLEAN GENERATED ALWAYS AS ("deletedAt" IS NOT NULL) VIRTUAL,
	"deletedAt" TEXT,
	"deletedById" TEXT,
	CONSTRAINT "pk_ReceiptLink" PRIMARY KEY (id),
	CONSTRAINT "ck_ReceiptLink_kind" CHECK (kind IN ('transaction', 'account', 'item', 'expense', 'gift', 'donation')),
	CONSTRAINT "ck_ReceiptLink_deleted_by" CHECK ("deletedAt" IS NOT NULL OR "deletedById" IS NULL),
	CONSTRAINT "ck_ReceiptLink_id" CHECK (id GLOB 'RcLnk_*' AND length(id) = 32),
	CONSTRAINT "fk_ReceiptLink_receiptId_Receipt" FOREIGN KEY("receiptId") REFERENCES "Receipt" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_ReceiptLink_linkedById_User" FOREIGN KEY("linkedById") REFERENCES "User" (id),
	CONSTRAINT "fk_ReceiptLink_deletedById_User" FOREIGN KEY("deletedById") REFERENCES "User" (id)
)
 WITHOUT ROWID""",
        [
            'CREATE INDEX "ix_ReceiptLink_item" ON "ReceiptLink" (kind, "itemId")',
            'CREATE UNIQUE INDEX "ux_ReceiptLink_receiptId_kind_itemId" ON "ReceiptLink" ("receiptId", kind, "itemId") WHERE NOT deleted',
        ],
    ),
}

TAG = """CREATE TABLE "Tag" (
	id TEXT NOT NULL,
	"ownerId" TEXT NOT NULL,
	name TEXT NOT NULL,
	version INTEGER DEFAULT 1 NOT NULL,
	"createdAt" TEXT NOT NULL,
	"updatedAt" TEXT NOT NULL,
	deleted BOOLEAN GENERATED ALWAYS AS ("deletedAt" IS NOT NULL) VIRTUAL,
	"deletedAt" TEXT,
	"deletedById" TEXT,
	CONSTRAINT "pk_Tag" PRIMARY KEY (id),
	CONSTRAINT "ck_Tag_deleted_by" CHECK ("deletedAt" IS NOT NULL OR "deletedById" IS NULL),
	CONSTRAINT "ck_Tag_id" CHECK (id GLOB 'Tag_*' AND length(id) = 30),
	CONSTRAINT "fk_Tag_ownerId_User" FOREIGN KEY("ownerId") REFERENCES "User" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_Tag_deletedById_User" FOREIGN KEY("deletedById") REFERENCES "User" (id)
)
 WITHOUT ROWID"""
TAG_INDEXES = [
    'CREATE UNIQUE INDEX "ux_Tag_ownerId_name" ON "Tag" ("ownerId", name) WHERE NOT deleted'
]

TRANSACTIONTAGS = """CREATE TABLE "_new_TransactionTags" (
	"transactionId" TEXT NOT NULL,
	"tagId" TEXT NOT NULL,
	deleted BOOLEAN GENERATED ALWAYS AS ("deletedAt" IS NOT NULL) VIRTUAL,
	"deletedAt" TEXT,
	"deletedById" TEXT,
	"createdAt" TEXT NOT NULL,
	CONSTRAINT "pk_TransactionTags" PRIMARY KEY ("transactionId", "tagId"),
	CONSTRAINT "ck_TransactionTags_deleted_by" CHECK ("deletedAt" IS NOT NULL OR "deletedById" IS NULL),
	CONSTRAINT "fk_TransactionTags_transactionId_Transaction" FOREIGN KEY("transactionId") REFERENCES "Transaction" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_TransactionTags_tagId_Tag" FOREIGN KEY("tagId") REFERENCES "Tag" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_TransactionTags_deletedById_User" FOREIGN KEY("deletedById") REFERENCES "User" (id)
)"""
TRANSACTIONTAGS_INDEXES = ['CREATE INDEX "ix_TransactionTags_tag" ON "TransactionTags" ("tagId")']

RULETAGS = """CREATE TABLE "RuleTags" (
	"ruleId" TEXT NOT NULL,
	"tagId" TEXT NOT NULL,
	deleted BOOLEAN GENERATED ALWAYS AS ("deletedAt" IS NOT NULL) VIRTUAL,
	"deletedAt" TEXT,
	"deletedById" TEXT,
	"createdAt" TEXT NOT NULL,
	CONSTRAINT "pk_RuleTags" PRIMARY KEY ("ruleId", "tagId"),
	CONSTRAINT "ck_RuleTags_deleted_by" CHECK ("deletedAt" IS NOT NULL OR "deletedById" IS NULL),
	CONSTRAINT "fk_RuleTags_ruleId_Rule" FOREIGN KEY("ruleId") REFERENCES "Rule" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_RuleTags_tagId_Tag" FOREIGN KEY("tagId") REFERENCES "Tag" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_RuleTags_deletedById_User" FOREIGN KEY("deletedById") REFERENCES "User" (id)
)"""
RULETAGS_INDEXES = []

RECEIPTTAGS = """CREATE TABLE "ReceiptTags" (
	"receiptId" TEXT NOT NULL,
	"tagId" TEXT NOT NULL,
	deleted BOOLEAN GENERATED ALWAYS AS ("deletedAt" IS NOT NULL) VIRTUAL,
	"deletedAt" TEXT,
	"deletedById" TEXT,
	"createdAt" TEXT NOT NULL,
	CONSTRAINT "pk_ReceiptTags" PRIMARY KEY ("receiptId", "tagId"),
	CONSTRAINT "ck_ReceiptTags_deleted_by" CHECK ("deletedAt" IS NOT NULL OR "deletedById" IS NULL),
	CONSTRAINT "fk_ReceiptTags_receiptId_Receipt" FOREIGN KEY("receiptId") REFERENCES "Receipt" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_ReceiptTags_tagId_Tag" FOREIGN KEY("tagId") REFERENCES "Tag" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_ReceiptTags_deletedById_User" FOREIGN KEY("deletedById") REFERENCES "User" (id)
)"""
RECEIPTTAGS_INDEXES = []

RULE = """CREATE TABLE "_new_Rule" (
	id TEXT NOT NULL,
	"ownerId" TEXT NOT NULL,
	position INTEGER NOT NULL,
	"payeeMatch" TEXT NOT NULL,
	"amountMin" INTEGER,
	"amountMax" INTEGER,
	direction TEXT DEFAULT 'any' NOT NULL,
	"accountId" TEXT,
	"categoryId" TEXT,
	payee TEXT,
	version INTEGER DEFAULT 1 NOT NULL,
	"createdAt" TEXT NOT NULL,
	"updatedAt" TEXT NOT NULL,
	deleted BOOLEAN GENERATED ALWAYS AS ("deletedAt" IS NOT NULL) VIRTUAL,
	"deletedAt" TEXT,
	"deletedById" TEXT,
	CONSTRAINT "pk_Rule" PRIMARY KEY (id),
	CONSTRAINT "ck_Rule_direction" CHECK (direction IN ('any', 'in', 'out')),
	CONSTRAINT "ck_Rule_deleted_by" CHECK ("deletedAt" IS NOT NULL OR "deletedById" IS NULL),
	CONSTRAINT "ck_Rule_id" CHECK (id GLOB 'Rule_*' AND length(id) = 31),
	CONSTRAINT "fk_Rule_ownerId_User" FOREIGN KEY("ownerId") REFERENCES "User" (id),
	CONSTRAINT "fk_Rule_accountId_Account" FOREIGN KEY("accountId") REFERENCES "Account" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_Rule_categoryId_Category" FOREIGN KEY("categoryId") REFERENCES "Category" (id),
	CONSTRAINT "fk_Rule_deletedById_User" FOREIGN KEY("deletedById") REFERENCES "User" (id)
)
 WITHOUT ROWID"""
RULE_INDEXES = ['CREATE INDEX "ix_Rule_owner" ON "Rule" ("ownerId", position)']


def _stored(conn, name: str) -> list[str]:
    """A table's stored columns, not its generated ones."""
    return [r[1] for r in conn.exec_driver_sql(f'PRAGMA table_xinfo("{name}")') if r[6] == 0]


def _swap(conn, name: str, indexes: list[str], new: str | None = None) -> None:
    conn.exec_driver_sql(f'DROP TABLE "{name}"')
    conn.exec_driver_sql(f'ALTER TABLE "_new_{new or name}" RENAME TO "{new or name}"')
    for index in indexes:
        conn.exec_driver_sql(index)


def _insert(conn, table: str, row: dict) -> None:
    listed = ", ".join(f'"{c}"' for c in row)
    marks = ", ".join("?" for _ in row)
    # The names come from the declarations, not from input.
    conn.exec_driver_sql(f'INSERT INTO "{table}" ({listed}) VALUES ({marks})', tuple(row.values()))  # noqa: S608


def _pairs(conn) -> None:
    for name, (renamed, prefix, table, indexes) in PAIRS.items():
        old = _stored(conn, name)
        conn.exec_driver_sql(table)
        new = _stored(conn, f"_new_{renamed}")
        kept = [c for c in old if c in new]
        selected = ", ".join(f'"{c}"' for c in kept)
        for values in conn.exec_driver_sql(f'SELECT {selected} FROM "{name}"').fetchall():  # noqa: S608
            row = dict(zip(kept, values, strict=True))
            # Made as a record when it was made as a pair.
            _insert(conn, f"_new_{renamed}", {"id": ids.new_id(prefix), **row,
                                           "updatedAt": row["createdAt"]})  # fmt: skip
        _swap(conn, name, indexes, renamed)


def _tags(conn) -> None:
    """Each owner's tag names become Tag rows; what named them refers to them by id."""
    conn.exec_driver_sql(TAG)
    for index in TAG_INDEXES:
        conn.exec_driver_sql(index)
    made: dict[tuple[str, str], str] = {}

    def tag(owner: str, name: str, at: str) -> str:
        key = (owner, name.strip().lower())
        if key not in made:
            made[key] = ids.new_id("Tag")
            _insert(conn, "Tag", {"id": made[key], "ownerId": owner, "name": key[1],
                                  "createdAt": at, "updatedAt": at})  # fmt: skip
        return made[key]

    conn.exec_driver_sql(TRANSACTIONTAGS)
    for txn, user, name, at, gone_at, gone_by in conn.exec_driver_sql(
        'SELECT "transactionId", "userId", tag, "createdAt", "deletedAt", "deletedById" '
        'FROM "TransactionTags" ORDER BY "createdAt"'
    ).fetchall():
        row = {"transactionId": txn, "tagId": tag(user, name, at), "createdAt": at,
               "deletedAt": gone_at, "deletedById": gone_by}  # fmt: skip
        if not conn.exec_driver_sql(
            'SELECT 1 FROM "_new_TransactionTags" WHERE "transactionId" = ? AND "tagId" = ?',
            (txn, row["tagId"]),
        ).first():
            _insert(conn, "_new_TransactionTags", row)
    _swap(conn, "TransactionTags", TRANSACTIONTAGS_INDEXES)

    conn.exec_driver_sql(RULETAGS)
    conn.exec_driver_sql(RECEIPTTAGS)
    for rule, owner, names, at in conn.exec_driver_sql(
        'SELECT id, "ownerId", tags, "createdAt" FROM "Rule"'
    ).fetchall():
        for name in sorted(set(json.loads(names or "[]"))):
            _insert(conn, "RuleTags", {"ruleId": rule, "tagId": tag(owner, name, at),
                                       "createdAt": at})  # fmt: skip
    for receipt, owner, names, at in conn.exec_driver_sql(
        'SELECT id, "ownerId", tags, "createdAt" FROM "Receipt"'
    ).fetchall():
        for name in sorted(set(json.loads(names or "[]"))):
            _insert(conn, "ReceiptTags", {"receiptId": receipt, "tagId": tag(owner, name, at),
                                          "createdAt": at})  # fmt: skip

    # The rule's own list goes, with the check that read it; the receipt's too.
    old = [c for c in _stored(conn, "Rule") if c != "tags"]
    conn.exec_driver_sql(RULE)
    listed = ", ".join(f'"{c}"' for c in old)
    conn.exec_driver_sql(f'INSERT INTO "_new_Rule" ({listed}) SELECT {listed} FROM "Rule"')  # noqa: S608
    _swap(conn, "Rule", RULE_INDEXES)
    conn.exec_driver_sql('ALTER TABLE "Receipt" DROP COLUMN tags')


def upgrade() -> None:
    conn = op.get_bind()
    _pairs(conn)
    _tags(conn)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
