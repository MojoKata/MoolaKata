"""The periods a home was lived in (requirements S1.10.4, S8.13): `ResidencePeriod`, each one
person's span of a real-estate item as their main home, from which its sale shows each person's
years lived in. Homes made before have none.

Revision: 0062
Follows: 0061
"""

from alembic import op

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None

TABLE = """CREATE TABLE "ResidencePeriod" (
	id TEXT NOT NULL,
	"itemId" TEXT NOT NULL,
	"personId" TEXT NOT NULL,
	"fromDate" TEXT NOT NULL,
	"toDate" TEXT,
	"createdById" TEXT,
	version INTEGER DEFAULT 1 NOT NULL,
	"createdAt" TEXT NOT NULL,
	"updatedAt" TEXT NOT NULL,
	deleted BOOLEAN GENERATED ALWAYS AS ("deletedAt" IS NOT NULL) VIRTUAL,
	"deletedAt" TEXT,
	"deletedById" TEXT,
	CONSTRAINT "pk_ResidencePeriod" PRIMARY KEY (id),
	CONSTRAINT "ck_ResidencePeriod_dates" CHECK ("toDate" IS NULL OR "toDate" >= "fromDate"),
	CONSTRAINT "ck_ResidencePeriod_deleted_by" CHECK ("deletedAt" IS NOT NULL OR "deletedById" IS NULL),
	CONSTRAINT "ck_ResidencePeriod_id" CHECK (id GLOB 'RsPrd_*' AND length(id) = 32),
	CONSTRAINT "fk_ResidencePeriod_itemId_Item" FOREIGN KEY("itemId") REFERENCES "Item" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_ResidencePeriod_personId_Person" FOREIGN KEY("personId") REFERENCES "Person" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_ResidencePeriod_createdById_User" FOREIGN KEY("createdById") REFERENCES "User" (id),
	CONSTRAINT "fk_ResidencePeriod_deletedById_User" FOREIGN KEY("deletedById") REFERENCES "User" (id)
)
 WITHOUT ROWID"""
INDEXES = (
    'CREATE INDEX "ix_ResidencePeriod_item" ON "ResidencePeriod" ("itemId", "fromDate")',
    'CREATE INDEX "ix_ResidencePeriod_person" ON "ResidencePeriod" ("personId", "fromDate")',
)


def upgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(TABLE)
    for index in INDEXES:
        conn.exec_driver_sql(index)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
