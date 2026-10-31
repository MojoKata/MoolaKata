"""Reads scoped to a user (docs/schema.md §7.6). A session opened for a user's request carries
the user, and every ORM query in it reads only the records the user's access views give them:
each table with a view gets `EXISTS (SELECT 1 FROM <Table>Access WHERE targetId = id AND
userId = :user)` beside whatever the query asks, for each such table it reads at its top
level, joined or aliased. The server's own work opens a session
unscoped, naming why, so every way around the views can be found by its reason."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Join, Select, Table, event, exists, or_
from sqlalchemy.orm import ORMExecuteState, Session

from . import access_views
from .tables import metadata

KEY = "access"


class Unscoped(Exception):
    """A query of a table with an access view in a session that names neither a user nor why
    it reads as the server."""


def scope_user(s: Session, user_id: str) -> None:
    s.info[KEY] = {"user": user_id}


def scope_server(s: Session, why: str) -> None:
    if not why:
        raise ValueError("an unscoped session says why")
    s.info[KEY] = {"unscoped": why}


def user_of(s: Session) -> str | None:
    """The user a session reads for, or None for the server's own."""
    return (s.info.get(KEY) or {}).get("user")


def _base(f) -> Table | None:
    """The table a FROM reads: itself, or what an alias names."""
    while not isinstance(f, Table):
        f = getattr(f, "element", None)
        if f is None:
            return None
    return f


def _froms(f, outer: bool = False):
    """Each table or alias a FROM holds, and whether it may be missing (the optional side of
    an outer join), through every join."""
    if isinstance(f, Join):
        yield from _froms(f.left, outer or f.full)
        yield from _froms(f.right, outer or f.isouter or f.full)
    else:
        yield f, outer


def criteria(statement, user_id: str) -> list:
    """For each table with an access view the statement reads at its top level, directly or
    joined, under its own name or an alias: the user reads the row (or, on the optional side
    of an outer join, there is none)."""
    out = []
    for top in statement.get_final_froms():
        for f, outer in _froms(top):
            base = _base(f)
            if base is None or base.name not in metadata.tables:
                continue
            if not access_views.has_view(metadata.tables[base.name]):
                continue
            # Its own alias, so it correlates only to the record, even when the query joins
            # the same view for the permissions. The user is a bound value, so a cached
            # statement can't carry one user's id into another's query.
            view = access_views.access_table(metadata.tables[base.name]).alias()
            readable = (
                exists()
                .where(view.c.targetId == f.c.id, view.c.userId == user_id)
                .correlate_except(view)
            )
            out.append(or_(f.c.id.is_(None), readable) if outer else readable)
    return out


@contextmanager
def as_server(s: Session, why: str) -> Iterator[Session]:
    """The server's own work inside a user's request (a wash sale worked out across spouses, an
    item's figures, S7.1.1, S8.14.2): a second session on the same connection, so it is part
    of the same transaction, reading as the server, its records never mixed with the user's
    (§7.6)."""
    s.flush()
    # In a savepoint of the request's transaction: committing it keeps what it did for the
    # request's own commit, and an error undoes only its part before the request's rollback.
    with Session(
        bind=s.connection(),
        expire_on_commit=False,
        autoflush=True,
        join_transaction_mode="create_savepoint",
    ) as server:
        scope_server(server, why)
        yield server
        server.commit()
    # What it changed is read afresh by the user's session.
    s.expire_all()


def unscoped(statement, why: str):
    """One statement read as the server inside a user's session: what it reads is used by the
    server (a Setting's value, whether a file is kept already), never handed to the user. It
    selects columns, never records, so nothing it reads joins the session's records (§7.6)."""
    return statement.execution_options(unscoped=why)


@event.listens_for(Session, "do_orm_execute")
def _scope(state: ORMExecuteState) -> None:
    if not state.is_select or state.is_column_load:
        # A refresh reloads a record already in the session, which a scoped query brought.
        return
    if state.execution_options.get("unscoped"):
        for d in state.statement.column_descriptions:
            if d.get("entity") is not None and d.get("expr") is d.get("entity"):
                raise Unscoped("an unscoped statement selects columns, never records")
        return
    access = state.session.info.get(KEY)
    if access is None:
        if isinstance(state.statement, Select) and criteria(state.statement, "?"):
            raise Unscoped(
                "a session reads for a user (db.read(user=…)) or names why it reads as the "
                "server (db.read(unscoped=…))"
            )
        return
    user_id = access.get("user")
    if user_id is None:
        return
    if isinstance(state.statement, Select):
        found = criteria(state.statement, user_id)
        if found:
            state.statement = state.statement.where(*found)
