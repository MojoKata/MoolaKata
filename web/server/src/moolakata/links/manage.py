"""Making, approving, pausing and ending links (requirements S11.1, S11.6), and the directory
each side sends the other at every exchange: its active users and its household (S11.3).

A link code is `mkl1.` and base64url JSON: the inviting server's link address (`a`), its key's
fingerprint (`f`) and a one-time secret (`c`). The inviting side keeps only the secret's hash,
and the code works once, for 24 hours."""

import contextlib
import datetime as dt
import hashlib
import json
import logging
import re
import secrets

from sqlalchemy import false, select

from .. import activity, clock, ids, people, settings
from ..store.entities.education import Person
from ..store.entities.links import Link
from ..store.entities.users import User
from . import client, keys, lifecycle
from .changes import ChangeError
from .client import LinkError

log = logging.getLogger("moolakata.links")

CODE_HOURS = 24


def own_address(s) -> str | None:
    return settings.get(s, "linkAddress") or settings.get(s, "publicUrl")


def household(s) -> dict:
    return {
        "serverName": settings.get(s, "serverName"),
        "name": settings.get(s, "householdName"),
        "avatar": settings.get(s, "householdAvatar"),
    }


def directory(s) -> dict:
    """What this server tells a peer about itself at every exchange (S11.3)."""
    users = s.scalars(
        select(User)
        .where(User.deleted == false(), User.active, User.linkId.is_(None))
        .order_by(User.displayName)
    )
    return {
        "household": household(s),
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "displayName": u.displayName,
                "email": u.email,
                "sex": people.of_user(s, u.id).sex,
            }
            for u in users
        ],
    }


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def encode_code(address: str, fp: str, secret: str, cert: str | None = None) -> str:
    """A link code (link-protocol.md §4.1); `t`, the fingerprint of this server's certificate
    key, only when that certificate is its own."""
    body = {"a": address, "f": fp, "c": secret, **({"t": cert} if cert else {})}
    raw = json.dumps(body, separators=(",", ":")).encode()
    return "mkl1." + keys.b64(raw)


FINGERPRINT = re.compile(r"[0-9a-f]{64}")


def _cert(value) -> str | None:
    """A certificate key's fingerprint as a code or a peer sends it; anything else is none."""
    return value if isinstance(value, str) and FINGERPRINT.fullmatch(value) else None


def pins(link: Link) -> frozenset[str] | None:
    """The certificate keys a peer whose certificate is its own may present: the pinned one
    and the next it announced. None: a public certificate, verified against the system's
    roots."""
    have = {x for x in (link.peerCert, link.peerCertNext) if x}
    return frozenset(have) if have else None


def decode_code(code: str) -> dict:
    code = "".join(code.split())
    if not code.startswith("mkl1."):
        raise LinkError("code-invalid", "That isn't a MoolaKata link code: it starts mkl1.")
    try:
        out = json.loads(keys.unb64(code[5:]))
        assert isinstance(out, dict) and {"a", "f", "c"} <= set(out)
    except ValueError, AssertionError:
        raise LinkError("code-invalid", "The link code is damaged: copy it again whole.") from None
    return out


def call(srv, link_id: str, path: str, data: dict | None = None) -> dict:
    """A signed call to a linked server, its TLS checked against the certificate keys pinned
    for it. One it announced, once presented, becomes the one pinned; one it didn't is kept
    for an admin to accept, and the link says so (link-protocol.md §4.5)."""
    with srv.db.read() as s:
        link = _get(s, link_id)
        address, peer, pinned = link.address, keys.unb64(link.peerKey), pins(link)
        announced = link.peerCertNext
    seen: list[str] = []
    try:
        out = client.call(srv, address, peer, path, data, pins=pinned, seen=seen)
    except LinkError as e:
        if e.code == "certificate-changed" and e.offered:
            with srv.db.tx() as s:
                row = _get(s, link_id)
                row.peerCertOffered = e.offered
                row.lastError = e.message
                row.failingSince = row.failingSince or clock.now()
        elif e.code == "link-ended" and path != "/link/v1/end":
            ended_by_peer(srv, link_id)
        elif e.code == "not-linked":
            # A peer restored from an older backup, say: broken, for an admin to end or link
            # again, never ended by an answer that isn't the peer's `link-ended` (S11.6).
            with srv.db.tx() as s:
                row = _get(s, link_id)
                with contextlib.suppress(LinkError):  # an ended or new link takes no mark
                    lifecycle.apply(row, "not-linked")
                row.lastError = "The other server has no link with this one: end it, or link again."
                row.failingSince = row.failingSince or clock.now()
        raise
    if seen and announced and seen[0] == announced:
        with srv.db.tx() as s:
            row = _get(s, link_id)
            row.peerCert, row.peerCertNext = row.peerCertNext, None
    return out


