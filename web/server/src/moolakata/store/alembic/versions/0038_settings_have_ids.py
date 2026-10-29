"""A setting is a record with an id of its own (docs/schema.md §2), its key a field of it
with one live row a key: the table is rebuilt the way SQLite documents (as 0002 does), each
saved setting given an id, made when it was last saved.

Revision: 0038
Follows: 0037
"""

from alembic import op

from moolakata import ids

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

TABLE = """CREATE TABLE "_new_Setting" (
	id TEXT NOT NULL,
	"key" TEXT NOT NULL,
	value TEXT NOT NULL,
	"updatedById" TEXT,
	version INTEGER DEFAULT 1 NOT NULL,
	"createdAt" TEXT NOT NULL,
	"updatedAt" TEXT NOT NULL,
	deleted BOOLEAN GENERATED ALWAYS AS ("deletedAt" IS NOT NULL) VIRTUAL,
	"deletedAt" TEXT,
	"deletedById" TEXT,
	CONSTRAINT "pk_Setting" PRIMARY KEY (id),
	CONSTRAINT "ck_Setting_deleted_by" CHECK ("deletedAt" IS NOT NULL OR "deletedById" IS NULL),
	CONSTRAINT "ck_Setting_id" CHECK (id GLOB 'Setng_*' AND length(id) = 32),
	CONSTRAINT "fk_Setting_updatedById_User" FOREIGN KEY("updatedById") REFERENCES "User" (id),
	CONSTRAINT "fk_Setting_deletedById_User" FOREIGN KEY("deletedById") REFERENCES "User" (id)
)
 WITHOUT ROWID"""


def upgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(TABLE)
    rows = conn.exec_driver_sql(
        'SELECT "key", value, "updatedById", version, "updatedAt", "deletedAt", "deletedById" '
        'FROM "Setting"'
    ).fetchall()
    for key, value, by, version, at, deleted_at, deleted_by in rows:
        conn.exec_driver_sql(
            'INSERT INTO "_new_Setting" (id, "key", value, "updatedById", version, "createdAt", '
            '"updatedAt", "deletedAt", "deletedById") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (ids.new_id("Setng"), key, value, by, version, at, at, deleted_at, deleted_by),
        )
    conn.exec_driver_sql('DROP TABLE "Setting"')
    conn.exec_driver_sql('ALTER TABLE "_new_Setting" RENAME TO "Setting"')
    conn.exec_driver_sql(
        'CREATE UNIQUE INDEX "ux_Setting_key" ON "Setting" ("key") WHERE NOT deleted'
    )


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
