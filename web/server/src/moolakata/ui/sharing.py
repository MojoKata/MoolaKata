"""The Share dialog and a receiver's Count in my totals (requirements S10.4–S10.7)."""

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import create_model
from sqlalchemy import false, select

from .. import access, activity, clock, sharing
from ..errors import Problem, refuse
from ..store import scoping
from ..store.entities.sharing import SHARE_ENTITIES, CountedAccount, ItemShare
from ..store.entities.users import Group, User, UserGroup
from ..store.rows import by_key
from ..store.tables.shares import SHARES
from . import save
from .conventions import ExactRoute, IdOf, Model
from .deps import Caller, caller, recent_auth, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["sharing"])
Kind = Literal[
    "account", "portfolio", "budget", "projection", "person", "gift-plan", "giving-plan", "tax-book"
]


Allow = Literal["read", "write"]
# What the Share dialog shows for a user or a group: no share, or what theirs allows.
Held = Literal["none", "read", "write"]


class Via(Model):
    groupId: str
    groupName: str
    allow: Allow


class UserGrant(Model):
    id: str
    displayName: str
    avatar: str | None
    allow: Held
    via: list[Via]
    # Its grant, a record of the save: none while it has none.
    shareId: str | None = None
    version: int = 0
    includeReceipts: bool = False


class GroupGrant(Model):
    id: str
    name: str
    allow: Held
    members: int
    shareId: str | None = None
    version: int = 0


class AccountName(Model):
    id: str
    name: str
    yours: bool


class LinkedPeople(Model):
    linkId: str
    serverName: str
    householdName: str | None
    includeReceipts: bool
    users: list[UserGrant]


class ShareView(Model):
    kind: str
    itemId: str
    itemName: str
    users: list[UserGrant]
    groups: list[GroupGrant]
    links: list[LinkedPeople]
    hidden: dict[str, list[str]]
    accounts: list[AccountName]


def view(s, owner: User, kind: str, item_id: str) -> ShareView:
    obj = sharing.item(s, kind, item_id)
    current = sharing.grants(s, kind, item_id)
    direct = {g.userId: sharing.allow_of(g) for g in current if g.userId}
    by_group = {g.groupId: sharing.allow_of(g) for g in current if g.groupId}
    rows = {g.userId or g.groupId: g for g in current}

    def grant(key: str) -> dict:
        g = rows.get(key)
        return (
            {
                "shareId": g.id,
                "version": g.version,
                **({"includeReceipts": g.includeReceipts} if g.userId else {}),
            }
            if g
            else {}
        )

    groups = s.scalars(
        select(Group).where(Group.deleted == false(), Group.active).order_by(Group.name)
    ).all()
    members: dict[str, list[str]] = {}
    for m in s.scalars(select(UserGroup).where(UserGroup.deleted == false())):
        members.setdefault(m.groupId, []).append(m.userId)
    users = s.scalars(
        select(User)
        .where(User.deleted == false(), User.active, User.id != owner.id, User.linkId.is_(None))
        .order_by(User.displayName)
    ).all()
    out_users = []
    for u in users:
        via = [
            Via(groupId=g.id, groupName=g.name, allow=by_group[g.id])
            for g in groups
            if g.id in by_group and u.id in members.get(g.id, [])
        ]
        out_users.append(
            UserGrant(
                id=u.id,
                displayName=u.displayName,
                avatar=u.avatar,
                allow=direct.get(u.id, "none"),
                via=via,
                **grant(u.id),
            )
        )
    hidden: dict[str, list[str]] = {}
    accounts: list[AccountName] = []
    if kind == "portfolio":
        people = [u for u in access.holders_of(s, access.entity_of(kind), item_id) if u != owner.id]
        hidden = sharing.hidden_accounts(s, obj, people)
        accounts = [
            AccountName(id=a.id, name=a.name, yours=a.ownerId == owner.id)
            for a in sharing.portfolio_accounts(s, item_id)
        ]
    return ShareView(
        kind=kind,
        itemId=item_id,
        itemName=sharing.name_of(s, kind, obj),
        links=_linked(s, current),
        users=out_users,
        groups=[
            GroupGrant(
                id=g.id,
                name=g.name,
                allow=by_group.get(g.id, "none"),
                members=len(members.get(g.id, [])),
                **grant(g.id),
            )
            for g in groups
        ],
        hidden=hidden,
        accounts=accounts,
    )


