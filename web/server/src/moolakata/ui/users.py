"""Users and Groups, for admins (requirements S10.1)."""

import datetime as dt

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field
from sqlalchemy import false, select

from .. import clock
from ..auth import signup, twostep
from ..auth import users as accounts
from ..errors import Problem, refuse
from ..store.entities.users import Group, User
from . import save
from .conventions import ExactRoute, IdOf, Model
from .deps import Caller, admin, recent_auth, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["users"])


class UserRow(Model):
    id: str
    username: str
    displayName: str
    email: str | None
    avatar: str | None
    active: bool
    admin: bool
    invited: bool
    twoStep: bool
    groupIds: list[str]
    lastSignInAt: dt.datetime | None
    reactivationAskedAt: dt.datetime | None
    createdAt: dt.datetime
    version: int


class NewUser(Model):
    displayName: str
    username: str
    email: str
    sex: str | None = None  # their person's (S10.10.1); required
    groupIds: list[str] = Field(default_factory=list)


class UserChange(Model):
    displayName: str | None = None
    email: str | None = None
    active: bool | None = None
    groupIds: list[str] | None = None


class GroupRow(Model):
    id: str
    name: str
    active: bool
    builtIn: str | None
    memberIds: list[str]
    createdAt: dt.datetime
    version: int


class NewGroup(Model):
    name: str
    memberIds: list[str] = Field(default_factory=list)


class GroupChange(Model):
    name: str | None = None
    active: bool | None = None
    memberIds: list[str] | None = None


def user_row(s, u: User) -> UserRow:
    return UserRow(
        id=u.id,
        username=u.username,
        displayName=u.displayName,
        email=u.email,
        avatar=u.avatar,
        active=u.active,
        admin=accounts.is_admin(s, u.id),
        invited=u.passwordHash is None and not u.needsSetup,
        twoStep=twostep.is_on(u),
        groupIds=accounts.group_ids(s, u.id),
        lastSignInAt=u.lastSignInAt,
        reactivationAskedAt=u.reactivationAskedAt,
        createdAt=u.createdAt,
        version=u.version,
    )


def group_row(s, g: Group) -> GroupRow:
    return GroupRow(
        id=g.id,
        name=g.name,
        active=g.active,
        builtIn=g.builtIn,
        memberIds=accounts.members(s, g.id),
        createdAt=g.createdAt,
        version=g.version,
    )


def _user(s, user_id: str) -> User:
    u = s.get(User, user_id)
    if u is None or u.deleted or u.linkId is not None:
        raise Problem(404, "not-found", "Not found")
    return u


def _group(s, group_id: str) -> Group:
    g = s.get(Group, group_id)
    if g is None or g.deleted:
        raise Problem(404, "not-found", "Not found")
    return g


@router.get("/users", response_model=list[UserRow])
def list_users(request: Request, c: Caller = Depends(admin)):
    with server(request).db.read() as s:
        users = s.scalars(
            select(User)
            .where(User.deleted == false(), User.linkId.is_(None))
            .order_by(User.displayName)
        ).all()
        return [user_row(s, u) for u in users]


def _admin_change(s, c: Caller, wanted: list[str] | None, user_id: str | None = None) -> None:
    """Making someone an admin, or no longer one, needs the password again (S13.7.2)."""
    if wanted is None:
        return
    admins = accounts.admins_group(s).id
    now = bool(user_id) and admins in accounts.group_ids(s, user_id)
    if (admins in wanted) != now:
        recent_auth(c)


@router.post("/users", response_model=UserRow, status_code=201)
def create_user(body: NewUser, request: Request, c: Caller = Depends(admin)):
    srv = server(request)
    with srv.db.tx() as s:
        _admin_change(s, c, body.groupIds)
        u = accounts.invite(
            s,
            srv.services,
            c.user,
            body.displayName,
            body.username,
            body.email,
            body.groupIds,
            body.sex,
        )
        row = user_row(s, u)
    # No route reads one by its id: the middleware's Location is the list (S13.8.4).
    return JSONResponse(row.model_dump(mode="json"), status_code=201)


