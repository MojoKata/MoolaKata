"""A loan's rows an import left out, dated before the loan starts (requirements S1.9.3):
`ImportLeftOut`, one record per row kept with why, a child of its import. The imports made so
far left none out.

Revision: 0077
Follows: 0076
"""

from alembic import op

revision = "0077"
down_revision = "0076"
branch_labels = None
depends_on = None

TABLE = """CREATE TABLE "ImportLeftOut" (
	id TEXT NOT NULL,
	"importId" TEXT NOT NULL,
	date TEXT NOT NULL,
	kind TEXT NOT NULL,
	amount INTEGER NOT NULL,
	payee TEXT,
	memo TEXT,
	"fitId" TEXT,
	reason TEXT NOT NULL,
	version INTEGER DEFAULT 1 NOT NULL,
	"createdAt" TEXT NOT NULL,
	"updatedAt" TEXT NOT NULL,
	deleted BOOLEAN GENERATED ALWAYS AS ("deletedAt" IS NOT NULL) VIRTUAL,
	"deletedAt" TEXT,
	"deletedById" TEXT,
	CONSTRAINT "pk_ImportLeftOut" PRIMARY KEY (id),
	CONSTRAINT "ck_ImportLeftOut_deleted_by" CHECK ("deletedAt" IS NOT NULL OR "deletedById" IS NULL),
	CONSTRAINT "ck_ImportLeftOut_id" CHECK (id GLOB 'ImpLO_*' AND length(id) = 32),
	CONSTRAINT "fk_ImportLeftOut_importId_Import" FOREIGN KEY("importId") REFERENCES "Import" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_ImportLeftOut_deletedById_User" FOREIGN KEY("deletedById") REFERENCES "User" (id)
)
 WITHOUT ROWID"""
INDEX = 'CREATE INDEX "ix_ImportLeftOut_importId" ON "ImportLeftOut" ("importId")'


def upgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(TABLE)
    conn.exec_driver_sql(INDEX)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
