"""Every table with values of its own has a synthetic id (docs/schema.md §2): the prices,
a user's typed prices, sessions, one-time tokens, recovery codes, a person's state of an
alert, and a linked copy's missing files and what was last sent a peer. Each is rebuilt the way
SQLite documents (as 0002 does), each row given an id, its old key kept as a unique rule.

Revision: 0039
Follows: 0038
"""

from alembic import op

from moolakata import ids

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None

# Each table as the declarations make it, with its prefix and its indexes.
TABLES = {
    "Price": (
        "Price",
        """CREATE TABLE "_new_Price" (
	id TEXT NOT NULL,
	"instrumentId" TEXT NOT NULL,
	date TEXT NOT NULL,
	close TEXT NOT NULL,
	source TEXT NOT NULL,
	"fetchedAt" TEXT NOT NULL,
	"enteredById" TEXT,
	version INTEGER DEFAULT 1 NOT NULL,
	"createdAt" TEXT NOT NULL,
	"updatedAt" TEXT NOT NULL,
	deleted BOOLEAN GENERATED ALWAYS AS ("deletedAt" IS NOT NULL) VIRTUAL,
	"deletedAt" TEXT,
	"deletedById" TEXT,
	CONSTRAINT "pk_Price" PRIMARY KEY (id),
	CONSTRAINT "ck_Price_deleted_by" CHECK ("deletedAt" IS NOT NULL OR "deletedById" IS NULL),
	CONSTRAINT "ck_Price_id" CHECK (id GLOB 'Price_*' AND length(id) = 32),
	CONSTRAINT "fk_Price_instrumentId_Instrument" FOREIGN KEY("instrumentId") REFERENCES "Instrument" (id),
	CONSTRAINT "fk_Price_enteredById_User" FOREIGN KEY("enteredById") REFERENCES "User" (id),
	CONSTRAINT "fk_Price_deletedById_User" FOREIGN KEY("deletedById") REFERENCES "User" (id)
)
 WITHOUT ROWID""",
        [
            'CREATE INDEX "ix_Price_date" ON "Price" (date)',
            'CREATE UNIQUE INDEX "ux_Price_instrumentId_date" ON "Price" ("instrumentId", date) WHERE NOT deleted',
        ],
    ),
    "TypedPrice": (
        "TyPrc",
        """CREATE TABLE "_new_TypedPrice" (
	id TEXT NOT NULL,
	"instrumentId" TEXT NOT NULL,
	"userId" TEXT NOT NULL,
	date TEXT NOT NULL,
	close TEXT NOT NULL,
	version INTEGER DEFAULT 1 NOT NULL,
	"createdAt" TEXT NOT NULL,
	"updatedAt" TEXT NOT NULL,
	deleted BOOLEAN GENERATED ALWAYS AS ("deletedAt" IS NOT NULL) VIRTUAL,
	"deletedAt" TEXT,
	"deletedById" TEXT,
	CONSTRAINT "pk_TypedPrice" PRIMARY KEY (id),
	CONSTRAINT "ck_TypedPrice_deleted_by" CHECK ("deletedAt" IS NOT NULL OR "deletedById" IS NULL),
	CONSTRAINT "ck_TypedPrice_id" CHECK (id GLOB 'TyPrc_*' AND length(id) = 32),
	CONSTRAINT "fk_TypedPrice_instrumentId_Instrument" FOREIGN KEY("instrumentId") REFERENCES "Instrument" (id),
	CONSTRAINT "fk_TypedPrice_userId_User" FOREIGN KEY("userId") REFERENCES "User" (id),
	CONSTRAINT "fk_TypedPrice_deletedById_User" FOREIGN KEY("deletedById") REFERENCES "User" (id)
)
 WITHOUT ROWID""",
        [
            'CREATE UNIQUE INDEX "ux_TypedPrice_userId_instrumentId_date" ON "TypedPrice" ("userId", "instrumentId", date) WHERE NOT deleted'
        ],
    ),
    "Session": (
        "Sessn",
        """CREATE TABLE "_new_Session" (
	id TEXT NOT NULL,
	"tokenHash" TEXT NOT NULL,
	"userId" TEXT NOT NULL,
	"createdAt" TEXT NOT NULL,
	"lastSeenAt" TEXT NOT NULL,
	"expiresAt" TEXT NOT NULL,
	"authAt" TEXT NOT NULL,
	address TEXT,
	admin BOOLEAN DEFAULT 0 NOT NULL,
	"needsSetup" BOOLEAN DEFAULT 0 NOT NULL,
	CONSTRAINT "pk_Session" PRIMARY KEY (id),
	CONSTRAINT "ck_Session_id" CHECK (id GLOB 'Sessn_*' AND length(id) = 32),
	CONSTRAINT "uq_Session_tokenHash" UNIQUE ("tokenHash"),
	CONSTRAINT "fk_Session_userId_User" FOREIGN KEY("userId") REFERENCES "User" (id)
)
 WITHOUT ROWID""",
        ['CREATE INDEX "ix_Session_userId" ON "Session" ("userId")'],
    ),
    "OneTimeToken": (
        "OTTkn",
        """CREATE TABLE "_new_OneTimeToken" (
	id TEXT NOT NULL,
	"tokenHash" TEXT NOT NULL,
	purpose TEXT NOT NULL,
	"userId" TEXT NOT NULL,
	data TEXT,
	"createdAt" TEXT NOT NULL,
	"expiresAt" TEXT NOT NULL,
	CONSTRAINT "pk_OneTimeToken" PRIMARY KEY (id),
	CONSTRAINT "ck_OneTimeToken_purpose" CHECK (purpose IN ('invitation', 'reset', 'email-change', 'two-step')),
	CONSTRAINT "ck_OneTimeToken_id" CHECK (id GLOB 'OTTkn_*' AND length(id) = 32),
	CONSTRAINT "uq_OneTimeToken_tokenHash" UNIQUE ("tokenHash"),
	CONSTRAINT "fk_OneTimeToken_userId_User" FOREIGN KEY("userId") REFERENCES "User" (id)
)
 WITHOUT ROWID""",
        ['CREATE INDEX "ix_OneTimeToken_userId" ON "OneTimeToken" ("userId")'],
    ),
    "RecoveryCode": (
        "RCode",
        """CREATE TABLE "_new_RecoveryCode" (
	id TEXT NOT NULL,
	"codeHash" TEXT NOT NULL,
	"userId" TEXT NOT NULL,
	"createdAt" TEXT NOT NULL,
	CONSTRAINT "pk_RecoveryCode" PRIMARY KEY (id),
	CONSTRAINT "ck_RecoveryCode_id" CHECK (id GLOB 'RCode_*' AND length(id) = 32),
	CONSTRAINT "uq_RecoveryCode_codeHash" UNIQUE ("codeHash"),
	CONSTRAINT "fk_RecoveryCode_userId_User" FOREIGN KEY("userId") REFERENCES "User" (id)
)
 WITHOUT ROWID""",
        ['CREATE INDEX "ix_RecoveryCode_userId" ON "RecoveryCode" ("userId")'],
    ),
    "AlertState": (
        "AlSt",
        """CREATE TABLE "_new_AlertState" (
	id TEXT NOT NULL,
	"alertId" TEXT NOT NULL,
	"userId" TEXT NOT NULL,
	"seenAt" TEXT,
	"dismissedAt" TEXT,
	"emailedAt" TEXT,
	CONSTRAINT "pk_AlertState" PRIMARY KEY (id),
	CONSTRAINT "uq_AlertState_alertId_userId" UNIQUE ("alertId", "userId"),
	CONSTRAINT "ck_AlertState_id" CHECK (id GLOB 'AlSt_*' AND length(id) = 31),
	CONSTRAINT "fk_AlertState_alertId_Alert" FOREIGN KEY("alertId") REFERENCES "Alert" (id),
	CONSTRAINT "fk_AlertState_userId_User" FOREIGN KEY("userId") REFERENCES "User" (id)
)
 WITHOUT ROWID""",
        ['CREATE INDEX "ix_AlertState_userId" ON "AlertState" ("userId")'],
    ),
    "LinkFile": (
        "LkFil",
        """CREATE TABLE "_new_LinkFile" (
	id TEXT NOT NULL,
	"linkId" TEXT NOT NULL,
	"fileId" TEXT NOT NULL,
	"fileName" TEXT,
	tries INTEGER DEFAULT 0 NOT NULL,
	"missedAt" TEXT NOT NULL,
	error TEXT,
	CONSTRAINT "pk_LinkFile" PRIMARY KEY (id),
	CONSTRAINT "uq_LinkFile_linkId_fileId" UNIQUE ("linkId", "fileId"),
	CONSTRAINT "ck_LinkFile_id" CHECK (id GLOB 'LkFil_*' AND length(id) = 32),
	CONSTRAINT "fk_LinkFile_linkId_Link" FOREIGN KEY("linkId") REFERENCES "Link" (id) ON DELETE CASCADE
)
 WITHOUT ROWID""",
        [],
    ),
    "LinkSent": (
        "LkSnt",
        """CREATE TABLE "_new_LinkSent" (
	id TEXT NOT NULL,
	"linkId" TEXT NOT NULL,
	"itemId" TEXT NOT NULL,
	path TEXT NOT NULL,
	viewer TEXT NOT NULL,
	hash TEXT NOT NULL,
	CONSTRAINT "pk_LinkSent" PRIMARY KEY (id),
	CONSTRAINT "uq_LinkSent_linkId_itemId_path_viewer" UNIQUE ("linkId", "itemId", path, viewer),
	CONSTRAINT "ck_LinkSent_id" CHECK (id GLOB 'LkSnt_*' AND length(id) = 32),
	CONSTRAINT "fk_LinkSent_linkId_Link" FOREIGN KEY("linkId") REFERENCES "Link" (id) ON DELETE CASCADE
)
 WITHOUT ROWID""",
        [],
    ),
}