@router.post("/users/{user_id}/invitation", status_code=204)
def resend(user_id: str, request: Request, c: Caller = Depends(admin)):
    srv = server(request)
    with srv.db.tx() as s:
        accounts.resend_invitation(s, srv.services, c.user, _user(s, user_id))
    return Response(status_code=204)


@router.post("/users/{user_id}/two-step/reset", response_model=UserRow)
def reset_two_step(user_id: str, request: Request, c: Caller = Depends(admin)):
    """An admin's reset, the last resort when the app and the recovery codes are lost
    (S10.1.6): two-step is off, and the user's sessions end. An action, the password given
    again."""
    recent_auth(c)
    srv = server(request)
    with srv.db.tx() as s:
        u = _user(s, user_id)
        twostep.turn_off(s, srv.services, u, c.user)
        u.updatedAt = clock.now()
        s.flush()
        out = user_row(s, u)
    if u.id != c.id:
        srv.events.end_user(u.id, "signed-out")
    return out


class SignupRow(Model):
    id: str
    displayName: str
    username: str
    email: str
    confirmedAt: dt.datetime | None


class Approval(Model):
    groupIds: list[str] = Field(default_factory=list)


@router.get("/signup-requests", response_model=list[SignupRow])
def signup_requests(request: Request, c: Caller = Depends(admin)):
    """Requests whose email is confirmed, waiting for an admin (S10.1.4)."""
    with server(request).db.read() as s:
        return [
            SignupRow(
                id=r.id,
                displayName=r.displayName,
                username=r.username,
                email=r.email,
                confirmedAt=r.confirmedAt,
            )
            for r in signup.waiting(s)
        ]


@router.post("/signup-requests/{request_id}/approve", response_model=UserRow)
def approve_signup(request_id: str, body: Approval, request: Request, c: Caller = Depends(admin)):
    srv = server(request)
    with srv.db.tx() as s:
        _admin_change(s, c, body.groupIds)
        u = signup.approve(s, srv.services, c.user, request_id, body.groupIds)
        row = user_row(s, u)
        admins = accounts.admin_ids(s)
    srv.events.publish("signup", {}, users=admins)
    return row


@router.post("/signup-requests/{request_id}/reject", status_code=204)
def reject_signup(request_id: str, request: Request, c: Caller = Depends(admin)):
    srv = server(request)
    with srv.db.tx() as s:
        signup.reject(s, srv.services, c.user, request_id)
        admins = accounts.admin_ids(s)
    srv.events.publish("signup", {}, users=admins)
    return Response(status_code=204)


@router.get("/groups", response_model=list[GroupRow])
def list_groups(request: Request, c: Caller = Depends(admin)):
    with server(request).db.read() as s:
        groups = s.scalars(select(Group).where(Group.deleted == false()).order_by(Group.name)).all()
        return [group_row(s, g) for g in groups]


@router.post("/groups", response_model=GroupRow, status_code=201)
def create_group(body: NewGroup, request: Request, c: Caller = Depends(admin)):
    with server(request).db.tx() as s:
        g = accounts.create_group(s, c.user, body.name, body.memberIds)
        row = group_row(s, g)
    # No route reads one by its id: the middleware's Location is the list (S13.8.4).
    return JSONResponse(row.model_dump(mode="json"), status_code=201)


# ---------- users and groups in a dialog's draft (S12.15, S13.8.11) ----------


class UserRecord(Model):
    """A user as an admin's draft saves them (S10.1): invited when made; their email changes
    only while the invitation is pending."""

    displayName: str
    username: str
    email: str
    sex: str | None = None  # their person's, when they are made (S10.10.1)
    active: bool = True
    groupIds: list[IdOf("Group")] = Field(  # type: ignore[valid-type]
        default_factory=list, json_schema_extra={"uniqueItems": True}
    )


class GroupRecord(Model):
    """A group as an admin's draft saves it (S10.2): the built-in admins keep their name."""

    name: str
    active: bool = True
    memberIds: list[IdOf("User")] = Field(  # type: ignore[valid-type]
        default_factory=list, json_schema_extra={"uniqueItems": True}
    )