def _linked(s, current) -> list[LinkedPeople]:
    """Each live link's people (S10.4): None or Read, with Include receipts per server."""
    from ..store.entities.links import Link

    direct = {g.userId: g for g in current if g.userId}
    out = []
    for link in s.scalars(
        select(Link)
        .where(Link.deleted == false(), Link.state.in_(("active", "paused")))
        .order_by(Link.peerName)
    ):
        people = s.scalars(
            select(User)
            .where(User.linkId == link.id, User.deleted == false(), User.active)
            .order_by(User.displayName)
        ).all()
        if not people:
            continue
        out.append(
            LinkedPeople(
                linkId=link.id,
                serverName=link.peerName or "a linked server",
                householdName=link.householdName,
                includeReceipts=any(direct[u.id].includeReceipts for u in people if u.id in direct),
                users=[
                    UserGrant(
                        id=u.id,
                        displayName=u.displayName,
                        avatar=None,
                        allow=sharing.allow_of(direct[u.id]) if u.id in direct else "none",
                        via=[],
                        **(
                            {
                                "shareId": direct[u.id].id,
                                "version": direct[u.id].version,
                                "includeReceipts": direct[u.id].includeReceipts,
                            }
                            if u.id in direct
                            else {}
                        ),
                    )
                    for u in people
                ],
            )
        )
    return out


def _owner_only(s, c: Caller, kind: str, item_id: str) -> None:
    """Whoever may share the item changes its sharing: its owner; a tax book's filers; whoever
    may change a person (S10.10.2)."""
    access.need(s, access.entity_of(kind), item_id, c.id, "shareable", kind.replace("-", " "))


@router.get("/shares/{kind}/{item_id}", response_model=ShareView)
def get_shares(kind: Kind, item_id: str, request: Request, c: Caller = Depends(caller)):
    with server(request).db.read(user=c.id) as s:
        _owner_only(s, c, kind, item_id)
        return view(s, c.user, kind, item_id)


class ShareFields(Model):
    """A grant as the share dialog's draft saves it (S10.4): an item shared with one user or
    one group, at Read or Write; with a linked server's person, at Read, with Include receipts
    their images and text cross too (S11.5.1). It stays with its item and its grantee. Each
    shareable kind saves its own (`AccountShareRecord`, …), its item a `targetId` of that kind."""

    targetId: str
    userId: IdOf("User") | None = None  # type: ignore[valid-type]
    groupId: IdOf("Group") | None = None  # type: ignore[valid-type]
    allow: Allow
    includeReceipts: bool = False


def _grantee(s, c: Caller, body: ShareFields):
    """The user or group the grant is for, checked as the dialog offers them."""
    if (body.userId is None) == (body.groupId is None):
        raise refuse("userId", "grantee-missing", "A user or a group.")
    if body.userId:
        # Checked as the server: an inactive user is in no one's view but an admin's.
        u = s.execute(
            scoping.unscoped(
                select(User.id, User.deletedAt, User.linkId, User.active, User.displayName).where(
                    User.id == body.userId
                ),
                "the user a share is for",
            )
        ).first()
        if u is None or u.deletedAt is not None or u.id == c.id:
            raise refuse("userId", "user-unknown", "Choose a user.")
        if u.linkId and body.allow == "write":
            raise refuse(
                "allow",
                "read-only",
                f"{u.displayName} is on a linked server: shares there are read only.",
            )
        if u.linkId and not sharing.link_live(s, u.linkId):
            raise refuse("userId", "link-not-active", "That server's link isn't active.")
        if not u.active:
            raise refuse(
                "userId", "user-inactive", f"{u.displayName} is not active and can't be added."
            )
        return s.get(User, u.id)
    g = s.execute(
        scoping.unscoped(
            select(Group.id, Group.deletedAt, Group.active, Group.name).where(
                Group.id == body.groupId
            ),
            "the group a share is for",
        )
    ).first()
    if g is None or g.deletedAt is not None:
        raise refuse("groupId", "group-unknown", "Choose a group.")
    if not g.active:
        raise refuse("groupId", "group-inactive", f"{g.name} is not active and can't be added.")
    return s.get(Group, g.id)


