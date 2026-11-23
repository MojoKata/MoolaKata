"""A reviewed month's figures per viewer (requirements S7.14, S7.1.1): `BudgetReviewViewer`, the
figures as one person the budget is shared with saw them when it was marked, so each is
compared with their own. `BudgetReview.figures` goes; a review made before keeps its figures
as its reviewer's, and anyone else sees who reviewed it with nothing changed until it is
marked again.

Revision: 0063
Follows: 0062
"""

from alembic import op

from moolakata import ids

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None

TABLE = """CREATE TABLE "BudgetReviewViewer" (
	id TEXT NOT NULL,
	"reviewId" TEXT NOT NULL,
	"userId" TEXT NOT NULL,
	figures TEXT NOT NULL,
	version INTEGER DEFAULT 1 NOT NULL,
	"createdAt" TEXT NOT NULL,
	"updatedAt" TEXT NOT NULL,
	deleted BOOLEAN GENERATED ALWAYS AS ("deletedAt" IS NOT NULL) VIRTUAL,
	"deletedAt" TEXT,
	"deletedById" TEXT,
	CONSTRAINT "pk_BudgetReviewViewer" PRIMARY KEY (id),
	CONSTRAINT "ck_BudgetReviewViewer_deleted_by" CHECK ("deletedAt" IS NOT NULL OR "deletedById" IS NULL),
	CONSTRAINT "ck_BudgetReviewViewer_id" CHECK (id GLOB 'BdgVw_*' AND length(id) = 32),
	CONSTRAINT "fk_BudgetReviewViewer_reviewId_BudgetReview" FOREIGN KEY("reviewId") REFERENCES "BudgetReview" (id) ON DELETE CASCADE,
	CONSTRAINT "fk_BudgetReviewViewer_userId_User" FOREIGN KEY("userId") REFERENCES "User" (id),
	CONSTRAINT "fk_BudgetReviewViewer_deletedById_User" FOREIGN KEY("deletedById") REFERENCES "User" (id)
)
 WITHOUT ROWID"""
INDEX = (
    'CREATE UNIQUE INDEX "ux_BudgetReviewViewer_reviewId_userId" ON "BudgetReviewViewer" '
    '("reviewId", "userId") WHERE NOT deleted'
)


def upgrade() -> None:
    conn = op.get_bind()
    kept = conn.exec_driver_sql(
        'SELECT id, "reviewedById", figures, "createdAt", "updatedAt", "deletedAt", '
        '"deletedById" FROM "BudgetReview" WHERE "reviewedById" IS NOT NULL'
    ).fetchall()
    conn.exec_driver_sql(TABLE)
    conn.exec_driver_sql(INDEX)
    for review_id, by, figures, made, changed, gone, gone_by in kept:
        conn.exec_driver_sql(
            'INSERT INTO "BudgetReviewViewer" (id, "reviewId", "userId", figures, version, '
            '"createdAt", "updatedAt", "deletedAt", "deletedById") '
            "VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)",
            (ids.new_id("BdgVw"), review_id, by, figures, made, changed, gone, gone_by),
        )
    conn.exec_driver_sql('ALTER TABLE "BudgetReview" DROP COLUMN figures')


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