def ended_by_peer(srv, link_id: str) -> None:
    """The peer's signed `link-ended`: the link ends here too, its copy, shares and remote
    users with it (S11.6)."""
    from . import receive

    with srv.db.tx() as s:
        row = _get(s, link_id)
        if not lifecycle.apply(row, "link-ended").ended:
            return
        end_users(s, row)
        activity.record(s, "link.ended-by-peer", actor=None, for_admins=True)
    receive.forget(srv, link_id)


def accept_certificate(srv, link_id: str, by: str) -> Link:
    """An admin accepts the certificate key a peer presented unannounced, once they have
    compared it with the peer's admin (link-protocol.md §4.5)."""
    with srv.db.tx() as s:
        link = _get(s, link_id)
        if not link.peerCertOffered:
            raise LinkError("no-certificate", "No other certificate is waiting to be accepted.")
        link.peerCert, link.peerCertNext = link.peerCertOffered, None
        link.peerCertOffered = None
        link.lastError = link.failingSince = None
        activity.record(s, "link.certificate-accepted", actor=by, for_admins=True)
        return link


def announce_certificate(srv) -> int:
    """This server's own certificate key, when it changed since it was last told to the peers:
    told to each active or paused link, signed (link-protocol.md §4.5). Returns how many were
    told."""
    from .. import certs

    key = certs.own_key(srv)
    with srv.db.read() as s:
        told = settings.get(s, "linkCertificate")
        ids_ = list(
            s.scalars(
                select(Link.id).where(Link.deleted == false(), Link.state.in_(("active", "paused")))
            )
        )
    if (key or None) == (told or None):
        return 0
    n = 0
    for link_id in ids_:
        with contextlib.suppress(LinkError):  # it learns at the next exchange instead
            call(srv, link_id, "/link/v1/certificate", {"fingerprint": key})
            n += 1
    with srv.db.tx() as s:
        settings.put(s, "linkCertificate", key, None)
    return n


def answer_certificate(srv, link: Link, body: dict) -> dict:
    """A peer announces its next certificate key; either is accepted until it is in use."""
    key = _cert(body.get("fingerprint"))
    with srv.db.tx() as s:
        row = _get(s, link.id)
        if key and key != row.peerCert:
            row.peerCertNext = key
            if row.peerCertOffered == key:  # presented early: the announcement vouches for it
                row.peerCert, row.peerCertNext, row.peerCertOffered = key, None, None
                row.lastError = row.failingSince = None
    return {"ok": True}


def invite(srv, by: str) -> tuple[Link, str]:
    """An invitation: a link waiting for the other server, and the code shown once."""
    from .. import certs

    cert = certs.own_key(srv)
    with srv.db.tx() as s:
        address = own_address(s)
        if not address:
            raise LinkError(
                "no-address",
                "Set this server's link address (or its public URL) first, so the other server "
                "can reach it.",
            )
        own = keys.private_key(s, srv.keys.secrets, by)
        fp = keys.fingerprint(keys.raw_public(own.public_key()))
        secret = secrets.token_urlsafe(24)
        link = Link(
            id=ids.new_id("Link"),
            state=lifecycle.start("invite"),
            role="inviter",
            codeHash=_hash(secret),
            codeExpiresAt=clock.now() + dt.timedelta(hours=CODE_HOURS),
            createdById=by,
        )
        s.add(link)
        activity.record(s, "link.invited", actor=by, for_admins=True)
        s.flush()
        return link, encode_code(address, fp, secret, cert)


