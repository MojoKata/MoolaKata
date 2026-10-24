"""Activity (requirements S10.8): the changes worth showing, newest first, each naming who
made it and what it is about, to the people concerned: the owner, those an item is shared
with, and admins for users, groups and Settings. Amounts are never named (R3.8)."""

import contextlib
import datetime as dt
import json

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, or_, select

from .. import access
from ..store.entities.accounts import Account
from ..store.entities.core import Activity
from ..store.entities.sharing import Portfolio
from ..store.entities.users import Group, User
from .conventions import ExactRoute, Model, Page, Paging
from .deps import Caller, caller, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["activity"])

TEXT = {
    "signin": "{actor} signed in",
    "signout": "{actor} signed out",
    "signin.failed": "A sign-in as {subject} failed",
    "signin.locked": "{subject} was locked after too many failed sign-ins",
    "signin.recovery-code": "{actor} signed in with a two-step recovery code",
    "user.created-default-admin": "The default admin was made",
    "user.created-first-admin": "{actor} set up the first admin account",
    "user.setup": "{actor} set up the admin account",
    "user.invited": "{actor} invited {subject}",
    "user.invitation-resent": "{actor} sent {subject} a new invitation",
    "user.joined": "{actor} joined",
    "user.updated": "{actor} changed {fields} of {subject}",
    "user.deactivated": "{actor} made {subject} inactive",
    "user.reactivated": "{actor} made {subject} active again",
    "user.reactivation-asked": "{actor} asked to be made active again",
    "user.password-changed": "{actor} changed their password",
    "user.password-reset": "{actor} reset their password",
    "user.email-changed": "{actor} changed their email address",
    "signup.requested": "{name} asked for an account",
    "signup.approved": "{actor} approved {subject}'s request for an account",
    "signup.rejected": "{actor} turned down {name}'s request for an account",
    "user.two-step-on": "{actor} turned on two-step sign-in",
    "user.two-step-off": "{actor} turned off two-step sign-in",
    "user.two-step-reset": "{actor} turned off two-step sign-in for {subject}",
    "user.recovery-codes": "{actor} made new two-step recovery codes",
    "profile.updated": "{actor} changed {fields} in their profile",
    "group.created": "{actor} made the group {subject}",
    "group.updated": "{actor} changed {fields} of the group {subject}",
    "group.members": "{actor} changed the members of {subject}",
    "settings.changed": "{actor} changed {fields} in Settings",
    "prices.source-added": "{actor} added the price source {source}",
    "prices.source-changed": "{actor} changed {fields} of the price source {source}",
    "prices.source-removed": "{actor} removed the price source {source}",
    "key.made": "A master key was made on the host ({fingerprint})",
    "key.made-welcome": "The welcome made the master key ({fingerprint})",
    "key.fingerprint-shown": "The master key's fingerprint was read on the host",
    "key.unlocked": "The server was unlocked with the recovery phrase ({fingerprint})",
    "key.unlock-refused": "An unlock from the host was refused",
    "key.verified": "The master key's recovery phrase was confirmed on the host ({fingerprint})",
    "key.verify-failed": "A recovery phrase typed on the host did not match ({fingerprint})",
    "key.checked": "{actor} confirmed the recovery phrase with Verify key ({fingerprint})",
    "key.check-failed": "{actor} typed a phrase into Verify key that isn't this server's key",
    "key.rotated": "The master key was rotated on the host ({from} → {to})",
    "keys.tested": "{actor} tested key storage",
    "keys.reencrypt-scheduled": "{actor} scheduled a re-encryption for the next restart",
    "keys.reencrypt-cancelled": "{actor} cancelled the re-encryption scheduled",
    "keys.reencrypted": "The data key was replaced: the database and secrets are re-encrypted",
    "keys.copy-removed": "{actor} removed the copy {name}",
    "keys.previous-forgotten": "{actor} forgot the previous key {key}",
    "db.shell": "The database was opened for maintenance on the host",
    "db.backup": "A backup was made on the host ({name})",
    "db.verify-backup": "A backup was checked on the host ({name})",
    "db.restore": "A backup was restored on the host ({name})",
    "db.restore-checked": "After the restore: {receipts} receipts and {secrets} secrets don't open",
    "connector.confirmed": "{actor} confirmed the connector's pairing",
    "connector.address-changed": "The connector reports from a new address ({from} → {to})",
    "connector.address-accepted": "{actor} accepted the connector's new address ({to})",
    "signin.new-address": "{actor} signed in from an address not used in the last 30 days",
    "files.orphans-removed": "{actor} removed {files} files no record names",
    "backups.started": "{actor} started a backup",
    "files.pruned": "{actor} pruned {files} expired files",
    "account.created": "{actor} made the account {subject}",
    "account.updated": "{actor} changed {fields} of {subject}",
    "account.closed": "{actor} closed {subject}",
    "account.reopened": "{actor} reopened {subject}",
    "account.deleted": "{actor} deleted {subject}",
    "account.imported": "{actor} imported {added_txns} into {subject}",
    "account.balance-typed": "{actor} typed a balance for {subject}",
    "account.balance-adjusted": "{actor} adjusted the balance of {subject}",
    "account.reconciled": "{actor} reconciled {subject} with a statement",
    "transaction.updated": "{actor} changed {fields} of a transaction in {subject}",
    "transaction.deleted": "{actor} deleted a transaction in {subject}",
    "transaction.categorised": "{actor} changed the category of {count_txns} in {subject}",
    "account.corporate-action": "{actor} recorded a {name} in {subject}",
    "rule.created": "{actor} added a categorisation rule",
    "rule.updated": "{actor} changed a categorisation rule",
    "rule.moved": "{actor} reordered their categorisation rules",
    "rule.deleted": "{actor} deleted a categorisation rule",
    "rules.applied": "{actor}'s rules set {count_txns}",
    "portfolio.created": "{actor} made the portfolio {subject}",
    "portfolio.updated": "{actor} changed {fields} of the portfolio {subject}",
    "portfolio.deleted": "{actor} deleted the portfolio {subject}",
    "receipts.reread": "{actor} asked for every receipt to be read again",
    "receipt.uploaded": "{actor} uploaded a receipt",
    "receipt.attached": "{actor} attached a receipt to a transaction in {subject}",
    "receipt.deleted": "{actor} deleted a receipt",
    "loan.payment": "{actor} recorded a payment on {subject}",
    "loan.plan-saved": "{actor} saved a payoff plan for {subject}",
    "gift.saved": "{actor} saved a gift",
    "gift.purchase-linked": "{actor} linked a purchase in {subject} to a gift",
    "person.share-asked": "{actor} asked for a private person to be shared",
    "person.joined": "{actor} joined a linked server's user to a person here",
    "relationship.saved": "{actor} saved a relationship",
    "relationship.confirmed": "{actor} confirmed a marriage",
    "option.traded": "{actor} recorded an option trade in {subject}",
    "strategy.grouped": "{actor} grouped legs as a strategy in {subject}",
    "option.adjusted": "{actor} adjusted options in {subject} after a corporate action",
    "token.created": "{actor} made an access token, {name}",
    "token.revoked": "{actor} revoked the access token {name}",
    "email.opened": "{actor} opened a written email to {to}: {subject}",
    "link.invited": "{actor} made an invitation for another server",
    "link.requested": "{actor} asked to link with another server",
    "link.request-received": "Another server asked to link with this one",
    "link.approved": "{actor} approved a link with another server",
    "link.paused": "{actor} paused a link",
    "link.resumed": "{actor} resumed a link",
    "link.ended": "{actor} ended a link",
    "link.ended-by-peer": "A linked server ended its link with this one",
    "link.pulled": "{subject} sent {count} changed items{shares}",
    "link.served": "This server sent {subject} {count} changed items{shares}",
    "link.pull-asked": "{actor} asked a linked server for its changes now",
    "link.copy-key-made": "{actor} created a linked copy's access key",
    "link.copy-unlocked": "{actor} unlocked a linked copy",
    "link.viewed": "{actor} viewed what {subject} shares",
    "link.copy-unlock-failed": "{actor} gave wrong words for a linked copy",
    "link.copy-locked": "{actor} locked a linked copy ({why})",
    "link.copy-reset": "{actor} reset a linked copy",
    "link.certificate-accepted": "{actor} accepted a linked server's new certificate",
    "mcp.called": "{actor}'s access token {name} read {tool}",
    "wallet.changed": "{actor} changed the keys and addresses {subject} watches",
    "option.settled": "{actor} recorded an option's expiry, assignment or exercise in {subject}",
    "donation.recorded": "{actor} recorded a donation",
    "tax-book.created": "{actor} made a tax book",
    "529.contribution": "{actor} recorded a contribution to {subject}",
    "item.added": "{actor} added an item to {subject}",
    "item.changed": "{actor} changed an item in {subject}",
    "item.deleted": "{actor} deleted an item from {subject}",
    "item.sold": "{actor} recorded the sale of an item in {subject}",
    "projection.created": "{actor} made the projection {subject}",
    "projection.updated": "{actor} changed {fields} of the projection {subject}",
    "projection.activated": "{actor} made {subject} the active plan",
    "projection.deleted": "{actor} deleted the projection {subject}",
    "profile.assumptions": "{actor} changed their assumptions for projections",
    "settings.tax-tables": "{actor} corrected {fields} in the tax tables",
    "budget.created": "{actor} made the budget {subject}",
    "budget.updated": "{actor} changed {fields} of the budget {subject}",
    "budget.planned": "{actor} changed the plan of the budget {subject}",
    "budget.deleted": "{actor} deleted the budget {subject}",
    "budget.activated": "{actor} made {subject} the budget they follow",
    "budget.moved": "{actor} moved money between categories in the budget {subject}",
    "budget.move-deleted": "{actor} deleted a move in the budget {subject}",
    "budget.left-out": "{actor} left a transaction out of the budget {subject}",
    "budget.counted-again": "{actor} counted a transaction in the budget {subject} again",
    "budget.landed": "{actor} said where money landed in the budget {subject}'s savings goes",
    "reimbursement.paired": "{actor} paired a payback with reimbursable spending in {subject}",
    "reimbursement.unpaired": "{actor} unpaired a payback in {subject}",
    "share.given": "{actor} shared {subject} with {grantee} ({level})",
    "share.changed": "{actor} changed {grantee}'s access to {subject} ({level})",
    "share.removed": "{actor} stopped sharing {subject} with {grantee}",
}
FIELD_NAMES = {
    "displayName": "the name",
    "reimbursable": "what is to be paid back",
    "owedBy": "who pays it back",
    "categoryId": "the category",
    "category": "the category",
    "amount": "the amount",
    "date": "the date",
    "payee": "the payee",
    "memo": "the memo",
    "timeZone": "the time zone",
    "lotMethod": "the lot method",
    "keptBy": "how it is kept current",
    "apiKey": "the key",
    "enabled": "on or off",
    "preference": "the order",
    "name": "the name",
    "active": "the active switch",
}