def _stored(conn, name: str) -> list[str]:
    """A table's stored columns, not its generated ones."""
    return [r[1] for r in conn.exec_driver_sql(f'PRAGMA table_xinfo("{name}")') if r[6] == 0]


def upgrade() -> None:
    conn = op.get_bind()
    for name, (prefix, table, indexes) in TABLES.items():
        old = _stored(conn, name)
        conn.exec_driver_sql(table)
        new = _stored(conn, f"_new_{name}")
        kept = [c for c in old if c in new]
        made = "createdAt" in new and "createdAt" not in old  # made when it was last changed
        columns = ["id", *kept, *(["createdAt"] if made else [])]
        listed = ", ".join(f'"{c}"' for c in columns)
        marks = ", ".join("?" for _ in columns)
        # The names come from sqlite_master and the declarations, not from input.
        selected = ", ".join(f'"{c}"' for c in kept)
        for row in conn.exec_driver_sql(f'SELECT {selected} FROM "{name}"').fetchall():  # noqa: S608
            values = [ids.new_id(prefix), *row]
            if made:
                values.append(row[kept.index("updatedAt")])
            conn.exec_driver_sql(
                f'INSERT INTO "_new_{name}" ({listed}) VALUES ({marks})',  # noqa: S608
                tuple(values),
            )
        conn.exec_driver_sql(f'DROP TABLE "{name}"')
        conn.exec_driver_sql(f'ALTER TABLE "_new_{name}" RENAME TO "{name}"')
        for index in indexes:
            conn.exec_driver_sql(index)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
