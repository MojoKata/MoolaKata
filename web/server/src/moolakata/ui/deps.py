"""Who is calling (requirements S13.2, S13.7.1): the session behind the mk_session cookie."""

import datetime as dt
from dataclasses import dataclass

from fastapi import Depends, Request

from ..auth import sessions
from ..auth.users import is_admin
from ..errors import Problem
from ..store.entities.users import Session, User

REAUTH_MINUTES = 10
TOUCH_SECONDS = 60


@dataclass
class Caller:
    user: User
    session: Session
    admin: bool

    @property
    def id(self) -> str:
        return self.user.id


def server(request: Request):
    return request.app.state.server


def set_cookie(request: Request, token: str | None) -> None:
    """The SessionCookie middleware writes it on the response; None clears it."""
    request.state.set_cookie = token if token is not None else ""


def _resolve(request: Request, allow_setup: bool, touch: bool) -> Caller:
    """Most requests only read: a write (and its lock) is taken only to remove an ended
    session, to rotate the token, or to note the session's use once a minute."""
    srv = server(request)
    token = request.cookies.get(sessions.COOKIE)
    with srv.db.read() as s:
        found = sessions.find(s, token)
        user = s.get(User, found.session.userId) if found else None
        admin = is_admin(s, user.id) if user is not None else False
    if found is None:
        raise Problem(401, "not-signed-in", "Sign in to continue.")
    row = found.session
    gone = user is None or user.deleted or not user.active
    rotate = (
        not found.ended and not gone and (admin != row.admin or user.needsSetup != row.needsSetup)
    )
    stale_touch = touch and (sessions.now() - row.lastSeenAt).total_seconds() >= TOUCH_SECONDS
    if found.ended or gone or rotate or stale_touch:
        with srv.db.tx() as s:
            if found.ended:
                # Removed outright, and committed before the refusal (schema.md §4.4.1).
                sessions.end(s, row.tokenHash)
            elif gone:
                sessions.end_all(s, row.userId)
            else:
                live = sessions.by_hash(s, row.tokenHash)
                if live is not None and rotate:
                    # A change of privilege: a new token; the old one never works again.
                    new = sessions.rotate(s, live, admin, user.needsSetup)
                    set_cookie(request, new)
                    live = sessions.find(s, new).session
                if live is not None and stale_touch:
                    live.lastSeenAt = sessions.now()
                row = live or row
    if found.ended:
        raise Problem(401, "session-expired", "Your session ended. Sign in again.")
    if gone:
        raise Problem(401, "account-disabled", "This account is disabled.")
    if row.needsSetup and not allow_setup:
        raise Problem(403, "setup-required", "Finish setting up the admin account first.")
    srv.api_limit.check(row.tokenHash, "requests")
    request.state.user_id = user.id
    return Caller(user, row, admin)


def caller(request: Request) -> Caller:
    return _resolve(request, allow_setup=False, touch=True)


def caller_in_setup(request: Request) -> Caller:
    return _resolve(request, allow_setup=True, touch=True)


def caller_quiet(request: Request) -> Caller:
    """For the live stream: it never extends the session (S12.6)."""
    return _resolve(request, allow_setup=True, touch=False)


def admin(c: Caller = Depends(caller)) -> Caller:
    if not c.admin:
        raise Problem(403, "admins-only", "Only admins can do this.")
    return c


def recent_auth(c: Caller) -> None:
    """Re-authentication (S13.7.2): the password again if last given over 10 minutes ago."""
    if sessions.now() - c.session.authAt > dt.timedelta(minutes=REAUTH_MINUTES):
        raise Problem(403, "reauth-required", "Enter your password again to do this.")
