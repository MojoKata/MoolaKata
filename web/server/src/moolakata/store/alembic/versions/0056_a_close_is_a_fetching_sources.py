"""A close is a fetching source's (requirements S4.6): `Price.source` is never `manual`, the
source that fetches nothing (a typed price is a `TypedPrice`, 0022), and `Price.enteredById`,
which only such a close carried, goes. A `manual` close left from before 0022 is removed.

Revision: 0056
Follows: 0055
"""

from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None

TABLE = "Price"
EDITS = (
    ('\t"enteredById" TEXT,\n', ""),
    (
        '\tCONSTRAINT "fk_Price_enteredById_User" FOREIGN KEY("enteredById") REFERENCES "User" (id),\n',
        "",
    ),
    (
        "\tCONSTRAINT \"ck_Price_id\" CHECK (id GLOB 'Price_*' AND length(id) = 32),\n",
        "\tCONSTRAINT \"ck_Price_id\" CHECK (id GLOB 'Price_*' AND length(id) = 32),\n"
        "\tCONSTRAINT \"ck_Price_source\" CHECK (source <> 'manual'),\n",
    ),
)


def upgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql("DELETE FROM \"Price\" WHERE source = 'manual'")
    sql = conn.exec_driver_sql(
        f"SELECT sql FROM sqlite_master WHERE type = 'table' AND name = '{TABLE}'"  # noqa: S608
    ).scalar_one()
    new = sql
    for old, replacement in EDITS:
        if new.count(old) != 1:
            raise RuntimeError(f"{TABLE}: unexpected declarations")
        new = new.replace(old, replacement)
    stored = [
        r[1]
        for r in conn.exec_driver_sql(f'PRAGMA table_xinfo("{TABLE}")').fetchall()
        if r[6] == 0 and r[1] != "enteredById"
    ]
    indexes = conn.exec_driver_sql(
        f"SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = '{TABLE}' "  # noqa: S608
        "AND sql IS NOT NULL"
    ).fetchall()
    head = f'CREATE TABLE "{TABLE}" ('
    conn.exec_driver_sql(f'CREATE TABLE "_new_{TABLE}" (' + new[len(head) :])
    listed = ", ".join(f'"{c}"' for c in stored)
    # The names come from sqlite_master, not from input.
    conn.exec_driver_sql(f'INSERT INTO "_new_{TABLE}" ({listed}) SELECT {listed} FROM "{TABLE}"')  # noqa: S608
    conn.exec_driver_sql(f'DROP TABLE "{TABLE}"')
    conn.exec_driver_sql(f'ALTER TABLE "_new_{TABLE}" RENAME TO "{TABLE}"')
    for (index_sql,) in indexes:
        conn.exec_driver_sql(index_sql)


def downgrade() -> None:
    raise NotImplementedError("MoolaKata migrates forward only; restore a backup to go back")