def _reaches(ctx, grantee, receipts: bool) -> None:
    """More sent to a linked server: the password again (S13.7.2)."""
    if isinstance(grantee, User) and grantee.linkId:
        recent_auth(ctx.caller)


def _told(ctx, kind: str, item_id: str, grantee) -> None:
    """Who the change reaches is told once the save has committed (S12.6)."""
    users = ctx.notes.setdefault("share-told", {}).setdefault(kind, set())
    if isinstance(grantee, User):
        users.add(grantee.id)
    else:
        users |= {
            m.userId
            for m in ctx.s.scalars(
                select(UserGroup).where(
                    UserGroup.groupId == grantee.id, UserGroup.deleted == false()
                )
            )
        }
    srv = server(ctx.request)
    ctx.after(f"share:{kind}", lambda: srv.events.publish("share", {"kind": kind}, users=users))


def _given(ctx, row: ItemShare, verb: str, allow: str | None) -> None:
    obj = sharing.item(ctx.s, row.kind, row.targetId)
    gk, gid = ("user", row.userId) if row.userId else ("group", row.groupId)
    activity.record(
        ctx.s,
        f"share.{verb}",
        actor=ctx.caller.id,
        subject_kind=row.kind,
        subject_id=row.targetId,
        owner=obj.ownerId,
        detail={"granteeKind": gk, "granteeId": gid} | ({"allow": allow} if allow else {}),
    )


def _share_kind(kind: str, entity: type[ItemShare]) -> None:
    """The save kind of one shareable kind's shares (S13.8.11): its own record and table."""
    target = SHARES[kind].c.targetId.foreign_keys
    target_prefix = next(iter(target)).column.table.info["prefix"]
    name = entity.__name__
    fields = create_model(
        f"{name}Record",
        __base__=ShareFields,
        __doc__=ShareFields.__doc__,
        targetId=(IdOf(target_prefix), ...),
    )
    out = create_model(f"{name}Out", __base__=fields, id=(str, ...), version=(int, ...))

    def create(ctx, record_id: str, body) -> None:
        s, c = ctx.s, ctx.caller
        _owner_only(s, c, kind, body.targetId)
        grantee = _grantee(s, c, body)
        same = [
            g
            for g in sharing.grants(s, kind, body.targetId)
            if (g.userId or g.groupId) == (body.userId or body.groupId)
        ]
        if same:
            raise refuse(
                "userId" if body.userId else "groupId",
                "shared",
                "It is shared with them: change what it allows.",
                409,
            )
        _reaches(ctx, grantee, body.includeReceipts)
        row = entity(
            id=record_id,
            targetId=body.targetId,
            accessClassId=sharing.class_of(body.allow),
            userId=body.userId,
            groupId=body.groupId,
            createdById=c.id,
            includeReceipts=body.includeReceipts and bool(body.userId),
        )
        s.add(row)
        s.flush()
        _given(ctx, row, "given", body.allow)
        _told(ctx, kind, body.targetId, grantee)

    def editable(ctx, record_id: str) -> ItemShare:
        row = ctx.s.get(entity, record_id)
        if row is None or row.deleted:
            raise Problem(404, "not-found", "Not found")
        _owner_only(ctx.s, ctx.caller, kind, row.targetId)
        return row

    def current(ctx, row: ItemShare) -> dict:
        return {
            "targetId": row.targetId,
            "userId": row.userId,
            "groupId": row.groupId,
            "allow": sharing.allow_of(row),
            "includeReceipts": row.includeReceipts,
        }

    def update(ctx, row: ItemShare, body) -> None:
        was = current(ctx, row)
        fixed = [f for f in ("targetId", "userId", "groupId") if getattr(body, f) != was[f]]
        if fixed:
            raise refuse(fixed[0], "share-fixed", "A grant stays with its item and its grantee.")
        grantee = _grantee(ctx.s, ctx.caller, body)
        if body.includeReceipts and not row.includeReceipts:
            _reaches(ctx, grantee, True)
        row.includeReceipts = body.includeReceipts and bool(body.userId)
        if body.allow != was["allow"]:
            row.accessClassId = sharing.class_of(body.allow)
            _given(ctx, row, "changed", body.allow)
        row.updatedAt = clock.now()
        _told(ctx, kind, row.targetId, grantee)

    def delete(ctx, row: ItemShare) -> None:
        """Taken away: a receiver who no longer reaches an account loses their tags on it
        (S10.4)."""
        s = ctx.s
        before = access.holders_of(s, access.entity_of(kind), row.targetId)
        row.mark_deleted(ctx.caller.id)
        s.flush()
        after = access.holders_of(s, access.entity_of(kind), row.targetId)
        if kind == "account":
            for uid in [u for u in before if u not in after]:
                sharing.drop_annotations(s, uid, row.targetId)
        _given(ctx, row, "removed", None)
        grantee = s.get(User, row.userId) if row.userId else s.get(Group, row.groupId)
        _told(ctx, kind, row.targetId, grantee)

    save.register(
        save.Kind(
            prefix=SHARES[kind].info["prefix"],
            entity=entity,
            fields=fields,
            create=create,
            editable=editable,
            current=current,
            update=update,
            delete=delete,
            read=lambda ctx, record_id: out(
                id=record_id,
                version=ctx.s.get(entity, record_id).version,
                **current(ctx, ctx.s.get(entity, record_id)),
            ),
        )
    )


