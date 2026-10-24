"""A budget's method and options, where its money comes from, and its lines' reserves,
projections and overspending (requirements S7.1, S7.2.1, S7.10, S7.13).

Revision: 0031
Follows: 0030
"""

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

BUDGET = [
    (
        "\tname TEXT NOT NULL, \n",
        "\tname TEXT NOT NULL, \n\tmethod TEXT DEFAULT 'tracking' NOT NULL, \n"
        "\treserves BOOLEAN DEFAULT 0 NOT NULL, \n\tmoves BOOLEAN DEFAULT 0 NOT NULL, \n"
        '\t"startMonth" TEXT, \n',
    ),
    (
        "\tCONSTRAINT \"ck_Budget_id\" CHECK (id GLOB 'Bdgt_*' AND length(id) = 31), \n",
        "\tCONSTRAINT \"ck_Budget_id\" CHECK (id GLOB 'Bdgt_*' AND length(id) = 31), \n"
        "\tCONSTRAINT \"ck_Budget_method\" CHECK (method IN ('tracking', 'envelope')), \n",
    ),
]
ACCOUNTS = [
    (
        '\t"accountId" TEXT NOT NULL, \n',
        '\t"accountId" TEXT NOT NULL, \n\t"movedFromId" TEXT, \n\t"paidFromId" TEXT, \n',
    ),
    (
        '\tCONSTRAINT "fk_BudgetAccounts_deletedById_User" FOREIGN KEY("deletedById") '
        'REFERENCES "User" (id)\n',
        '\tCONSTRAINT "fk_BudgetAccounts_deletedById_User" FOREIGN KEY("deletedById") '
        'REFERENCES "User" (id), \n'
        '\tCONSTRAINT "fk_BudgetAccounts_movedFromId_Account" FOREIGN KEY("movedFromId") '
        'REFERENCES "Account" (id), \n'
        '\tCONSTRAINT "fk_BudgetAccounts_paidFromId_Account" FOREIGN KEY("paidFromId") '
        'REFERENCES "Account" (id)\n',
    ),
]
LINE = [
    (
        "\trollover BOOLEAN DEFAULT 0 NOT NULL, \n",
        "\trollover BOOLEAN DEFAULT 0 NOT NULL, \n\toverspend TEXT DEFAULT 'carry' NOT NULL, \n"
        '\t"projectionId" TEXT, \n\ttarget INTEGER, \n\t"heldInId" TEXT, \n',
    ),
    (
        "\tCONSTRAINT \"ck_BudgetLine_cadence\" CHECK (cadence IN ('month', 'year')), \n",
        "\tCONSTRAINT \"ck_BudgetLine_cadence\" CHECK (cadence IN ('month', 'year')), \n"
        "\tCONSTRAINT \"ck_BudgetLine_overspend\" CHECK (overspend IN ('carry', 'next')), \n",
    ),
    (
        '\tCONSTRAINT "fk_BudgetLine_deletedById_User" FOREIGN KEY("deletedById") '
        'REFERENCES "User" (id)\n',
        '\tCONSTRAINT "fk_BudgetLine_deletedById_User" FOREIGN KEY("deletedById") '
        'REFERENCES "User" (id), \n'
        '\tCONSTRAINT "fk_BudgetLine_heldInId_Account" FOREIGN KEY("heldInId") '
        'REFERENCES "Account" (id), \n'
        '\tCONSTRAINT "fk_BudgetLine_projectionId_Projection" FOREIGN KEY("projectionId") '
        'REFERENCES "Projection" (id)\n',
    ),
]


def rebuild(conn, name: str, edits: list[tuple[str, str]]) -> None:
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).scalar_one()
    stored = [
        r[1] for r in conn.exec_driver_sql(f'PRAGMA table_xinfo("{name}")').fetchall() if r[6] == 0
    ]
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL",
        (name,),
    ).fetchall()
    new = sql
    for old, replacement in edits:
        if new.count(old) != 1:
            raise RuntimeError(f"{name}: unexpected declarations")
        new = new.replace(old, replacement)
    head = f'CREATE TABLE "{name}" ('
    conn.exec_driver_sql(f'CREATE TABLE "_new_{name}" (' + new[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(f'INSERT INTO "_new_{name}" ({listed}) SELECT {listed} FROM "{name}"')  # noqa: S608
    conn.exec_driver_sql(f'DROP TABLE "{name}"')
    conn.exec_driver_sql(f'ALTER TABLE "_new_{name}" RENAME TO "{name}"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)


def upgrade() -> None:
    conn = op.get_bind()
    rebuild(conn, "Budget", BUDGET)
    rebuild(conn, "BudgetAccounts", ACCOUNTS)
    rebuild(conn, "BudgetLine", LINE)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
