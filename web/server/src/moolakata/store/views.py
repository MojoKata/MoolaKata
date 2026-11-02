"""The `<Table>Effective` views (docs/schema.md §4.2), generated from the table declarations.

A record is effectively deleted when it is deleted itself or when anything it is deleted with is:
*deleted with* is a foreign key declared ondelete="CASCADE" to a soft-deletable table. Each view
chains its parents' views, so a new cascading key changes the view with it.
"""

from functools import cache
from graphlib import TopologicalSorter

from sqlalchemy import Boolean, Column, MetaData, Table, Text

from .types import UtcTimestamp

FAR = "'~'"  # sorts after every timestamp


def view_name(table: str) -> str:
    return f"{table}Effective"


def parents(table: Table) -> list[tuple[str, str]]:
    """(column, parent table) for each cascading key to a soft-deletable table."""
    out = []
    for fk in sorted(table.foreign_keys, key=lambda f: f.parent.name):
        parent = fk.column.table
        if fk.ondelete and fk.ondelete.upper() == "CASCADE" and parent.info.get("softDelete"):
            if parent is table:
                raise ValueError(
                    f"{table.name}.{fk.parent.name}: a table cannot belong to "
                    "itself; use a plain key"
                )
            out.append((fk.parent.name, parent.name))
    return out


_views = MetaData()


@cache
def view_table(table: Table) -> Table:
    """The view as a selectable: the table's keys plus the two effective columns."""
    keys = [Column(c.name, Text, primary_key=True) for c in table.primary_key.columns]
    return Table(
        view_name(table.name),
        _views,
        *keys,
        Column("effectiveDeleted", Boolean),
        Column("effectiveDeletedAt", UtcTimestamp),
    )


def soft_tables(metadata: MetaData) -> list[Table]:
    return [t for t in metadata.sorted_tables if t.info.get("softDelete")]


def view_sql(table: Table) -> str:
    ps = parents(table)
    deleted = ["t.deleted"] + [f'coalesce(p{i}."effectiveDeleted", 0)' for i in range(len(ps))]
    if ps:
        times = ['coalesce(t."deletedAt", ' + FAR + ")"] + [
            f'coalesce(p{i}."effectiveDeletedAt", {FAR})' for i in range(len(ps))
        ]
        at = f"nullif(min({', '.join(times)}), {FAR})"
    else:
        at = 't."deletedAt"'
    joins = "".join(
        f'\n  LEFT JOIN "{view_name(parent)}" AS p{i} ON p{i}.id = t."{col}"'
        for i, (col, parent) in enumerate(ps)
    )
    return (
        f'CREATE VIEW "{view_name(table.name)}" AS\n'
        f'SELECT t.*,\n  ({" OR ".join(deleted)}) AS "effectiveDeleted",\n'
        f'  {at} AS "effectiveDeletedAt"\nFROM "{table.name}" AS t{joins}'
    )


def ordered(metadata: MetaData) -> list[Table]:
    """Parents' views before their children's."""
    tables = {t.name: t for t in soft_tables(metadata)}
    graph = {name: {p for _, p in parents(t)} for name, t in tables.items()}
    return [tables[n] for n in TopologicalSorter(graph).static_order()]


def create_all_sql(metadata: MetaData) -> list[str]:
    return [view_sql(t) for t in ordered(metadata)]


def drop_all_sql(connection) -> list[str]:
    """Every generated view, the access views (§7) that read the Effective views first; and the
    data version's triggers (§8), so a migration runs without them."""
    from . import access_views

    rows = connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type = 'view' AND name LIKE '%Effective'"
    ).fetchall()
    from . import data_version

    return (
        data_version.drop_all_sql(connection)
        + access_views.drop_all_sql(connection)
        + [f'DROP VIEW IF EXISTS "{r[0]}"' for r in rows]
    )


def sync(connection, metadata: MetaData, *, access: bool = True) -> None:
    """Drop every generated view and create them again from the declarations: the Effective
    views, then the access views built on them (schema.md §7); and the data version's triggers
    (§8)."""
    from . import access_views, data_version

    for sql in drop_all_sql(connection):
        connection.exec_driver_sql(sql)
    made = create_all_sql(metadata)
    if access:
        made += access_views.create_all_sql(metadata)
    for sql in made:
        connection.exec_driver_sql(sql)
    if data_version.TABLE in metadata.tables:
        data_version.sync(connection, metadata)
