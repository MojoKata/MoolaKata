"""A gift's holding period (requirements S1.10.1): `Item.heldFrom`, the day the giver's holding
began, for an item received as a gift at the giver's basis; never after the day acquired. Every
item made before has none. And `Item.primaryResidence` goes: whether a home is anyone's main
home is its periods lived in (`ResidencePeriod`, 0062; S1.10.4), never a flag on the home.

Revision: 0061
Follows: 0060
"""

from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None

TABLE = "Item"
DROPPED = ("primaryResidence",)
EDITS = (
    ('\t"primaryResidence" BOOLEAN DEFAULT 0 NOT NULL, \n', ""),
    ('\t"acquiredOn" TEXT NOT NULL, \n', '\t"acquiredOn" TEXT NOT NULL, \n\t"heldFrom" TEXT, \n'),
    (
        '\tCONSTRAINT "pk_Item" PRIMARY KEY (id), \n',
        '\tCONSTRAINT "pk_Item" PRIMARY KEY (id), \n'
        '\tCONSTRAINT "ck_Item_held_from" CHECK ("heldFrom" IS NULL OR '
        '("acquiredHow" = \'gift\' AND "heldFrom" <= "acquiredOn")), \n',
    ),
)


def upgrade() -> None:
    """The table made again with the columns and their checks, its rows and indexes kept, less the
    dropped column."""
    conn = op.get_bind()
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (TABLE,)
    ).scalar_one()
    new = sql
    for old, added in EDITS:
        if new.count(old) != 1:
            raise RuntimeError(f"{TABLE}: unexpected declarations")
        new = new.replace(old, added)
    stored = [
        r[1]
        for r in conn.exec_driver_sql(f'PRAGMA table_xinfo("{TABLE}")').fetchall()
        if r[6] == 0 and r[1] not in DROPPED
    ]
    indexes = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL",
        (TABLE,),
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
