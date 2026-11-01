"""The checks of docs/schema.md §5, run by the test suite against the table declarations and
a database migrated to head."""

import re
from dataclasses import dataclass

from sqlalchemy import MetaData, Table

from .. import paths
from . import access_views, views
from .tables._base import DELETED, DELETED_BY, Seen

SCHEMA_MD = paths.ROOT / "docs" / "schema.md"
INFRA = {"SchemaRevision"}
CAMEL = re.compile(r"^[a-z][a-zA-Z0-9]*$")
SOFT_FIELDS = {"deleted", "deletedAt", "deletedById"}


@dataclass(frozen=True)
class PrefixRow:
    prefix: str
    table: str
    reserved: bool


def prefix_rows(text: str | None = None) -> list[PrefixRow]:
    """The rows of schema.md §3's two tables: prefixes in use, then reserved ones."""
    text = text if text is not None else SCHEMA_MD.read_text()
    section = text.split("## 3. Prefixes", 1)[1].split("\n## ", 1)[0]
    rows, reserved = [], False
    for line in section.splitlines():
        if line.startswith("### ") and "Reserved" in line:
            reserved = True
        m = re.match(r"^\|\s*([A-Z][A-Za-z]{0,4})\s*\|\s*([A-Za-z]+)\s*\|", line)
        if m and m.group(1) != "Prefix":
            rows.append(PrefixRow(m.group(1), m.group(2), reserved))
    return rows


def check_metadata(metadata: MetaData, text: str | None = None) -> list[str]:
    problems: list[str] = []
    rows = prefix_rows(text)
    in_use = [r for r in rows if not r.reserved]
    for group, label in ((in_use, "in use"), ([r for r in rows if r.reserved], "reserved")):
        prefixes = [r.prefix for r in group]
        if prefixes != sorted(prefixes):
            problems.append(f"schema.md §3: the {label} prefixes are not sorted by prefix")
    seen: dict[str, str] = {}
    for r in rows:
        if r.prefix in seen:
            problems.append(f"schema.md §3: prefix {r.prefix} is listed twice")
        seen[r.prefix] = r.table
    documented = {r.table: r.prefix for r in in_use}
    reserved_tables = {r.table for r in rows if r.reserved}

    for t in metadata.sorted_tables:
        problems += _check_names(t)
        has_id = "id" in t.c
        prefix = t.info.get("prefix")
        if has_id:
            if t.name not in documented:
                where = "is still under Reserved" if t.name in reserved_tables else "has no row"
                problems.append(f"{t.name} {where} in schema.md §3")
            elif documented[t.name] != prefix:
                problems.append(
                    f"{t.name}: prefix {prefix} but schema.md §3 says {documented[t.name]}"
                )
            if t.dialect_options["sqlite"].get("with_rowid", True):
                problems.append(f"{t.name} is not WITHOUT ROWID")
            if not _has_id_check(t, prefix):
                problems.append(f"{t.name} lacks the CHECK on its id's form")
        problems += _check_soft_delete(t)
        problems += _check_seen(t)
    for r in in_use:
        if r.table not in metadata.tables:
            problems.append(f"schema.md §3 names {r.table}, which is not a table")
    return problems


def _check_names(t: Table) -> list[str]:
    out = []
    pairs = bool(t.info.get("pairs"))
    if not re.match(r"^[A-Z][A-Za-z]*$", t.name) and t.name not in INFRA:
        out.append(f"table {t.name}: names are capitalized words")
    if re.search(r"[A-Z]{3}", t.name):
        out.append(f"table {t.name}: write acronyms as words")
    if pairs and not t.name.endswith("s"):
        out.append(f"table {t.name}: a many-to-many table's name is plural")
    if not pairs and t.name.endswith("s") and not t.name.endswith("ss"):
        out.append(f"table {t.name}: names are singular")
    for c in t.c:
        if not CAMEL.match(c.name):
            out.append(f"{t.name}.{c.name}: field names are camelCase")
        elif re.search(r"[A-Z]{3}", c.name):
            out.append(f"{t.name}.{c.name}: write acronyms as words")
    return out


