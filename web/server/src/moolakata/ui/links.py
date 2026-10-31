"""Settings › Linked servers (requirements S11.1, S11.7): invite a server or join one with its
code, approve a request, pause, resume or end a link, and see each link's users."""

import contextlib
import datetime as dt
import json

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import false, select

from .. import activity, clock, settings
from ..errors import Problem, refuse
from ..links import keys, manage
from ..links.client import LinkError
from ..store.entities.links import Link
from ..store.entities.users import User
from .conventions import ExactRoute, Model
from .deps import Caller, admin, server
from .imports import JobOut, accepted
from .prices import apply_egress

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["links"])


class RemoteUser(Model):
    id: str
    username: str
    displayName: str
    email: str | None


class CopyOut(Model):
    """The link's copy (S11.7): its access key, size, and whether it is unlocked."""

    keyMadeAt: dt.datetime | None
    keyMadeBy: str | None
    sizeBytes: int
    receipts: int
    items: int
    waiting: int  # changes pulled while it was locked
    unlocked: bool
    unlockedBy: str | None
    unlockedAt: dt.datetime | None
    locksInSeconds: int | None


class Incoming(Model):
    """A share crossing the link, either way, as an admin here sees it (S11.3, S11.7): its
    kind, owner, date and who it names, never its name or figures."""

    kind: str
    ownerName: str
    sharedAt: dt.datetime
    names: list[str]
    includeReceipts: bool


class LinkOut(Model):
    id: str
    state: str  # invited, requested, pending, active, paused, ended
    role: str  # inviter or joiner
    peerName: str | None
    householdName: str | None
    householdAvatar: dict | None
    address: str | None
    fingerprint: str | None  # four groups of four, to compare
    peerVersion: str | None
    codeExpiresAt: dt.datetime | None
    lastOkAt: dt.datetime | None
    lastError: str | None
    failingSince: dt.datetime | None
    createdAt: dt.datetime
    endedAt: dt.datetime | None
    pausedUntil: dt.datetime | None  # a pause resumes on its own then (S11.7.2)
    syncThrough: dt.date | None  # a large change arriving: the newest record so far
    syncBytes: int | None  # and what has arrived
    syncTotal: int | None  # of what the source said it would send
    users: list[RemoteUser]
    # The peer's own TLS certificate (S11.1.3), pinned by its key: four groups of four; None
    # for a public certificate. One it presented unannounced waits to be accepted, shown whole
    # for the admins to compare.
    certificate: str | None = None
    certificateOffered: str | None = None
    # The peer answered that it has no link with this one (S11.6).
    brokenAt: dt.datetime | None = None
    linkedCopy: CopyOut | None = None
    incoming: list[Incoming] = Field(default_factory=list)
    outgoing: list[Incoming] = Field(default_factory=list)  # what this server sends (S11.7)


class LinksView(Model):
    fingerprint: str  # this server's
    address: str | None  # this server's link address, as peers reach it
    # This server's own TLS certificate's key, whole, for its admin to read out to a peer's
    # (link-protocol.md §4.5); None when the certificate is a public one.
    certificate: str | None = None
    links: list[LinkOut]


class Invitation(Model):
    code: str  # shown once
    link: LinkOut


class JoinIn(Model):
    code: str


def _copy(s, srv, link: Link) -> CopyOut | None:
    if link.state not in ("active", "paused"):
        return None
    from sqlalchemy import func

    from ..links import copies
    from ..links.changes import waiting
    from ..store.entities.links import LinkedItem

    size, receipts = copies.size(srv, link.id)
    o = srv.copies.get(link.id, for_person=False)
    by = s.get(User, link.copyKeyById) if link.copyKeyById else None
    who = s.get(User, o.by) if o else None
    left = srv.copies.locks_in(link.id, settings.get(s, "linkReleaseMinutes"))
    return CopyOut(
        keyMadeAt=link.copyKeyAt,
        keyMadeBy=by.displayName if by else None,
        sizeBytes=size,
        receipts=receipts,
        items=s.scalar(
            select(func.count()).select_from(LinkedItem).where(LinkedItem.linkId == link.id)
        ),
        waiting=len(waiting(srv.config.data_dir, link.id)),
        unlocked=o is not None,
        unlockedBy=who.displayName if who else None,
        unlockedAt=o.at if o else None,
        locksInSeconds=int(left) if left is not None else None,
    )