def join(srv, code: str, by: str) -> Link:
    """Answer an invitation: check the inviting server's key against the code, then ask it to
    link. The link waits for that server's admin to approve it."""
    from .. import certs

    c = decode_code(code)
    theirs = _cert(c.get("t"))
    pinned = frozenset([theirs]) if theirs else None
    hi = client.hello(srv, c["a"], pinned)
    peer = keys.unb64(hi.get("key", ""))
    if keys.fingerprint(peer) != c["f"]:
        raise LinkError(
            "fingerprint-mismatch",
            "The server at that address doesn't have the key the code names: nothing was sent.",
        )
    with srv.db.tx() as s:
        address = own_address(s)
        if not address:
            raise LinkError(
                "no-address",
                "Set this server's link address (or its public URL) first, so the other server "
                "can reach it.",
            )
        old = _with_key(s, peer)
        if old is not None:
            lifecycle.step(old.state, old.brokenAt is not None, "link-again")  # or refused
    # No directory crosses before the other side's admin approves (link-protocol.md §4.1).
    mine = certs.own_key(srv)
    body = {"code": c["c"], "address": address, **({"t": mine} if mine else {})}
    client.call(srv, c["a"], peer, "/link/v1/join", body, pins=pinned)
    with srv.db.tx() as s:
        gone = _link_again(s, peer, by)
        link = Link(
            id=ids.new_id("Link"),
            state=lifecycle.start("join-here"),
            role="joiner",
            address=client.checked_address(c["a"]),
            peerKey=keys.b64(peer),
            peerCert=theirs,
            peerVersion=hi.get("version"),
            peerProtocol=hi.get("protocol"),
            createdById=by,
            lastOkAt=clock.now(),
        )
        s.add(link)
        s.flush()
        activity.record(s, "link.requested", actor=by, for_admins=True)
    if gone:
        from . import receive

        receive.forget(srv, gone)
    return link


def answer_join(srv, caller_key: bytes, body: dict) -> dict:
    """The inviting side: a live code turns its invitation into a request from that key."""
    code = body.get("code") or ""
    with srv.db.tx() as s:
        link = s.scalars(
            select(Link).where(
                Link.codeHash == _hash(code), Link.state == "invited", Link.deleted == false()
            )
        ).first()
        if link is None or link.codeExpiresAt <= clock.now():
            return {"error": ("code-used", "That link code was used, expired or withdrawn.")}
        try:
            address = client.checked_address(str(body.get("address") or ""))
            gone = _link_again(s, caller_key)
        except LinkError as e:
            return {"error": (e.code, e.message)}
        lifecycle.apply(link, "join-arrives")
        link.codeHash = None
        link.peerKey = keys.b64(caller_key)
        link.address = address
        link.peerCert = _cert(body.get("t"))
        link.lastOkAt = clock.now()
        s.flush()
        activity.record(s, "link.request-received", actor=None, for_admins=True)
    if gone:
        from . import receive

        receive.forget(srv, gone)
    # Nothing of either household crosses until the admin approves (S10.10.1).
    return {}


def apply_directory(s, link: Link, payload: dict) -> None:
    """The peer's household and active users, kept as remote users by their id there: added,
    updated in place, soft-deleted when gone, and restored when they return (S11.3)."""
    h = payload.get("household") or {}
    link.peerName = h.get("serverName") or link.peerName
    link.householdName = h.get("name") or link.householdName
    if h.get("avatar") is not None:
        link.householdAvatar = json.dumps(h["avatar"])
    seen = set()
    now = clock.now()
    have = {u.remoteId: u for u in s.scalars(select(User).where(User.linkId == link.id))}
    for r in payload.get("users") or []:
        rid = str(r.get("id") or "")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        u = have.get(rid)
        name = str(r.get("displayName") or r.get("username") or "?")[:120]
        # A remote user's person is its own, filled from its server, for gifts; it is joined
        # to a person here only when someone who may change that one confirms it (S10.10.1).
        sex = r.get("sex") if r.get("sex") in people.SEXES else "male"
        if u is None:
            u = User(
                id=ids.new_id("User"),
                personId=people.make(s, name, sex).id,
                username=str(r.get("username") or rid)[:64],
                displayName=name,
                email=r.get("email"),
                linkId=link.id,
                remoteId=rid,
                alertEmails="none",
            )
            s.add(u)
            continue
        u.username = str(r.get("username") or u.username)[:64]
        u.displayName = str(r.get("displayName") or u.displayName)[:120]
        p = s.get(Person, u.personId)
        if p is not None and p.ownerId is None:  # its own person, never one joined to it here
            people.change(s, p, {"name": u.displayName, "sex": sex})
        u.email = r.get("email")
        u.active = True
        if u.deleted:
            u.restore()
    for rid, u in have.items():
        if rid not in seen and not u.deleted:
            u.mark_deleted(None, now)
    s.flush()