class ActivityItem(Model):
    id: str
    at: dt.datetime
    kind: str
    actorId: str | None
    actorName: str | None
    actorAvatar: str | None
    via: str | None
    subjectKind: str | None
    subjectId: str | None
    text: str


class Newer(Model):
    count: int


def _fields(detail: dict) -> str:
    names = [FIELD_NAMES.get(f, f) for f in detail.get("fields", [])]
    if not names:
        return "details"
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _txns(n: int, adjective: str = "") -> str:
    return f"{n} {adjective}transaction" + ("" if n == 1 else "s")


def render(a: Activity, names: dict[tuple[str, str], str]) -> str:
    detail = json.loads(a.detail or "{}")
    actor = names.get(("user", a.actorId or ""), "MoolaKata" if a.via != "host" else "The host")
    subject = names.get((a.subjectKind or "", a.subjectId or ""), "something")
    grantee = names.get((detail.get("granteeKind", ""), detail.get("granteeId", "")), "someone")
    values = {
        "actor": actor,
        "subject": subject,
        "grantee": grantee,
        "fields": _fields(detail),
        "count": detail.get("count", 1),
        "added": detail.get("added", 0),
        "level": detail.get("level", ""),
        "count_txns": _txns(detail.get("count", 1)),
        "added_txns": _txns(detail.get("added", 0), "new "),
        "source": detail.get("source", ""),
        "fingerprint": detail.get("fingerprint", ""),
        "from": detail.get("from", ""),
        "to": detail.get("to", ""),
        "name": detail.get("name", ""),
        "tool": detail.get("tool", "").replace("_", " "),
        "why": detail.get("why", ""),
        "files": f"{detail.get('files', 0):,}",
        "shares": (": " + "; ".join(detail["shares"])) if detail.get("shares") else "",
    }
    template = TEXT.get(a.kind, "{actor}: " + a.kind)
    return template.format(**values)


