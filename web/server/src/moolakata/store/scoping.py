"""Reads scoped to a user (docs/schema.md §7.6). A session opened for a user's request carries
the user, and every ORM query in it reads only the records the user's access views give them:
each table with a view gets `EXISTS (SELECT 1 FROM <Table>Access WHERE targetId = id AND
userId = :user)` beside whatever the query asks. The server's own work opens a session
unscoped, naming why, so every way around the views can be found by its reason."""

from functools import cache

from sqlalchemy import Table, event, exists
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria
from sqlalchemy.sql.util import find_tables

from . import access_views

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


@cache
def _entities() -> dict[Table, type]:
    from .mapping import map_all, mapper_registry

    map_all()
    return {
        m.local_table: m.class_
        for m in mapper_registry.mappers
        if access_views.has_view(m.local_table)
    }


def criteria(statement, user_id: str) -> list:
    """The loader criteria scoping a statement's tables with views to a user."""
    entities = _entities()
    out = []
    for t in {t for t in find_tables(statement, include_joins=True, include_aliases=True)}:
        base = getattr(t, "element", t)  # an alias's table
        entity = entities.get(base)
        if entity is None:
            continue
        # Its own alias, so it correlates only to the record, even when the query joins the
        # same view for the permissions. A plain expression, never a lambda: the user is a
        # bound value, so a cached statement can't carry one user's id into another's query.
        view = access_views.access_table(base).alias()
        readable = (
            exists()
            .where(view.c.targetId == entity.id, view.c.userId == user_id)
            .correlate_except(view)
        )
        out.append(with_loader_criteria(entity, readable, include_aliases=True))
    return out


def unscoped(statement, why: str):
    """One statement read as the server inside a user's session: what it reads is used by the
    server (a Setting's value, whether a file is kept already), never handed to the user. It
    selects columns, never records, so nothing it reads joins the session's records (§7.6)."""
    return statement.execution_options(unscoped=why)


@event.listens_for(Session, "do_orm_execute")
def _scope(state: ORMExecuteState) -> None:
    if not state.is_select:
        return
    if state.execution_options.get("unscoped"):
        for d in state.statement.column_descriptions:
            if d.get("entity") is not None and d.get("expr") is d.get("entity"):
                raise Unscoped("an unscoped statement selects columns, never records")
        return
    access = state.session.info.get(KEY)
    user_id = access.get("user") if access else None
    if user_id is None:
        return
    found = criteria(state.statement, user_id)
    if found:
        state.statement = state.statement.options(*found)