def end_users(s, link: Link) -> None:
    """A link ended: its users are removed here, with the shares that name them (S10.3.3)."""
    from ..sharing import remove_link_shares

    remove_link_shares(s, link.id)
    now = clock.now()
    for u in s.scalars(select(User).where(User.linkId == link.id, User.deleted == false())):
        u.mark_deleted(None, now)


def _get(s, link_id: str) -> Link:
    link = s.get(Link, link_id)
    if link is None or link.deleted:
        raise LinkError("not-found", "No such link.")
    return link


def _with_key(s, peer: bytes) -> Link | None:
    """The link this server has with the server whose key this is: at most one is live."""
    return s.scalars(
        select(Link).where(Link.peerKey == keys.b64(peer), Link.deleted == false())
    ).first()


def _link_again(s, peer: bytes, by: str | None = None) -> str | None:
    """Linking again with a server this one already had a link with (S11.6): an ended link is
    put aside for the new one, a broken one ended first, its copy deleted (the id returned,
    for the caller to forget once the transaction is done); any other is the link the two
    already have, refused."""
    old = _with_key(s, peer)
    if old is None:
        return None
    got = lifecycle.apply(old, "link-again", by)
    if got.ended:
        old.codeHash = None
        end_users(s, old)
        activity.record(s, "link.ended", actor=by, for_admins=True)
    s.flush()  # put aside before the new link takes its key
    return old.id if got.ended else None


def approve(srv, link_id: str, by: str) -> Link:
    with srv.db.tx() as s:
        link = _get(s, link_id)
        lifecycle.apply(link, "approve")
        link.approvedById = by
        link.approvedAt = clock.now()
        activity.record(s, "link.approved", actor=by, for_admins=True)
    with contextlib.suppress(LinkError):  # else the other side learns at its next exchange
        exchange(srv, link_id)  # tells the other side at once when it can be reached
    return link


def set_state(
    srv, link_id: str, by: str | None, state: str, until: dt.datetime | None = None
) -> Link:
    """Reject a request, pause (until a time), resume or end a link on this side."""
    with srv.db.tx() as s:
        link = _get(s, link_id)
        was = link.state
        event = {"paused": "pause", "active": "resume", "ended": "end-here"}[state]
        try:
            lifecycle.apply(link, event)
        except LinkError:
            raise LinkError(
                "state-invalid", f"A link that is {link.state} can't be {state}."
            ) from None
        link.pausedUntil = until if state == "paused" else None
        if state == "ended":
            link.codeHash = None
            end_users(s, link)
        kind = {"paused": "link.paused", "active": "link.resumed", "ended": "link.ended"}[state]
        activity.record(s, kind, actor=by, for_admins=True)
        peer = link.peerKey
    if state == "ended":
        from . import receive

        receive.forget(srv, link_id)
    if state == "ended" and was in ("requested", "pending", "active", "paused") and peer:
        with contextlib.suppress(LinkError):  # else the other side learns at its next call
            call(srv, link_id, "/link/v1/end")
    return link


