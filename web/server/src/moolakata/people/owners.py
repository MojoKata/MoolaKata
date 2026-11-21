"""Who owns what a caller is shown (requirements S10.1.7): the owner of a shared record is
named to whom it is shared, an inactive one too, marked so."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..store import scoping
from ..store.entities.users import User


@dataclass(frozen=True)
class Owner:
    name: str
    avatar: str | None
    active: bool


def of(s: Session, user_ids: set[str]) -> dict[str, Owner]:
    """The owners named, read as the server: the household reads only its active users
    (S10.4), but what an inactive user shared stays shared, and theirs (S10.1.7). Only the
    name, the picture and whether they are active are read, of owners of records the caller
    already sees."""
    if not user_ids:
        return {}
    # Only reads, and the caller's records stay as read: no change here shows.
    why = "the owners of what a caller is shown"  # pragma: no mutate
    with scoping.as_server(s, why, expire=False) as srv:  # pragma: no mutate
        return {
            u.id: Owner(u.displayName, u.avatar, u.active)
            for u in srv.scalars(select(User).where(User.id.in_(list(user_ids))))
        }
