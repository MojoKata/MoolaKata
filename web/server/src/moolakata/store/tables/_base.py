"""The columns and constraints every table carries (docs/schema.md §2, §4, §7).

A record table has a prefixed id with its CHECK, is WITHOUT ROWID, and carries the
soft-delete fields with their CHECK, plus `version`, `createdAt` and `updatedAt` for the API's
concurrency rule (requirements S13.8.6). Tables removed outright (schema.md §4.4) say so in
`info["exception"]`. Every table says how it is seen (`Seen`, schema.md §7) in `info["seen"]`.
"""

from dataclasses import dataclass

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    text,
)

from ..types import UtcTimestamp


@dataclass(frozen=True)
class Seen:
    """How a table's records are seen (docs/schema.md §7), which decides its `<Table>Access`
    view: generated for a root, a child, a per-user table or admin data; written by hand for a
    rule of its own; none for a relation, household data or the server's own."""

    how: str
    share: str | None = None  # a root's share kind, and for a share table its target's
    share_prefix: str | None = None  # the prefix of a root's `<Table>Share` table
    key: str | None = None  # a child's parent key, a per-user table's user column
    configurable: bool = False  # a per-user table whose rows hold secrets (Connection)
    # Changing these asks `configurable`, not `writable` (§7.6): an account's settings.
    settings: tuple[str, ...] = ()
    # What any write of a row asks: `configurable` for what a record covers (its accounts).
    writes: str = "writable"

    @staticmethod
    def root(share: str, share_prefix: str, settings: tuple[str, ...] = ()) -> Seen:
        """One of the shareable kinds, by the plain rule: its owner, and its shares (its
        `<Table>Share` table, made with the prefix given)."""
        return Seen("root", share=share, share_prefix=share_prefix, settings=settings)

    @staticmethod
    def child(key: str, writes: str = "writable") -> Seen:
        """Seen as the record its NOT NULL key names is."""
        return Seen("child", key=key, writes=writes)

    @staticmethod
    def rule(share: str | None = None, share_prefix: str | None = None) -> Seen:
        """A view written by hand; `share` when it is a shareable kind with rules of its own,
        with the prefix of its `<Table>Share` table."""
        return Seen("rule", share=share, share_prefix=share_prefix)

    @staticmethod
    def shares(kind: str) -> Seen:
        """A `<Table>Share` table: an item of a shareable kind granted to a user or a group
        (§7). Whoever may share the item holds its shares; a grantee reads their own."""
        return Seen("share", share=kind, key="targetId")

    @staticmethod
    def per_user(key: str, configurable: bool = False) -> Seen:
        return Seen("per-user", key=key, configurable=configurable)

    @staticmethod
    def relation() -> Seen:
        """A pure many-to-many table: reached through one of its sides' views."""
        return Seen("relation")

    @staticmethod
    def household() -> Seen:
        """Read by every signed-in local user; written as code allows."""
        return Seen("household")

    @staticmethod
    def admin() -> Seen:
        return Seen("admin")

    @staticmethod
    def server() -> Seen:
        """Read only by the server's own code, never by a user's query."""
        return Seen("server")


NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=NAMING)


DELETED = '"deletedAt" IS NOT NULL'
DELETED_BY = '"deletedAt" IS NOT NULL OR "deletedById" IS NULL'


def soft_delete(table: str) -> list:
    """`deleted` is generated from `deletedAt`, so the two can't disagree (schema.md §4.1)."""
    return [
        Column("deleted", Boolean, Computed(DELETED, persisted=False)),
        Column("deletedAt", UtcTimestamp),
        Column("deletedById", Text, ForeignKey("User.id")),
        CheckConstraint(DELETED_BY, name="deleted_by"),
    ]


def record(name: str, prefix: str, *columns, seen: Seen, **kw) -> Table:
    """A table of records with a prefixed id (schema.md §2) and soft deletes (§4)."""
    length = len(prefix) + 1 + 26
    return Table(
        name,
        metadata,
        Column("id", Text, primary_key=True),
        *columns,
        Column("version", Integer, nullable=False, server_default=text("1")),
        Column("createdAt", UtcTimestamp, nullable=False),
        Column("updatedAt", UtcTimestamp, nullable=False),
        *soft_delete(name),
        CheckConstraint(f"id GLOB '{prefix}_*' AND length(id) = {length}", name="id"),
        sqlite_with_rowid=False,
        info={"prefix": prefix, "softDelete": True, "seen": seen},
        **kw,
    )


def pairs(name: str, *columns, **kw) -> Table:
    """A many-to-many table: plural name, the pair of keys as its primary key (schema.md §1.2)."""
    return Table(
        name,
        metadata,
        *columns,
        *soft_delete(name),
        Column("createdAt", UtcTimestamp, nullable=False),
        info={"softDelete": True, "pairs": True, "seen": Seen.relation()},
        **kw,
    )


def keyed(name: str, *columns, seen: Seen, **kw) -> Table:
    """A table keyed by name rather than an id, with soft deletes (Settings)."""
    return Table(
        name,
        metadata,
        *columns,
        Column("version", Integer, nullable=False, server_default=text("1")),
        Column("updatedAt", UtcTimestamp, nullable=False),
        *soft_delete(name),
        info={"softDelete": True, "seen": seen},
        **kw,
    )


def exception(
    name: str, reason: str, *columns, seen: Seen, prefix: str | None = None, **kw
) -> Table:
    """A table that schema.md §4.4 removes outright, or never deletes from at all."""
    cols = list(columns)
    info = {"softDelete": False, "exception": reason, "seen": seen}
    if prefix:
        length = len(prefix) + 1 + 26
        cols.insert(0, Column("id", Text, primary_key=True))
        cols.append(CheckConstraint(f"id GLOB '{prefix}_*' AND length(id) = {length}", name="id"))
        info["prefix"] = prefix
        kw.setdefault("sqlite_with_rowid", False)
    return Table(name, metadata, *cols, info=info, **kw)


def unique_live(table: Table, *columns: str, name: str | None = None) -> Index:
    """Uniqueness that ignores deleted records (schema.md §4.3)."""
    return Index(
        name or f"ux_{table.name}_{'_'.join(columns)}",
        *(table.c[c] for c in columns),
        unique=True,
        sqlite_where=text("NOT deleted"),
    )