def _incoming(s, link: Link) -> list[Incoming]:
    from ..store.entities.links import LinkedItem

    out = []
    for it in s.scalars(
        select(LinkedItem).where(LinkedItem.linkId == link.id).order_by(LinkedItem.sharedAt)
    ):
        ids_ = json.loads(it.viewers or "[]")
        names = [u.displayName for u in s.scalars(select(User).where(User.id.in_(ids_)))]
        out.append(
            Incoming(
                kind=it.kind,
                ownerName=it.ownerName,
                sharedAt=it.sharedAt,
                names=sorted(names),
                includeReceipts=it.includeReceipts,
            )
        )
    return out


def _outgoing(s, link: Link) -> list[Incoming]:
    """The shares this server sends over the link: one entry per item, with the people there
    it names."""
    from .. import sharing
    from ..errors import Problem
    from ..store.entities.sharing import Share

    remote = {
        u.id: u
        for u in s.scalars(select(User).where(User.linkId == link.id, User.deleted == false()))
    }
    if not remote:
        return []
    out: dict[tuple[str, str], Incoming] = {}
    for g in s.scalars(
        select(Share)
        .where(Share.userId.in_(list(remote)), Share.deleted == false())
        .order_by(Share.createdAt)
    ):
        e = out.get((g.kind, g.itemId))
        if e is None:
            try:
                obj = sharing.item(s, g.kind, g.itemId)
            except Problem:
                continue
            if getattr(obj, "deleted", False):
                continue
            owner_id = getattr(obj, "ownerId", None)
            owner = s.get(User, owner_id) if owner_id else None
            e = out[(g.kind, g.itemId)] = Incoming(
                kind=g.kind,
                ownerName=owner.displayName if owner else "",
                sharedAt=g.createdAt,
                names=[],
                includeReceipts=False,
            )
        e.names = sorted({*e.names, remote[g.userId].displayName})
        e.includeReceipts = e.includeReceipts or g.includeReceipts
    return list(out.values())


def _out(s, link: Link, srv=None) -> LinkOut:
    users = s.scalars(
        select(User)
        .where(User.linkId == link.id, User.deleted == false())
        .order_by(User.displayName)
    )
    return LinkOut(
        id=link.id,
        state=link.state,
        role=link.role,
        peerName=link.peerName,
        householdName=link.householdName,
        householdAvatar=json.loads(link.householdAvatar) if link.householdAvatar else None,
        address=link.address,
        fingerprint=keys.short(keys.fingerprint(keys.unb64(link.peerKey)))
        if link.peerKey
        else None,
        peerVersion=link.peerVersion,
        codeExpiresAt=link.codeExpiresAt if link.state == "invited" else None,
        lastOkAt=link.lastOkAt,
        lastError=link.lastError,
        failingSince=link.failingSince,
        createdAt=link.createdAt,
        endedAt=link.endedAt,
        pausedUntil=link.pausedUntil,
        syncThrough=link.syncThrough,
        syncBytes=link.syncBytes,
        syncTotal=link.syncTotal,
        users=[
            RemoteUser(id=u.id, username=u.username, displayName=u.displayName, email=u.email)
            for u in users
        ],
        certificate=keys.short(link.peerCert) if link.peerCert else None,
        certificateOffered=link.peerCertOffered,
        brokenAt=link.brokenAt,
        linkedCopy=_copy(s, srv, link) if srv is not None else None,
        incoming=_incoming(s, link),
        outgoing=_outgoing(s, link),
    )