def _admin_ctx(ctx) -> Caller:
    if not ctx.caller.admin:
        raise Problem(403, "admins-only", "Only admins can do this.")
    return ctx.caller


def _user_create(ctx, record_id: str, body: UserRecord) -> None:
    c = _admin_ctx(ctx)
    srv = server(ctx.request)
    _admin_change(ctx.s, c, body.groupIds)
    accounts.invite(ctx.s, srv.services, c.user, body.displayName, body.username, body.email,
                    body.groupIds, body.sex, user_id=record_id)  # fmt: skip


def _user_editable(ctx, record_id: str) -> User:
    _admin_ctx(ctx)
    return _user(ctx.s, record_id)


def _user_current(ctx, u: User) -> dict:
    return {"displayName": u.displayName, "username": u.username, "email": u.email,
            "sex": None, "active": u.active,
            "groupIds": accounts.group_ids(ctx.s, u.id)}  # fmt: skip


def _user_update(ctx, u: User, body: UserRecord) -> None:
    c, s = _admin_ctx(ctx), ctx.s
    srv = server(ctx.request)
    current = _user_current(ctx, u)
    if body.username != current["username"]:
        raise refuse("username", "username-fixed", "A user keeps their username.")
    groups = body.groupIds if set(body.groupIds) != set(current["groupIds"]) else None
    _admin_change(s, c, groups, u.id)
    email = body.email if body.email != current["email"] else None
    name = body.displayName if body.displayName != current["displayName"] else None
    accounts.update_user(s, c.user, u, name, email)
    if groups is not None:
        accounts.set_user_groups(s, c.user, u, groups)
    ended = body.active != current["active"] and accounts.set_active(
        s, srv.services, c.user, u, body.active
    )
    if ended:
        # Switched off: their sessions end now, and their pages are told (S10.1.5).
        ctx.after(f"user.ended:{u.id}", lambda: srv.events.end_user(u.id, "disabled"))


def _user_delete(ctx, u: User) -> None:
    raise refuse(None, "user-delete", "A user stays; make them inactive.")


def _group_create(ctx, record_id: str, body: GroupRecord) -> None:
    c = _admin_ctx(ctx)
    g = accounts.create_group(ctx.s, c.user, body.name, body.memberIds, group_id=record_id)
    if not body.active:
        accounts.update_group(ctx.s, c.user, g, None, False, None)


def _group_editable(ctx, record_id: str) -> Group:
    _admin_ctx(ctx)
    return _group(ctx.s, record_id)


def _group_update(ctx, g: Group, body: GroupRecord) -> None:
    c = _admin_ctx(ctx)
    have = accounts.members(ctx.s, g.id)
    members = body.memberIds if set(body.memberIds) != set(have) else None
    if g.builtIn == "admins" and members is not None:
        # Making or unmaking an admin: the password again (S13.7.2).
        recent_auth(c)
    if g.builtIn and (body.name != g.name or body.active != g.active):
        raise refuse("name", "group-built-in", "The admins keep their name and stay active.")
    name = body.name if body.name != g.name else None
    active = body.active if body.active != g.active else None
    accounts.update_group(ctx.s, c.user, g, name, active, members)


def _group_delete(ctx, g: Group) -> None:
    raise refuse(None, "group-delete", "A group stays; make it inactive.")


save.register(
    save.Kind(
        prefix="User",
        entity=User,
        fields=UserRecord,
        create=_user_create,
        editable=_user_editable,
        current=_user_current,
        update=_user_update,
        delete=_user_delete,
        read=lambda ctx, record_id: user_row(ctx.s, ctx.s.get(User, record_id)),
    )
)
save.register(
    save.Kind(
        prefix="Group",
        entity=Group,
        fields=GroupRecord,
        create=_group_create,
        editable=_group_editable,
        current=lambda ctx, g: {
            "name": g.name,
            "active": g.active,
            "memberIds": accounts.members(ctx.s, g.id),
        },
        update=_group_update,
        delete=_group_delete,
        read=lambda ctx, record_id: group_row(ctx.s, ctx.s.get(Group, record_id)),
    )
)
