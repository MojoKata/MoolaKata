"""Who may see and change what (requirements S10.3–S10.7, S13.8.10), as the access views
say (docs/schema.md §7): a record a user reads has a row in its table's view, with what more
they may do. Something the caller can't see answers 404, never revealing whether it exists;
something they read but may not change, 403.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, inspect, select
from sqlalchemy.orm import Session

from .errors import Problem
from .store import access_views
from .store.access_views import COLUMNS, PERMISSIONS
from .store.entities.accounts import Account
from .store.entities.budgets import Budget
from .store.entities.sharing import Portfolio


@dataclass(frozen=True)
class Perms:
    """What a user may do with a record they read, and whether it is theirs, from its access
    view. `mine` is a fact, never a permission: nothing is allowed by it (`need` asks only
    the four)."""

    writable: bool
    deletable: bool
    shareable: bool
    configurable: bool
    mine: bool

    def child(self) -> Perms:
        """A child's, from its parent's, as its generated view has it (docs/schema.md §7.1)."""
        return Perms(
            writable=self.writable,
            deletable=self.writable,
            shareable=False,
            configurable=self.configurable,
            mine=self.mine,
        )


# An owner's: everything, and theirs (a portfolio made of one's own accounts, S5.1).
OWNER = Perms(True, True, True, True, True)
# Reading alone.
READ = Perms(False, False, False, False, False)


def _view(entity):
    return access_views.access_table(inspect(entity).local_table)


def perms(s: Session, entity, item_id: str, user_id: str) -> Perms | None:
    """The user's permissions on a record, or None when they don't read it."""
    v = _view(entity)
    row = s.execute(
        select(*(v.c[p] for p in COLUMNS)).where(v.c.targetId == item_id, v.c.userId == user_id)
    ).first()
    return None if row is None else Perms(*(bool(x) for x in row))


def need(s: Session, entity, item_id: str, user_id: str, permission: str | None = None, what=None):
    """The record and the user's permissions on it: 404 when they don't read it, never
    saying whether it exists; 403 without the permission asked for."""
    if permission is not None and permission not in PERMISSIONS:
        raise ValueError(f"{permission!r} is not a permission")
    p = perms(s, entity, item_id, user_id) if item_id else None
    obj = s.get(entity, item_id) if p is not None else None
    if obj is None:
        raise Problem(404, "not-found", "Not found")
    if permission is None or getattr(p, permission):
        return obj, p
    what = what or entity.__name__.lower()
    if permission == "writable":
        raise Problem(403, "share-read-only", f"You can read this {what} but not change it.")
    if permission == "shareable":
        raise Problem(403, "owner-only", "Only the owner changes who this is shared with.")
    raise Problem(403, "owner-only", f"Only the {what}'s owner can do this.")


def listing(s: Session, entity, user_id: str, *where, order_by=None) -> list[tuple[Any, Perms]]:
    """The records of a kind the user reads, with their permissions, joined to the kind's
    view: the same in a user's session and in the server's."""
    v = _view(entity)
    q = (
        select(entity, *(v.c[p] for p in COLUMNS))
        .join(v, and_(v.c.targetId == entity.id, v.c.userId == user_id))
        .where(*where)
    )
    if order_by is not None:
        q = q.order_by(*(order_by if isinstance(order_by, tuple) else (order_by,)))
    return [(r[0], Perms(*(bool(x) for x in r[1:]))) for r in s.execute(q)]


def _want(want: str) -> str | None:
    """*read*, *write* or a permission's name: the permission asked for."""
    return {"read": None, "write": "writable"}.get(want, want)


def account(s: Session, user_id: str, account_id: str, want: str = "read") -> tuple[Any, Perms]:
    """An account the user reads, and what they may do with it."""
    return need(s, Account, account_id, user_id, _want(want), "account")


def portfolio(s: Session, user_id: str, portfolio_id: str, want: str = "read") -> tuple[Any, Perms]:
    return need(s, Portfolio, portfolio_id, user_id, _want(want), "portfolio")


def budget(s: Session, user_id: str, budget_id: str, want: str = "read") -> tuple[Any, Perms]:
    return need(s, Budget, budget_id, user_id, _want(want), "budget")


def accounts(s: Session, user_id: str, *where) -> list[tuple[Any, Perms]]:
    """The accounts the user reads, by name, with their permissions."""
    return listing(s, Account, user_id, *where, order_by=Account.name)


def entity_of(kind: str):
    """The entity a share's kind names (Share.kind)."""
    from .store.mapping import mapper_registry

    table = access_views.SUBJECTS[kind]
    return next(m.class_ for m in mapper_registry.mappers if m.local_table.name == table)


def entity_of_table(name: str):
    """The entity mapped onto a table, by the table's name."""
    from .store.mapping import mapper_registry

    return next(m.class_ for m in mapper_registry.mappers if m.local_table.name == name)


def holders_of(s: Session, entity, item_id: str) -> dict[str, Perms]:
    """Everyone who reads a record, with their permissions."""
    v = _view(entity)
    return {
        r[0]: Perms(*(bool(x) for x in r[1:]))
        for r in s.execute(
            select(v.c.userId, *(v.c[p] for p in COLUMNS)).where(v.c.targetId == item_id)
        )
    }