def _problem(e: LinkError) -> Problem:
    status = 404 if e.code == "not-found" else 502 if e.code == "unreachable" else 422
    return refuse("code" if e.code.startswith("code") else None, e.code, e.message, status)


@router.get("/settings/links", response_model=LinksView)
def list_links(request: Request, c: Caller = Depends(admin)):
    from .. import certs

    srv = server(request)
    own_cert = certs.own_key(srv)
    with srv.db.tx(user=c.id) as s:
        fp = keys.fingerprint(keys.public_of(s, srv.keys.secrets))
        rows = s.scalars(
            select(Link).where(Link.deleted == false()).order_by(Link.createdAt.desc())
        ).all()
        return LinksView(
            fingerprint=keys.short(fp),
            address=manage.own_address(s),
            certificate=own_cert,
            links=[_out(s, r, srv) for r in rows],
        )


@router.post("/settings/links/invitations", response_model=Invitation, status_code=201)
def invite(request: Request, c: Caller = Depends(admin)):
    srv = server(request)
    try:
        link, code = manage.invite(srv, c.id)
    except LinkError as e:
        raise _problem(e) from None
    with srv.db.read(user=c.id) as s:
        return Invitation(code=code, link=_out(s, s.get(Link, link.id), srv))


@router.post("/settings/links/join", response_model=LinkOut, status_code=201)
def join(body: JoinIn, request: Request, c: Caller = Depends(admin)):
    srv = server(request)
    try:
        c_ = manage.decode_code(body.code)
    except LinkError as e:
        raise _problem(e) from None
    # The inviting server's address may be reached for the join, but it came from the other
    # server, so it is never exempt from the guard's refusal of loopback, link-local and
    # metadata addresses (S13.5), except between two dev servers on one machine.
    hosts, named = srv.guard.snapshot()
    from urllib.parse import urlsplit

    host = (urlsplit(c_["a"]).hostname or "").lower()
    srv.guard.allow(hosts | {host}, named | ({host} if srv.config.dev else set()))
    try:
        link = manage.join(srv, body.code, c.id)
    except LinkError as e:
        raise _problem(e) from None
    finally:
        apply_egress(srv)
    with srv.db.read(user=c.id) as s:
        return _out(s, s.get(Link, link.id), srv)


LOCAL = ("not-found", "state-invalid", "not-requested")


def _act(request: Request, c: Caller, link_id: str, fn) -> LinkOut:
    """A change here, then a call to the peer: what the peer answers is recorded on the link,
    and only this side's own refusals fail the request."""
    srv = server(request)
    try:
        fn(srv)
    except LinkError as e:
        if e.code in LOCAL:
            raise _problem(e) from None
    apply_egress(srv)
    with srv.db.read(user=c.id) as s:
        link = s.get(Link, link_id)
        if link is None or link.deleted:
            raise Problem(404, "not-found", "No such link.")
        return _out(s, link, srv)


@router.post("/settings/links/{link_id}/approve", response_model=LinkOut)
def approve(link_id: str, request: Request, c: Caller = Depends(admin)):
    return _act(request, c, link_id, lambda srv: manage.approve(srv, link_id, c.id))


class PauseIn(Model):
    for_: str = Field("1d", alias="for")  # a duration (S12.13): 1d, 2w 3d, 4h


@router.post("/settings/links/{link_id}/pause", response_model=LinkOut)
def pause(link_id: str, request: Request, body: PauseIn | None = None, c: Caller = Depends(admin)):
    """Pause for a duration, after which it resumes on its own (S11.7.2)."""
    from .. import duration

    try:
        span = duration.parse(body.for_ if body else "1d")
    except duration.DurationError as e:
        raise refuse("for", "duration-invalid", str(e)) from None
    until = clock.now() + span
    return _act(
        request, c, link_id, lambda srv: manage.set_state(srv, link_id, c.id, "paused", until)
    )


