"""No answer names a record its reader can't read (decision 5.5 of the access-views walk):
every GET route, called by each user of a household with partial access, is read for ids,
and each id of a table with an access view must be in that user's view."""

import re

import pytest
from conftest import sign_in
from sqlalchemy import text
from test_access import household  # noqa: F401

from moolakata import contract
from moolakata.dev.seed import PASSWORD
from moolakata.store import access_views
from moolakata.store.tables import metadata

ID = re.compile(r"\b([A-Z][A-Za-z]{0,4})_[0-9a-z]{26}\b")
USERS = ("admin", "alice", "bob", "dave", "erin")

# A path parameter, and the table whose records fill it: one the caller reads.
PARAMS = {
    "account_id": "Account",
    "budget_id": "Budget",
    "book_id": "TaxBook",
    "link_id": "Link",
    "portfolio_id": "Portfolio",
    "receipt_id": "Receipt",
    "person_id": "Person",
    "txn_id": "Transaction",
    "transaction_id": "Transaction",
    "item_id": "Item",
    "projection_id": "Projection",
}
# Routes the sweep can't fill: their parameters name no record a user reads.
UNFILLED = {"name", "file_id", "job_id", "instrument_id", "kind"}
# The live stream answers with events, not records, and stays open (S12.6).
STREAMS = {"/ui/api/events"}


def _tables():
    by_prefix = {t.info["prefix"]: t for t in metadata.sorted_tables if t.info.get("prefix")}
    return by_prefix


def reads(srv, table: str, item_id: str, user_id: str) -> bool:
    """Whether the user reads the record now: entries made during the sweep (a sign-in's
    Activity) count too."""
    with srv.db.read(unscoped="test") as s:
        name = access_views.access_name(table)
        return (
            s.execute(
                text(f'SELECT 1 FROM "{name}" WHERE "targetId" = :i AND "userId" = :u'),
                {"i": item_id, "u": user_id},
            ).first()
            is not None
        )


def readable(srv) -> dict[str, set[str]]:
    """The records each table's view holds for anyone: what a path parameter may name."""
    out = {}
    with srv.db.read(unscoped="test") as s:
        for t in metadata.sorted_tables:
            if access_views.has_view(t):
                name = access_views.access_name(t.name)
                out[t.name] = set(
                    s.execute(text(f'SELECT "targetId", "userId" FROM "{name}"')).all()
                )
    return out


def ids_in(body) -> set[tuple[str, str]]:
    return {(m.group(1), m.group(0)) for m in ID.finditer(body)}


@pytest.mark.parametrize("who", USERS)
def test_no_answer_names_what_its_reader_cant_read(household, who):  # noqa: F811
    srv, named = household
    views = readable(srv)
    tables = _tables()
    with srv.db.read(unscoped="test") as s:
        users = dict(
            s.execute(text('SELECT username, id FROM "User" WHERE "linkId" IS NULL')).all()
        )
    uid = users[who]
    c = sign_in(srv, who, PASSWORD)
    paths = [p for p, ops in contract.openapi_document()["paths"].items() if "get" in ops]
    leaks: dict[tuple[str, str, str], str] = {}
    called = 0
    for path in paths:
        params = re.findall(r"\{(\w+)\}", path)
        if set(params) & UNFILLED or path in STREAMS:
            continue
        filled = {}
        for p in params:
            mine = {i for i, u in views[PARAMS[p]] if u == uid}
            # The household's own edge cases first (a receipt kept on both sides of a share),
            # else the first the user reads.
            picks = [i for i in named.values() if i in mine] or sorted(mine)[:1]
            if not picks:
                break
            filled[p] = picks[0]
        else:
            try:
                r = c.get(path.format(**filled))
            except Exception as e:
                raise AssertionError(f"{who} GET {path}: {e!r}") from e
            called += 1
            if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
                continue
            for prefix, found in ids_in(r.text):
                t = tables.get(prefix)
                if t is None or t.name not in views or (who, t.name, path) in leaks:
                    continue
                if not reads(srv, t.name, found, uid):
                    leaks[(who, t.name, path)] = found
    assert called > 40
    found = sorted(k for k in leaks if k[1:] not in KNOWN)
    assert not found, "\n" + "\n".join(f"{w} {t} {p} {leaks[(w, t, p)]}" for w, t, p in found)


# Answers that name what their reader can't read, on purpose, with why.
KNOWN: dict[tuple[str, str], str] = {
    ("Account", "/ui/api/tax-books/{book_id}"): (
        "S8.14.2: a tax book counts its filers' accounts and names them to whoever reads it"
    ),
    ("Account", "/ui/api/settings/connector"): (
        "S16.2: the connector's page names the accounts each connection keeps current"
    ),
    ("TaxBook", "/ui/api/tax-books"): (
        "S8.14.1: a filer named on a book sees it, its year and filers, to accept it"
    ),
}


def test_raw_sql_outside_the_store_reads_no_table_with_a_view():
    """Raw SQL is never scoped (schema.md §7.6): outside store/, no `text()` or
    `exec_driver_sql()` names a table with an access view (decision 5.5)."""
    import ast
    from pathlib import Path

    import moolakata

    root = Path(moolakata.__file__).parent
    viewed = {t.name for t in metadata.sorted_tables if access_views.has_view(t)}
    found = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if rel.parts[0] in ("store", "dev"):
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            f = node.func
            name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
            if name not in ("text", "exec_driver_sql"):
                continue
            sql = "".join(
                n.value
                for n in ast.walk(node.args[0])
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
            )
            for table in re.findall(r'"([A-Z][A-Za-z]+)"', sql):
                if table in viewed:
                    found.append(f"{rel}:{node.lineno} {table}")
    assert found == []