for _kind, _entity in SHARE_ENTITIES.items():
    _share_kind(_kind, _entity)


class CountedRecord(Model):
    """A receiver's Count in my totals on an account shared with them (S10.7), off until they
    tick it; their own, as its record of the save."""

    accountId: IdOf("Acct")  # type: ignore[valid-type]
    counted: bool


def _counted_create(ctx, record_id: str, body: CountedRecord) -> None:
    s, c = ctx.s, ctx.caller
    a, level = access.account(s, c.id, body.accountId)
    if level == "owner":
        raise refuse(
            None,
            "owner-counts",
            "Your own accounts count by their Count in net worth setting.",
            409,
        )
    have = by_key(s, CountedAccount, userId=c.id, accountId=a.id)
    if have is not None and not have.deleted:
        raise refuse("accountId", "counted-set", "It is set: change it.", 409)
    s.add(CountedAccount(id=record_id, userId=c.id, accountId=a.id, counted=body.counted))


def _counted_editable(ctx, record_id: str) -> CountedAccount:
    row = ctx.s.get(CountedAccount, record_id)
    if row is None or row.deleted or row.userId != ctx.caller.id:
        raise Problem(404, "not-found", "Not found")
    return row


def _counted_update(ctx, row: CountedAccount, body: CountedRecord) -> None:
    if body.accountId != row.accountId:
        raise refuse("accountId", "counted-fixed", "It stays with its account.")
    row.counted = body.counted


class CountedOut(CountedRecord):
    id: str
    version: int


save.register(
    save.Kind(
        prefix="CntAc",
        entity=CountedAccount,
        fields=CountedRecord,
        create=_counted_create,
        editable=_counted_editable,
        current=lambda ctx, row: {"accountId": row.accountId, "counted": row.counted},
        update=_counted_update,
        delete=lambda ctx, row: row.mark_deleted(ctx.caller.id),
        read=lambda ctx, record_id: CountedOut(
            id=record_id,
            version=ctx.s.get(CountedAccount, record_id).version,
            accountId=ctx.s.get(CountedAccount, record_id).accountId,
            counted=ctx.s.get(CountedAccount, record_id).counted,
        ),
    )
)


def counted_for(s, user_id: str) -> set[str]:
    return set(
        s.scalars(
            select(CountedAccount.accountId).where(
                CountedAccount.userId == user_id,
                CountedAccount.counted,
                CountedAccount.deleted == false(),
            )
        )
    )
