"""The schema checks of docs/schema.md §5 (store/schema_check.py): each break a table declaration,
schema.md's tables or a migrated database can have is named, in its words."""

import pytest
from sqlalchemy import Boolean, CheckConstraint, Column, Computed, ForeignKey, MetaData, Table, Text

from moolakata.store import access_views, schema_check, views
from moolakata.store.tables import metadata
from moolakata.store.tables._base import DELETED, DELETED_BY, Seen

SERVER = {"softDelete": False, "exception": "§4.4", "seen": Seen.server()}


def _prefixes(*rows: str, reserved: tuple[str, ...] = ()) -> str:
    """schema.md §3 with these rows in use, then these reserved."""
    used = "\n".join(f"| {r} |" for r in rows)
    kept = "\n".join(f"| {r} |" for r in reserved)
    return (
        "## 3. Prefixes\n\n### 3.1 Tables\n\n| Prefix | Table |\n|---|---|\n"
        f"{used}\n\n### 3.2 Reserved\n\n| Prefix | Table |\n|---|---|\n{kept}\n"
    )


def _problems(md: MetaData, text: str = _prefixes()) -> list[str]:
    return schema_check.check_metadata(md, text)


def _soft(name: str, md: MetaData, *columns, **info) -> Table:
    """A soft-deleting table with its fields and CHECK, seen as the server's own."""
    return Table(
        name,
        md,
        *columns,
        Column("deleted", Boolean, Computed(DELETED)),
        Column("deletedAt", Text),
        Column("deletedById", Text),
        CheckConstraint(DELETED_BY),
        info={"softDelete": True, "seen": Seen.server(), **info},
    )


def test_schema_md_s_prefix_tables_are_sorted_and_each_prefix_listed_once():
    """§5.2: each list of §3 sorted by prefix, and no prefix twice across them."""
    text = _prefixes("Zeta | Zeta", "Alpha | Alpha", reserved=("Yy | Yes", "Bb | Bee", "Alpha | A"))
    assert _problems(MetaData(), text) == [
        "schema.md §3: the in use prefixes are not sorted by prefix",
        "schema.md §3: the reserved prefixes are not sorted by prefix",
        "schema.md §3: prefix Alpha is listed twice",
        "schema.md §3 names Zeta, which is not a table",
        "schema.md §3 names Alpha, which is not a table",
    ]


def test_a_tables_prefix_is_the_one_its_row_gives_and_a_reserved_one_is_not_in_use():
    """§5.2: a table with an id has its row in §3, in use and with its own prefix."""
    md = MetaData()
    for name in ("Thing", "Spare"):
        Table(name, md, Column("id", Text, primary_key=True), sqlite_with_rowid=False,
              info={**SERVER, "prefix": "Thng"})  # fmt: skip
    found = _problems(md, _prefixes("Thg | Thing", reserved=("Spare | Spare",)))
    assert "Thing: prefix Thng but schema.md §3 says Thg" in found
    assert "Spare is still under Reserved in schema.md §3" in found
    assert "Thing lacks the CHECK on its id's form" in found


@pytest.mark.parametrize(
    ("name", "column", "pairs", "said"),
    [
        ("thing_x", "id", False, "table thing_x: names are capitalized words"),
        ("HTMLPage", "id", False, "table HTMLPage: write acronyms as words"),
        ("ThingTag", "id", True, "table ThingTag: a many-to-many table's name is plural"),
        ("Things", "id", False, "table Things: names are singular"),
        ("Thing", "Bad_Name", False, "Thing.Bad_Name: field names are camelCase"),
        ("Thing", "theHTMLText", False, "Thing.theHTMLText: write acronyms as words"),
    ],
)
def test_each_naming_rule_is_named_when_broken(name, column, pairs, said):
    """§5.1: tables are singular capitalized words (many-to-many ones plural), fields
    camelCase, acronyms written as words."""
    md = MetaData()
    seen = Seen.relation() if pairs else Seen.server()
    Table(name, md, Column(column, Text), info={**SERVER, "seen": seen, "pairs": pairs})
    assert said in _problems(md)


def test_a_class_name_ending_ss_is_singular():
    md = MetaData()
    Table("Class", md, Column("name", Text), info=SERVER)
    assert _problems(md) == []


@pytest.mark.parametrize(
    ("build", "said"),
    [
        (
            lambda md: Table("Things", md, Column("a", Text), info={**SERVER, "pairs": True,
                                                                  "seen": Seen.server()}),
            "Things: a many-to-many table is a relation",
        ),
        (
            lambda md: Table("Part", md, Column("thingId", Text),
                             info={**SERVER, "seen": Seen.child("thingId")}),
            "Part.thingId: a child's key is a NOT NULL foreign key",
        ),
        (
            lambda md: (
                Table("Thing", md, Column("id", Text, primary_key=True), info=SERVER),
                Table("Part", md, Column("thingId", Text, ForeignKey("Thing.id"), nullable=False),
                      info={**SERVER, "seen": Seen.child("thingId")}),
            ),
            "Part.thingId: its parent has no access view",
        ),
        (
            lambda md: Table("ThingShare", md, Column("targetId", Text),
                             info={**SERVER, "seen": Seen.shares("thing")}),
            "ThingShare.targetId: a share's item is a NOT NULL key to a shared table",
        ),
        (
            lambda md: Table("Note", md, Column("text", Text),
                             info={**SERVER, "seen": Seen.per_user("userId")}),
            "Note: no column userId for its user",
        ),
        (
            lambda md: Table("Note", md, Column("text", Text),
                             info={**SERVER, "seen": Seen.rule()}),
            "Note: its access view is not written",
        ),
    ],
)  # fmt: skip
def test_how_a_table_is_seen_holds_together(build, said):
    """§5.5: a relation for a many-to-many table; a child's or a share's key a NOT NULL key to
    a table with an access view; a per-user table's user column there; a rule's view
    written."""
    md = MetaData()
    build(md)
    assert said in _problems(md)


