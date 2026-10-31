"""The connector's two keys (requirements S18.4.2, review 3's CR3-65): the key that signs its
calls is its action key, kept in its vault, and a status key, kept beside the vault, signs only
a report that it is locked and `unpaired`. MoolaKata holds both public halves.

Revision: 0043
Follows: 0042
"""

from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


STATUS = ('\t"pageAddress" TEXT, \n', '\t"pageAddress" TEXT, \n\t"statusKey" TEXT, \n')


def rebuild(conn, name: str, edits: list[tuple[str, str]], drop: tuple[str, ...] = ()) -> None:
    sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).scalar_one()
    stored = [
        r[1]
        for r in conn.exec_driver_sql(f'PRAGMA table_xinfo("{name}")').fetchall()
        if r[6] == 0 and r[1] not in drop
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
    conn.exec_driver_sql('DROP INDEX "ux_Connector_identityKey"')
    conn.exec_driver_sql('ALTER TABLE "Connector" RENAME COLUMN "identityKey" TO "actionKey"')
    rebuild(conn, "Connector", [STATUS])
    for key in ("actionKey", "statusKey"):
        conn.exec_driver_sql(
            f'CREATE UNIQUE INDEX "ux_Connector_{key}" ON "Connector" ("{key}") WHERE NOT deleted'
        )


def downgrade() -> None:
    conn = op.get_bind()
    for key in ("actionKey", "statusKey"):
        conn.exec_driver_sql(f'DROP INDEX "ux_Connector_{key}"')
    rebuild(conn, "Connector", [(STATUS[1], STATUS[0])], drop=("statusKey",))
    conn.exec_driver_sql('ALTER TABLE "Connector" RENAME COLUMN "actionKey" TO "identityKey"')
    conn.exec_driver_sql(
        'CREATE UNIQUE INDEX "ux_Connector_identityKey" ON "Connector" ("identityKey") '
        "WHERE NOT deleted"
    )