def _visible(s, c: Caller):
    """Entries the caller may see (S10.8): their own, about them, about whatever is shared with
    them, the one that says a share with them was removed, and for admins, about users,
    groups, Settings and keys."""
    from ..taxes import books

    accounts = [a.id for a, _ in access.visible_accounts(s, c.id)]
    portfolios = [p.id for p, _ in access.visible_portfolios(s, c.id)]
    shared: dict[str, set[str]] = {}
    for kind, item in access.reach(s, c.id).levels:
        shared.setdefault(kind, set()).add(item)
    shared.setdefault("tax-book", set()).update(b.id for b, _ in books.visible(s, c.id))
    groups = access.groups_of(s, c.id)
    grantee = func.json_extract(Activity.detail, "$.granteeId")
    conds = [
        Activity.actorId == c.id,
        Activity.ownerId == c.id,
        and_(Activity.subjectKind == "account", Activity.subjectId.in_(accounts)),
        and_(Activity.subjectKind == "portfolio", Activity.subjectId.in_(portfolios)),
        and_(
            Activity.subjectKind == "budget",
            Activity.subjectId.in_([b.id for b, _ in access.visible_budgets(s, c.id)]),
        ),
        *(
            and_(Activity.subjectKind == kind, Activity.subjectId.in_(sorted(items)))
            for kind, items in shared.items()
            if kind not in ("account", "portfolio", "budget")
        ),
        and_(
            Activity.kind == "share.removed",
            or_(grantee == c.id, grantee.in_(groups)),
        ),
    ]
    if c.admin:
        conds.append(
            and_(
                Activity.forAdmins,
                or_(
                    Activity.subjectKind.is_(None),
                    Activity.subjectKind.in_(("user", "group", "link")),
                ),
            )
        )
    return or_(*conds)