def test_a_tables_soft_delete_is_declared_and_whole():
    """§5.4: a table says whether it soft-deletes; an exception cites §4.4; a soft-deleting
    one has `deleted` generated, virtual, from `deletedAt` and the CHECK on who deleted it."""
    md = MetaData()
    Table("Plain", md, Column("a", Text), info={"seen": Seen.server()})
    Table("Gone", md, Column("a", Text), info={"softDelete": False, "seen": Seen.server()})
    Table("Typed", md, Column("deleted", Boolean), Column("deletedAt", Text),
          Column("deletedById", Text), CheckConstraint(DELETED_BY),
          info={"softDelete": True, "seen": Seen.server()})  # fmt: skip
    Table("Stored", md, Column("deleted", Boolean, Computed(DELETED, persisted=True)),
          Column("deletedAt", Text), Column("deletedById", Text), CheckConstraint(DELETED_BY),
          info={"softDelete": True, "seen": Seen.server()})  # fmt: skip
    _soft("Whole", md)
    Table("Unchecked", md, Column("deleted", Boolean, Computed(DELETED)),
          Column("deletedAt", Text), Column("deletedById", Text),
          info={"softDelete": True, "seen": Seen.server()})  # fmt: skip
    assert set(_problems(md)) == {
        "Plain: say whether it soft-deletes",
        "Gone: an exception must cite schema.md §4.4",
        "Typed.deleted is not generated from deletedAt",
        "Stored.deleted is not generated from deletedAt",
        "Unchecked lacks the soft-delete CHECK",
    }


def _with(db, *sql: str) -> list[str]:
    """What the checks find in the migrated database once `sql` has run, in a transaction left
    undone."""
    with db.engine.connect() as conn:
        raw = conn.connection.dbapi_connection
        raw.execute("PRAGMA foreign_keys = OFF")
        conn.exec_driver_sql("SAVEPOINT broken")
        try:
            for statement in sql:
                conn.exec_driver_sql(statement)
            return schema_check.check_database(conn, metadata)
        finally:
            conn.exec_driver_sql("ROLLBACK TO broken")
            conn.rollback()
            raw.execute("PRAGMA foreign_keys = ON")


def test_a_view_missing_or_changed_is_named(db, monkeypatch):
    """§5.4, §5.5: every Effective and access view there, as generated now, an access view
    with its seven columns. The declarations are made to want what the database lacks, so no
    view another reads is touched."""
    real_tables, real_sql, real_made = views.soft_tables, views.view_sql, access_views.all_sql
    ghost = Table("Ghost", MetaData(), Column("id", Text))
    monkeypatch.setattr(views, "soft_tables", lambda md: [*real_tables(md), ghost])
    monkeypatch.setattr(
        views, "view_sql", lambda t: "SELECT 1" if t.name == "Account" else real_sql(t)
    )
    odd = 'CREATE VIEW "OddAccess" AS SELECT 1 AS "targetId", 2 AS "userId"'
    made = real_made(metadata)
    leaf = next(n for n in made if n.endswith(access_views.SUFFIX))
    monkeypatch.setattr(
        access_views,
        "all_sql",
        lambda md: {**made, "NoneAccess": "x", leaf: "CREATE VIEW x AS SELECT 2", "OddAccess": odd},
    )
    assert _with(db, odd) == [
        "view AccountEffective does not match Account's cascading keys",
        "view GhostEffective is missing",
        f"view {leaf} is not as generated now",
        "view NoneAccess is missing",
        "view OddAccess has columns ['targetId', 'userId']",
    ]


def test_a_table_missing_or_unlike_its_declaration_is_named(db):
    """§5.3: every table there, WITHOUT ROWID with an id, with each CHECK it declares."""
    assert _with(db, 'ALTER TABLE "TaskRun" RENAME TO "Gone"') == [
        "table TaskRun is missing from the database"
    ]
    rebuilt = (
        'CREATE TABLE "Setting" (id TEXT PRIMARY KEY, key TEXT, value TEXT, "updatedById" TEXT, '
        'version INTEGER, "createdAt" TEXT, "updatedAt" TEXT, deleted BOOLEAN, '
        '"deletedAt" TEXT, "deletedById" TEXT)'
    )
    found = _with(db, 'ALTER TABLE "Setting" RENAME TO "Old"', rebuilt)
    assert "table Setting is not WITHOUT ROWID in the database" in found
    assert any(p.startswith("table Setting lacks CHECK (") for p in found)
