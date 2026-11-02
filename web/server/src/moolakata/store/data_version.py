"""The data version (docs/schema.md §8): one number in the database that every write to a table
figures are worked out from moves on, by a trigger, inside the writing transaction.

A reader reads it in its own transaction, so it is the version of exactly the data the reader
sees (SQLite gives a transaction one snapshot): a write that hasn't committed hasn't moved it
for anyone else, and one that has is in the reader's data and its version alike. Figures kept
under it (a budget's months, S7.3.10) are never older than the data they say they are from.

Every table is an input unless it declares why it isn't (`not_figures` on `exception()`), so a
table added later is watched without anyone remembering to: leaving one out costs only speed.
The triggers are generated from the declarations and made again at every start and migration,
as the views are.
"""

from sqlalchemy import Connection, MetaData, Table, text
from sqlalchemy.orm import Session

TABLE = "DataVersion"
ROW = "figures"
PREFIX = "dataVersion_"
OPS = ("INSERT", "UPDATE", "DELETE")


def inputs(metadata: MetaData) -> list[Table]:
    """The tables a write to which moves the version on: all but those declared otherwise."""
    return [t for t in metadata.sorted_tables if not t.info.get("notFigures")]


def trigger_name(table: str, op: str) -> str:
    return f"{PREFIX}{table}_{op.lower()}"


def create_all_sql(metadata: MetaData) -> list[str]:
    return [
        f'CREATE TRIGGER "{trigger_name(t.name, op)}" AFTER {op} ON "{t.name}" '
        f"BEGIN UPDATE \"{TABLE}\" SET version = version + 1 WHERE name = '{ROW}'; END"
        for t in inputs(metadata)
        for op in OPS
    ]


def drop_all_sql(connection: Connection) -> list[str]:
    rows = connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name LIKE ? ESCAPE '\\'",
        (PREFIX.replace("_", "\\_") + "%",),
    ).fetchall()
    return [f'DROP TRIGGER IF EXISTS "{r[0]}"' for r in rows]


def sync(connection: Connection, metadata: MetaData) -> None:
    """Drop every generated trigger and make them again from the declarations; the row is made
    the first time."""
    for sql in drop_all_sql(connection):
        connection.exec_driver_sql(sql)
    for sql in create_all_sql(metadata):
        connection.exec_driver_sql(sql)
    connection.exec_driver_sql(
        f"INSERT OR IGNORE INTO \"{TABLE}\" (name, version) VALUES ('{ROW}', 0)"
    )


def read(s: Session) -> int:
    """The version of the data this session's transaction reads."""
    return s.execute(text(f"SELECT version FROM \"{TABLE}\" WHERE name = '{ROW}'")).scalar_one()


def read_only(s: Session) -> bool:
    """Whether the session's transaction is a read (`Database.read`): only a read's figures may
    be kept, since a write's could still be rolled back after its version was taken."""
    return s.connection().get_execution_options().get("mk_mode") == "read"