@router.get("/activity", response_model=Page[ActivityItem])
def list_activity(
    request: Request,
    c: Caller = Depends(caller),
    paging: Paging = Depends(),
    account: str | None = None,
    person: str | None = None,
):
    with server(request).db.read() as s:
        q = select(Activity).where(_visible(s, c))
        if account:
            q = q.where(Activity.subjectKind == "account", Activity.subjectId == account)
        if person:
            q = q.where(Activity.actorId == person)
        page, total = paging.query(s, q.order_by(Activity.at.desc(), Activity.id.desc()))
        names = _names(s, page)
        users = {u.id: u for u in s.scalars(select(User))}
        return paging.wrap(
            [
                ActivityItem(
                    id=a.id,
                    at=a.at,
                    kind=a.kind,
                    actorId=a.actorId,
                    actorName=users[a.actorId].displayName if a.actorId in users else None,
                    actorAvatar=users[a.actorId].avatar if a.actorId in users else None,
                    via=a.via,
                    subjectKind=a.subjectKind,
                    subjectId=a.subjectId,
                    text=render(a, names),
                )
                for a in page
            ],
            total,
        )


@router.get("/activity/newer", response_model=Newer)
def newer(request: Request, c: Caller = Depends(caller), since: str = Query(...)):
    """How many entries arrived after one the page shows: the +N new pill (S12.1.3)."""
    with server(request).db.read() as s:
        first = s.get(Activity, since)
        if first is None:
            return Newer(count=0)
        q = select(Activity.id).where(
            _visible(s, c),
            or_(Activity.at > first.at, and_(Activity.at == first.at, Activity.id > first.id)),
        )
        return Newer(count=len(s.scalars(q).all()))


def _names(s, rows: list[Activity]) -> dict[tuple[str, str], str]:
    names: dict[tuple[str, str], str] = {}
    for u in s.scalars(select(User)):
        names[("user", u.id)] = u.displayName
    for g in s.scalars(select(Group)):
        names[("group", g.id)] = g.name
    acct_ids = {a.subjectId for a in rows if a.subjectKind == "account"}
    for a in s.scalars(select(Account).where(Account.id.in_(acct_ids))):
        names[("account", a.id)] = a.name
    port_ids = {a.subjectId for a in rows if a.subjectKind == "portfolio"}
    for p in s.scalars(select(Portfolio).where(Portfolio.id.in_(port_ids))):
        names[("portfolio", p.id)] = p.name
    from ..store.entities.budgets import Budget
    from ..store.entities.projections import Projection

    proj_ids = {a.subjectId for a in rows if a.subjectKind == "projection"}
    for p in s.scalars(select(Projection).where(Projection.id.in_(proj_ids))):
        names[("projection", p.id)] = p.name
    budget_ids = {a.subjectId for a in rows if a.subjectKind == "budget"}
    for b in s.scalars(select(Budget).where(Budget.id.in_(budget_ids))):
        names[("budget", b.id)] = b.name
    from ..store.entities.links import Link

    link_ids = {a.subjectId for a in rows if a.subjectKind == "link"}
    for k in s.scalars(select(Link).where(Link.id.in_(link_ids))):
        names[("link", k.id)] = k.householdName or k.peerName or "a linked household"
    # The other kinds that are shared (S10.3), named as the Share dialog names them.
    from .. import sharing
    from ..errors import Problem

    for a in rows:
        key = (a.subjectKind or "", a.subjectId or "")
        if key[0] in ("person", "gift-plan", "giving-plan", "tax-book") and key not in names:
            with contextlib.suppress(Problem):  # deleted since: "something"
                obj = sharing.item(s, key[0], key[1])
                names[key] = (
                    sharing.name_of(s, key[0], obj)
                    if hasattr(obj, "name") or key[0] == "gift-plan"
                    else f"the {key[0].replace('-', ' ')} for {obj.year}"
                )
    return names
