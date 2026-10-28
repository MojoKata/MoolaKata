"""Access tokens for the MCP endpoint (requirements S10.9.1): made by a user for themself, shown
once as `mkt_<id>.<secret>`, kept as a hash of the secret, and good until they expire, are
revoked, their user is made inactive, or their user's password is changed or reset (S10.9.4).
A token reads what its user can see, or only the accounts and portfolios chosen for it."""

import datetime as dt
import hashlib
import hmac
import json
import secrets

from sqlalchemy.orm import Session

from . import clock, ids
from .store.entities.users import AccessToken, User

PREFIX = "mkt_"
DAYS = (30, 90, 365)
KINDS = ("account", "portfolio")


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def make(
    s: Session,
    user_id: str,
    name: str,
    scope: str,
    items: list[dict],
    days: int,
    token_id: str | None = None,
) -> tuple[AccessToken, str]:
    """A new token and the text shown once."""
    secret = secrets.token_urlsafe(32)
    t = AccessToken(
        id=token_id or ids.new_id("Token"),
        userId=user_id,
        name=name,
        scope=scope,
        items=json.dumps(items if scope == "chosen" else []),
        secretHash=_hash(secret),
        expiresAt=clock.now() + dt.timedelta(days=days),
    )
    s.add(t)
    s.flush()
    return t, f"{PREFIX}{t.id.removeprefix('Token_')}.{secret}"


def revoke_all(s: Session, user_id: str) -> int:
    """A password changed or reset stops every token of its user (S10.9.4)."""
    from sqlalchemy import false, select

    rows = list(
        s.scalars(
            select(AccessToken).where(AccessToken.userId == user_id, AccessToken.deleted == false())
        )
    )
    for t in rows:
        t.mark_deleted(user_id)
    return len(rows)


def tell_made(s: Session, svc, user: User, t: AccessToken) -> None:
    """Making a token is emailed, as the other account-security changes are (S10.1.9)."""
    from . import settings
    from .mail import Email

    if not user.email:
        return
    svc.mailer.send(
        s,
        Email(
            user.email,
            "An access token was made",
            (
                f'Hello {user.displayName},\n\nAn access token named "{t.name}" was just made '
                f"for {user.username} on {settings.get(s, 'serverName')}. It lets an agent read "
                f"what you can see until {t.expiresAt:%b %-d, %Y}.\n\nIf you didn't make it, "
                "revoke it in Profile › Access tokens, change your password, and tell an admin.\n"
            ),
        ),
    )


def find(s: Session, raw: str) -> tuple[AccessToken, User] | None:
    """The live token this text is, and its user; None for anything else."""
    if not raw.startswith(PREFIX) or "." not in raw:
        return None
    ident, secret = raw[len(PREFIX) :].split(".", 1)
    t = s.get(AccessToken, "Token_" + ident)
    if t is None or not hmac.compare_digest(t.secretHash, _hash(secret)):
        return None
    if t.deleted or t.expiresAt <= clock.now():
        return None
    u = s.get(User, t.userId)
    if u is None or not u.active:
        return None
    return t, u


def chosen(t: AccessToken) -> dict[str, set[str]]:
    """A chosen-items token's accounts and portfolios, by kind."""
    out: dict[str, set[str]] = {k: set() for k in KINDS}
    for it in json.loads(t.items or "[]"):
        if it.get("kind") in out:
            out[it["kind"]].add(it["id"])
    return out
