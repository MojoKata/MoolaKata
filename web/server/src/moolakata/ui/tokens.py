"""Profile › Access tokens (requirements S10.9.1): a user's own tokens for the MCP endpoint,
made with a name, what they can read and an expiry, shown once, and revoked."""

import datetime as dt
import json

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import false, select

from .. import access, activity, clock, tokens
from ..errors import FieldError, Problem, refuse
from ..store.entities.users import AccessToken, User
from . import save
from .conventions import ExactRoute, Model
from .deps import Caller, caller, recent_auth, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["tokens"])


class TokenItem(Model):
    kind: str  # account or portfolio
    id: str


class TokenItemOut(TokenItem):
    name: str


class TokenOut(Model):
    id: str
    name: str
    scope: str  # all or chosen
    items: list[TokenItemOut]
    createdAt: dt.datetime
    expiresAt: dt.datetime
    lastUsedAt: dt.datetime | None
    expired: bool
    version: int


class NewToken(Model):
    name: str
    scope: str = "all"
    items: list[TokenItem] = Field(default_factory=list)
    days: int = 90


class TokenMade(Model):
    token: TokenOut
    secret: str  # shown once


def _names(s, user_id: str) -> dict[tuple[str, str], str]:
    out = {("account", a.id): a.name for a, _ in access.visible_accounts(s, user_id)}
    out |= {("portfolio", p.id): p.name for p, _ in access.visible_portfolios(s, user_id)}
    return out


def _out(t: AccessToken, names: dict) -> TokenOut:
    items = [
        TokenItemOut(kind=i["kind"], id=i["id"], name=names.get((i["kind"], i["id"]), "—"))
        for i in json.loads(t.items or "[]")
    ]
    return TokenOut(
        id=t.id,
        name=t.name,
        scope=t.scope,
        items=items,
        createdAt=t.createdAt,
        expiresAt=t.expiresAt,
        lastUsedAt=t.lastUsedAt,
        expired=t.expiresAt <= clock.now(),
        version=t.version,
    )


@router.get("/profile/tokens", response_model=list[TokenOut])
def list_tokens(request: Request, c: Caller = Depends(caller)):
    with server(request).db.read() as s:
        names = _names(s, c.id)
        rows = s.scalars(
            select(AccessToken)
            .where(AccessToken.userId == c.id, AccessToken.deleted == false())
            .order_by(AccessToken.createdAt.desc())
        )
        return [_out(t, names) for t in rows]


def _made(s, c: Caller, body: NewToken, token_id: str | None = None) -> TokenMade:
    """A token for its maker, the password given again (S13.7.2); its secret shown once."""
    recent_auth(c)
    e: list[FieldError] = []
    name = body.name.strip()
    if not 1 <= len(name) <= 60:
        e.append(FieldError("name", "name-invalid", "A name to tell it apart: up to 60 letters."))
    if body.scope not in ("all", "chosen"):
        e.append(FieldError("scope", "scope-invalid", "Everything you can see, or chosen items."))
    if body.days not in tokens.DAYS:
        e.append(FieldError("days", "days-invalid", "30 days, 90 days or a year."))
    if body.scope == "chosen" and not body.items:
        e.append(FieldError("items", "items-missing", "Choose at least one account or portfolio."))
    if e:
        raise Problem(422, e[0].code, e[0].message, e)
    names = _names(s, c.id)
    items = []
    for i in body.items if body.scope == "chosen" else []:
        if (i.kind, i.id) not in names:
            raise refuse("items", "not-found", "Only accounts and portfolios you can see.")
        items.append({"kind": i.kind, "id": i.id})
    t, secret = tokens.make(s, c.id, name, body.scope, items, body.days, token_id)
    activity.record(s, "token.created", actor=c.id, owner=c.id, detail={"name": name})
    return TokenMade(token=_out(t, names), secret=secret)


# ---------- a token in a dialog's draft (S12.15, S13.8.11) ----------


class TokenRecord(NewToken):
    """A token as a draft makes it (S10.9): made once, its secret in the save's answer alone;
    never changed; revoked by deleting it."""


def _token_create(ctx, record_id: str, body: TokenRecord) -> None:
    made = _made(ctx.s, ctx.caller, body, record_id)
    ctx.notes[record_id] = made.secret
    srv, user_id = server(ctx.request), ctx.caller.id

    def tell() -> None:
        with srv.db.tx() as s:
            tokens.tell_made(s, srv.services, s.get(User, user_id), s.get(AccessToken, record_id))

    ctx.after(f"token.made:{record_id}", tell)


def _token_editable(ctx, record_id: str) -> AccessToken:
    t = ctx.s.get(AccessToken, record_id)
    if t is None or t.deleted or t.userId != ctx.caller.id:
        raise Problem(404, "not-found", "No such token.")
    return t


def _token_update(ctx, t: AccessToken, body: TokenRecord) -> None:
    raise refuse(None, "token-fixed", "A token isn't changed: revoke it and make another.")


def _token_delete(ctx, t: AccessToken) -> None:
    t.mark_deleted(ctx.caller.id)
    activity.record(ctx.s, "token.revoked", actor=ctx.caller.id, owner=ctx.caller.id,
                    detail={"name": t.name})  # fmt: skip


def _token_read(ctx, record_id: str) -> dict:
    """The token as read; on the save that made it, with its secret, shown once."""
    out = _out(ctx.s.get(AccessToken, record_id), _names(ctx.s, ctx.caller.id))
    secret = ctx.notes.get(record_id)
    return {**out.model_dump(), "secret": secret} if secret else out.model_dump()


save.register(
    save.Kind(
        prefix="Token",
        entity=AccessToken,
        fields=TokenRecord,
        create=_token_create,
        editable=_token_editable,
        current=lambda ctx, t: {
            "name": t.name,
            "scope": t.scope,
            "items": json.loads(t.items or "[]"),
            "days": 90,
        },
        update=_token_update,
        delete=_token_delete,
        read=_token_read,
    )
)
