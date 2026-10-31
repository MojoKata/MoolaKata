"""Users and Groups, for admins (requirements S10.1)."""

import datetime as dt

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
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


class GroupRow(Model):
    id: str
    name: str
    active: bool
    builtIn: str | None
    memberIds: list[str]
    createdAt: dt.datetime
    version: int


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
    with server(request).db.read(user=c.id) as s:
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


@router.post("/users/{user_id}/invitation", status_code=204)
def resend(user_id: str, request: Request, c: Caller = Depends(admin)):
    srv = server(request)
    with srv.db.tx(user=c.id) as s:
        accounts.resend_invitation(s, srv.services, c.user, _user(s, user_id))
    return Response(status_code=204)


@router.post("/users/{user_id}/two-step/reset", response_model=UserRow)
def reset_two_step(user_id: str, request: Request, c: Caller = Depends(admin)):
    """An admin's reset, the last resort when the app and the recovery codes are lost
    (S10.1.6): two-step is off, and the user's sessions end. An action, the password given
    again."""
    recent_auth(c)
    srv = server(request)
    with srv.db.tx(user=c.id) as s:
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
    with server(request).db.read(user=c.id) as s:
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
    with srv.db.tx(user=c.id) as s:
        _admin_change(s, c, body.groupIds)
        u = signup.approve(s, srv.services, c.user, request_id, body.groupIds)
        row = user_row(s, u)
        admins = accounts.admin_ids(s)
    srv.events.publish("signup", {}, users=admins)
    return row


@router.post("/signup-requests/{request_id}/reject", status_code=204)
def reject_signup(request_id: str, request: Request, c: Caller = Depends(admin)):
    srv = server(request)
    with srv.db.tx(user=c.id) as s:
        signup.reject(s, srv.services, c.user, request_id)
        admins = accounts.admin_ids(s)
    srv.events.publish("signup", {}, users=admins)
    return Response(status_code=204)


@router.get("/groups", response_model=list[GroupRow])
def list_groups(request: Request, c: Caller = Depends(admin)):
    with server(request).db.read(user=c.id) as s:
        groups = s.scalars(select(Group).where(Group.deleted == false()).order_by(Group.name)).all()
        return [group_row(s, g) for g in groups]


# ---------- users and groups in a dialog's draft (S12.15, S13.8.11) ----------


class UserRecord(Model):
    """A user as a draft saves them: an admin's (S10.1), invited when made, their email
    changed only while the invitation is pending; and the user's own Profile (S12.2.16),
    theirs alone, their sex and birthday their person's (S10.10.1)."""

    displayName: str
    username: str
    email: str | None = None
    sex: str | None = None
    active: bool = True
    groupIds: list[IdOf("Group")] = Field(  # type: ignore[valid-type]
        default_factory=list, json_schema_extra={"uniqueItems": True}
    )
    avatar: str | None = None
    timeZone: str = "auto"
    theme: str = "system"
    birthMonth: int | None = None
    birthDay: int | None = None
    birthYear: int | None = None
    alertEmails: str = "each"
    bitcoinUnit: str = "btc"
    shownProjectionIds: list[IdOf("Prjct")] = Field(  # type: ignore[valid-type]
        default_factory=list, json_schema_extra={"uniqueItems": True}
    )
    activeBudgetId: IdOf("Bdgt") | None = None  # type: ignore[valid-type]  # S7.12.1


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
    if record_id != ctx.caller.id:
        _admin_ctx(ctx)
    return _user(ctx.s, record_id)


def _user_current(ctx, u: User) -> dict:
    from . import profile

    return {**profile.current(ctx.s, u), "username": u.username, "email": u.email,
            "active": u.active, "groupIds": accounts.group_ids(ctx.s, u.id)}  # fmt: skip


def _user_update(ctx, u: User, body: UserRecord) -> None:
    from . import profile

    current = _user_current(ctx, u)
    sent = {f for f in UserRecord.model_fields if getattr(body, f) != current[f]}
    if "username" in sent:
        raise refuse("username", "username-fixed", "A user keeps their username.")
    if u.id == ctx.caller.id and not sent & {"email", "active", "groupIds"}:
        # Their own Profile: their name among it.
        profile.change(ctx.s, u, body, sent & set(profile.PROFILE_FIELDS))
        return
    if sent & (set(profile.PROFILE_FIELDS) - {"displayName"}):
        field = sorted(sent & set(profile.PROFILE_FIELDS))[0]
        raise refuse(field, "own-profile", "A user's profile is theirs to change.", 403)
    c, s = _admin_ctx(ctx), ctx.s
    srv = server(ctx.request)
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


def _user_read(ctx, record_id: str):
    """The user as their own Profile reads them, or as the Users screen does."""
    from . import profile

    u = ctx.s.get(User, record_id)
    return profile.profile(ctx.s, u) if u.id == ctx.caller.id else user_row(ctx.s, u)


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
        read=_user_read,
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