def _check_seen(t: Table) -> list[str]:
    """How it is seen (schema.md §7): declared, and a child's key a NOT NULL key to a table
    with a view."""
    how = t.info.get("seen")
    if not isinstance(how, Seen):
        return [f"{t.name}: say how it is seen (schema.md §7)"]
    if t.info.get("pairs") and how.how != "relation":
        return [f"{t.name}: a many-to-many table is a relation"]
    if how.how == "child":
        fk = [f for f in t.foreign_keys if f.parent.name == how.key]
        if not fk or t.c[how.key].nullable:
            return [f"{t.name}.{how.key}: a child's key is a NOT NULL foreign key"]
        if not access_views.has_view(fk[0].column.table):
            return [f"{t.name}.{how.key}: its parent has no access view"]
    if how.how == "share":
        fk = [f for f in t.foreign_keys if f.parent.name == how.key]
        if not fk or t.c[how.key].nullable or not access_views.has_view(fk[0].column.table):
            return [f"{t.name}.{how.key}: a share's item is a NOT NULL key to a shared table"]
    if how.how == "per-user" and how.key not in t.c:
        return [f"{t.name}: no column {how.key} for its user"]
    if how.how == "rule" and t.name not in access_views.WRITTEN:
        return [f"{t.name}: its access view is not written"]
    return []


def _has_id_check(t: Table, prefix: str | None) -> bool:
    want = f"id GLOB '{prefix}_*' AND length(id) = {len(prefix or '') + 27}"
    return any(
        getattr(c, "sqltext", None) is not None and str(c.sqltext) == want for c in t.constraints
    )


def _check_soft_delete(t: Table) -> list[str]:
    if t.info.get("softDelete") is False:
        reason = t.info.get("exception", "")
        return [] if "§4.4" in reason else [f"{t.name}: an exception must cite schema.md §4.4"]
    if t.info.get("softDelete") is not True:
        return [f"{t.name}: say whether it soft-deletes"]
    out = []
    missing = SOFT_FIELDS - set(t.c.keys())
    if missing:
        out.append(f"{t.name} lacks {sorted(missing)}")
    else:
        computed = t.c.deleted.computed
        if computed is None or str(computed.sqltext) != DELETED or computed.persisted:
            out.append(f"{t.name}.deleted is not generated from deletedAt")
        texts = {str(getattr(c, "sqltext", "")) for c in t.constraints}
        if DELETED_BY not in texts:
            out.append(f"{t.name} lacks the soft-delete CHECK")
    return out


def check_database(connection, metadata: MetaData) -> list[str]:
    """Every soft-deleting table has its Effective view, matching its cascading keys, and every
    table with an access view has it as generated now, with its seven columns (§7)."""
    problems = []
    have = {
        name: sql
        for name, sql in connection.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master WHERE type = 'view'"
        ).fetchall()
    }
    for t in views.soft_tables(metadata):
        name = views.view_name(t.name)
        if name not in have:
            problems.append(f"view {name} is missing")
        elif have[name].strip() != views.view_sql(t).strip():
            problems.append(f"view {name} does not match {t.name}'s cascading keys")
    made = access_views.all_sql(metadata)
    for name, sql in made.items():
        if name not in have:
            problems.append(f"view {name} is missing")
        elif have[name].strip() != sql.strip():
            problems.append(f"view {name} is not as generated now")
        elif name.endswith(access_views.SUFFIX):
            cols = [r[1] for r in connection.exec_driver_sql(f'PRAGMA table_info("{name}")')]
            if cols != ["targetId", "userId", *access_views.COLUMNS]:
                problems.append(f"view {name} has columns {cols}")
    for t in metadata.sorted_tables:
        sql = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (t.name,)
        ).scalar()
        if sql is None:
            problems.append(f"table {t.name} is missing from the database")
        else:
            if "id" in t.c and "WITHOUT ROWID" not in sql.upper():
                problems.append(f"table {t.name} is not WITHOUT ROWID in the database")
            for c in t.constraints:
                check = getattr(c, "sqltext", None)
                if check is not None and str(check) not in sql:
                    problems.append(f"table {t.name} lacks CHECK ({check}) in the database")
    return problems