@router.post("/settings/links/{link_id}/resume", response_model=LinkOut)
def resume(link_id: str, request: Request, c: Caller = Depends(admin)):
    return _act(request, c, link_id, lambda srv: manage.set_state(srv, link_id, c.id, "active"))


@router.post("/settings/links/{link_id}/end", response_model=LinkOut)
def end(link_id: str, request: Request, c: Caller = Depends(admin)):
    """End a link, or reject a request, or withdraw an invitation."""
    return _act(request, c, link_id, lambda srv: manage.set_state(srv, link_id, c.id, "ended"))


@router.post("/settings/links/{link_id}/pull", response_model=LinkOut)
def pull_now(link_id: str, request: Request, c: Caller = Depends(admin)):
    """An exchange now rather than at the next hour (S11.7), recorded with who asked (S11.8)."""
    with server(request).db.tx(user=c.id) as s:
        if s.get(Link, link_id) is not None:
            activity.record(s, "link.pull-asked", actor=c.id, for_admins=True)
    return _act(request, c, link_id, lambda srv: manage.exchange(srv, link_id))


class Words(Model):
    words: list[str]  # shown once


def _copy_problem(e) -> Problem:
    status = 404 if e.code == "not-found" else 409 if e.code == "key-exists" else 422
    return Problem(status, e.code, e.message)


@router.post("/settings/links/{link_id}/copy-key", response_model=Words)
def make_copy_key(link_id: str, request: Request, c: Caller = Depends(admin)):
    """Create the access key (S11.9.2.1): 12 words, shown once; the password again if given
    over 10 minutes ago (S13.7.2)."""
    from ..links import copies
    from ..links.copy import CopyError
    from .deps import recent_auth

    recent_auth(c)
    try:
        return Words(words=copies.make_key(server(request), link_id, c.id))
    except CopyError as e:
        raise _copy_problem(e) from None


@router.post("/settings/links/{link_id}/accept-certificate", response_model=LinkOut)
def accept_certificate(link_id: str, request: Request, c: Caller = Depends(admin)):
    """The certificate the peer presented unannounced, accepted once its fingerprint has been
    compared with the peer's admin (link-protocol.md §4.5): the password again (S13.7.2)."""
    from .deps import recent_auth

    recent_auth(c)
    try:
        manage.accept_certificate(server(request), link_id, c.id)
    except LinkError as e:
        raise _problem(e) from None
    with server(request).db.read(user=c.id) as s:
        return _out(s, s.get(Link, link_id), server(request))


@router.post("/settings/links/{link_id}/lock", response_model=LinkOut)
def lock_copy(link_id: str, request: Request, c: Caller = Depends(admin)):
    from ..links import copies

    return _act(request, c, link_id, lambda srv: copies.lock(srv, link_id, c.id, True))


@router.post("/settings/links/{link_id}/reset-copy", response_model=JobOut, status_code=202)
def reset_copy(link_id: str, request: Request, c: Caller = Depends(admin)):
    """The copy deleted and taken again in full, as a job (S11.9.8, S13.8.7); the password
    again if given over 10 minutes ago (S13.7.2)."""
    from ..links import copies
    from .deps import recent_auth

    recent_auth(c)
    srv = server(request)
    with srv.db.read(user=c.id) as s:
        link = s.get(Link, link_id)
        if link is None or link.deleted:
            raise Problem(404, "not-found", "No such link.")

    def work(job) -> dict:
        copies.reset(srv, link_id, c.id)
        # Pulled again in full at once; a failure is recorded on the link, and the next
        # hourly exchange tries again.
        with contextlib.suppress(LinkError):
            manage.exchange(srv, link_id)
        apply_egress(srv)
        return {"linkId": link_id}

    return accepted(srv.jobs.start("reset-copy", c.id, work))
