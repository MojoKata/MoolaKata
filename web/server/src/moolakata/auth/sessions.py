"""Sessions (requirements S13.2, S13.7.1): a 256-bit token in the mk_session cookie, stored
as its SHA-256, with idle and absolute lifetimes from Settings. A new token at sign-in and at
every change of privilege; signing out, a password change and deactivation end every session
of that user."""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as Db

from .. import clock, settings
from ..store.entities.users import Session
from .tokens import digest, new_token

COOKIE = "mk_session"


def now() -> dt.datetime:
    return clock.now()


def create(
    s: Db,
    user_id: str,
    admin: bool,
    needs_setup: bool = False,
    auth_at: dt.datetime | None = None,
    address: str | None = None,
) -> str:
    token, token_hash = new_token()
    t = now()
    days = settings.get(s, "sessionAbsoluteDays")
    s.add(
        Session(
            tokenHash=token_hash,
            userId=user_id,
            createdAt=t,
            lastSeenAt=t,
            expiresAt=t + dt.timedelta(days=days),
            address=address,
            authAt=auth_at or t,
            admin=admin,
            needsSetup=needs_setup,
        )
    )
    s.flush()
    return token


@dataclass
class Found:
    session: Session
    ended: str | None  # why it is no longer good: "expired"


def by_hash(s: Db, token_hash: str) -> Session | None:
    """The session its token's hash names: the token itself is never stored."""
    return s.scalars(select(Session).where(Session.tokenHash == token_hash)).first()


def find(s: Db, token: str | None) -> Found | None:
    if not token or len(token) > 100:
        return None
    row = by_hash(s, digest(token))
    if row is None:
        return None
    t = now()
    idle = dt.timedelta(hours=settings.get(s, "sessionIdleHours"))
    if t >= row.expiresAt or t - row.lastSeenAt >= idle:
        return Found(row, "expired")
    return Found(row, None)


def rotate(s: Db, old: Session, admin: bool, needs_setup: bool) -> str:
    """A new token for a change of privilege: the old one stops working."""
    token = create(s, old.userId, admin, needs_setup, auth_at=old.authAt)
    s.delete(old)
    return token


def end(s: Db, token_hash: str) -> None:
    s.execute(delete(Session).where(Session.tokenHash == token_hash))


def end_all(s: Db, user_id: str) -> list[str]:
    hashes = list(s.scalars(select(Session.tokenHash).where(Session.userId == user_id)))
    s.execute(delete(Session).where(Session.userId == user_id))
    return hashes


def prune(s: Db) -> int:
    """Expired sessions are removed outright (schema.md §4.4.1)."""
    t = now()
    idle = dt.timedelta(hours=settings.get(s, "sessionIdleHours"))
    result = s.execute(
        delete(Session).where((Session.expiresAt <= t) | (Session.lastSeenAt <= t - idle))
    )
    return result.rowcount or 0