def exchange(srv, link_id: str) -> None:
    """One exchange with the peer (S11.2–S11.4), made by whichever side can reach the other:
    each side's directory and copy key for the other's, the peer's change for this side in its
    answer, and then this side's change for the peer, its receipts sent ahead of it. Only a
    signed `link-ended` ends the link here (S11.6)."""
    from ..ui.prices import apply_egress

    with srv.db.read() as s:
        link = _get(s, link_id)
        if link.state not in ("active", "pending"):
            return
    # A peer's host joins the egress guard's list when its request arrives; make sure the
    # guard knows it before calling (S13.5).
    apply_egress(srv)
    with srv.db.read() as s:
        link = _get(s, link_id)
        pending = link.state == "pending"
        # A link not yet approved over there gets no directory (link-protocol.md §4.1).
        mine = {
            **({} if pending else directory(s)),
            "have": link.gotSeq,
            "wantFull": link.needsFull,
            **({"copyKey": link.copyPublicKey} if link.copyPublicKey else {}),
        }
    try:
        out = call(srv, link_id, "/link/v1/exchange", mine)
    except LinkError as e:
        if e.code in ("link-requested", "link-ended"):
            return  # not approved there yet; or ended, here too now
        if e.code in ("not-linked", "certificate-changed"):
            raise  # recorded on the link as it is (S11.6, link-protocol.md §4.5)
        with srv.db.tx() as s:
            link = _get(s, link_id)
            if e.code == "link-paused":
                # Paused on the other side: waits, and isn't alerted (S11.7.2).
                link.lastError = e.message
            else:
                # A clock more than a minute off is named as such (S12.11.1.1): the fix is
                # NTP on one host, not the network.
                link.lastError = (
                    f"the clocks disagree: {e.message}" if e.code == "clock-skew" else e.message
                )
                link.failingSince = link.failingSince or clock.now()
        raise
    with srv.db.tx() as s:
        link = _get(s, link_id)
        if out.get("state") == "active":
            lifecycle.apply(link, "peer-active")
        lifecycle.apply(link, "good-call")
        link.lastOkAt, link.lastError, link.failingSince = clock.now(), None, None
        link.peerVersion = out.get("version") or link.peerVersion
        link.peerCopyKey = _copy_key(out.get("copyKey"))
        apply_directory(s, link, out)
        active = link.state == "active"
    if not active:
        return
    if pending:
        # Approved there: this side's directory goes now, with the first exchange proper.
        return exchange(srv, link_id)
    try:
        _rest_of_exchange(srv, link_id, out)
    except (LinkError, ChangeError) as e:
        # What fails after the first call is recorded on the link like a failed call, so a
        # link that keeps failing is alerted (S12.11.1), never left showing a good exchange.
        message = e.message if isinstance(e, LinkError) else f"A change failed: {e}"
        with srv.db.tx() as s:
            link = _get(s, link_id)
            link.lastError = message
            link.failingSince = link.failingSince or clock.now()
        if isinstance(e, LinkError):
            raise
        raise LinkError("change-failed", message) from e


def _rest_of_exchange(srv, link_id: str, out: dict) -> None:
    """After the exchange call: the peer's change taken, the receipts not yet arrived asked
    for again, then this side's change sent, each of its receipts ahead of it."""
    from . import receive, serve

    tried: set[str] = set()
    if out.get("change"):
        tried |= receive.take(srv, link_id, out["change"])
        # The rest of a large change, part by part, oldest first (S11.4).
        more = int(out.get("more") or 0)
        while more > 0:
            with srv.db.read() as s:
                got = _get(s, link_id).gotSeq
            nxt = call(srv, link_id, "/link/v1/next", {"have": got})
            if not nxt.get("change"):
                break
            tried |= receive.take(srv, link_id, nxt["change"])
            more = int(nxt.get("more") or 0)
    receive.fetch_missing(srv, link_id, tried)
    mine = serve.change_for(srv, link_id, int(out.get("have") or 0), bool(out.get("wantFull")))
    for part in mine:
        for fid in part.get("fetch") or []:
            try:
                _deliver_file(srv, link_id, fid)
            except LinkError as e:
                # The peer fetches what it lacks, and keeps any it can't as not arrived: one
                # receipt never holds the change back (S11.4).
                log.info("delivering a receipt to link %s failed: %s", link_id, e.code)
        answer = call(srv, link_id, "/link/v1/deliver", {"change": part})
        if answer.get("have") != part.get("seq"):
            break  # the peer missed one: its next exchange asks again
    if mine:
        _served(srv, link_id, mine[0])


def _copy_key(value) -> str | None:
    """A peer's copy key as it sends it: 32 bytes, base64url; anything else is none."""
    try:
        return value if isinstance(value, str) and len(keys.unb64(value)) == 32 else None
    except ValueError:
        return None


def _deliver_file(srv, link_id: str, file_id: str) -> None:
    """One of this side's receipts, sealed to the peer's copy key, sent ahead of the change
    that names it (link-protocol.md §4.3)."""
    from . import serve

    path, digest = serve.sealed_receipt(srv, link_id, file_id)
    with srv.db.read() as s:
        link = _get(s, link_id)
        address, peer, pinned = link.address, keys.unb64(link.peerKey), pins(link)
    try:
        client.send_file(srv, address, peer, file_id, path, digest, pinned)
    finally:
        path.unlink(missing_ok=True)


def _served(srv, link_id: str, change: dict) -> None:
    from .receive import shares_of

    with srv.db.tx() as s:
        activity.record(
            s,
            "link.served",
            actor=None,
            subject_kind="link",
            subject_id=link_id,
            for_admins=True,
            detail={
                "count": len(change.get("items") or []) + len(change.get("removed") or []),
                "shares": shares_of(s, link_id, change, here=False),
            },
        )


def answer_exchange(srv, link: Link, body: dict, version: str | None) -> dict:
    from . import serve

    with srv.db.tx() as s:
        row = _get(s, link.id)
        lifecycle.apply(row, "peer-active")  # only an approved link calls this way
        lifecycle.apply(row, "good-call")
        row.lastOkAt, row.lastError, row.failingSince = clock.now(), None, None
        row.peerVersion = version or row.peerVersion
        row.peerCopyKey = _copy_key(body.get("copyKey"))
        apply_directory(s, row, body)
        out = {
            **directory(s),
            "state": row.state,
            "version": srv.version,
            "have": row.gotSeq,
            "wantFull": row.needsFull,
            **({"copyKey": row.copyPublicKey} if row.copyPublicKey else {}),
        }
        active = row.state == "active"
    if active:
        parts = serve.change_for(
            srv, link.id, int(body.get("have") or 0), bool(body.get("wantFull"))
        )
        if parts:
            out["change"] = parts[0]
            out["more"] = len(parts) - 1
            # Kept for the peer to ask for, one at a time, while it is pulling.
            PENDING[link.id] = parts[1:]
            _served(srv, link.id, parts[0])
    return out


PENDING: dict[str, list[dict]] = {}  # the parts of a large change still to send, by link


def answer_next(srv, link: Link, body: dict) -> dict:
    """The next part of a large change the peer is pulling, when its `have` is the part
    before; nothing when it isn't, and its next exchange starts again."""
    rest = PENDING.get(link.id) or []
    if not rest or int(body.get("have") or 0) + 1 != rest[0].get("seq"):
        PENDING.pop(link.id, None)
        return {"change": None, "more": 0}
    part = rest.pop(0)
    if not rest:
        PENDING.pop(link.id, None)
    return {"change": part, "more": len(rest)}


def answer_deliver(srv, link: Link, body: dict) -> dict:
    from . import receive
    from .routes import DELIVERED

    if body.get("change"):
        receive.take(srv, link.id, body["change"], DELIVERED.take(link.id))
    with srv.db.read() as s:
        return {"have": _get(s, link.id).gotSeq}


def answer_end(srv, link: Link) -> None:
    from . import receive

    with srv.db.tx() as s:
        row = _get(s, link.id)
        if lifecycle.apply(row, "link-ended").ended:
            end_users(s, row)
            activity.record(s, "link.ended-by-peer", actor=None, for_admins=True)
    receive.forget(srv, link.id)


def resume_due(srv) -> int:
    """Links whose pause has run out resume on their own (S11.7.2)."""
    with srv.db.read() as s:
        due = list(
            s.scalars(
                select(Link.id).where(
                    Link.deleted == false(),
                    Link.state == "paused",
                    Link.pausedUntil.is_not(None),
                    Link.pausedUntil <= clock.now(),
                )
            )
        )
    for link_id in due:
        set_state(srv, link_id, None, "active")
    return len(due)


def exchange_all(srv, ctx=None) -> None:
    """Every link that exchanges: active ones, and joined ones waiting for approval; a pause
    that has run out ends first."""
    resume_due(srv)
    with srv.db.read() as s:
        wanted = list(
            s.scalars(
                select(Link.id).where(
                    Link.deleted == false(), Link.state.in_(("active", "pending"))
                )
            )
        )
    for link_id in wanted:
        if ctx is not None and ctx.stop.is_set():
            break
        with contextlib.suppress(LinkError):  # recorded on the link; alerts follow it
            exchange(srv, link_id)
