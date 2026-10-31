"""The /link listener (requirements S11.1.3, S11.2): what a linked server calls. Everything but
`hello` is signed by a key this server has a link with (`join`: the caller's own, which the
link code vouches for), checked by the gate before its body is read, and every answer is
signed back (`gate.py`)."""

import re
import threading

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import false, select

from .. import clock, ratelimit
from ..store.entities.links import Link
from . import PROTOCOL, SUPPORTED, keys, signing
from .gate import Call, Gate, Kind

KIND = Kind(
    scheme=signing.LINK,
    name="link protocol",
    protocol=PROTOCOL,
    supported=tuple(SUPPORTED),
    nonces=lambda srv: srv.link_nonces,
    limit=lambda srv: srv.link_limit,
    unknown=lambda srv: srv.link_unknown,
)
gate = Gate(KIND)
router = APIRouter(prefix="/link/v1", include_in_schema=False)

# A join's body is a code, an address and a time: a few hundred bytes (S13.7.5.4).
JOIN_BODY = 16 * 1024


def own(srv) -> tuple[object, str]:
    """This server's link key, to sign an answer, and its fingerprint."""
    return keys.signing_key(srv), keys.own_public(srv)[1]


def link_in(*states: str):
    """The finder for a route the peer's link must be in one of these states to call; its
    calls count against that link (S13.7.5.4)."""

    def find(srv, caller: signing.Caller) -> tuple[Link, str]:
        with srv.db.read() as s:
            link = s.scalars(
                select(Link).where(Link.peerKey == keys.b64(caller.public), Link.deleted == false())
            ).first()
        if link is None:
            raise signing.Refused("not-linked", "This server has no link with yours.")
        if link.state not in states:
            until = (
                f" until {link.pausedUntil:%b %-d, %H:%M} UTC"
                if link.state == "paused" and link.pausedUntil
                else ""
            )
            raise signing.Refused(
                f"link-{link.state}", f"The link is {link.state} on this side{until}."
            )
        return link, link.id

    return find


def hello_limit(request: Request) -> None:
    """The unsigned hello, 60 a minute from one address (S13.7.5.4)."""
    srv = request.app.state.server
    host = request.client.host if request.client else None
    srv.link_unknown.check(ratelimit.address_key(host), "calls from this address")


@router.get("/hello", dependencies=[Depends(hello_limit)])
def hello(request: Request):
    """Unsigned: the protocol this server speaks and its key's fingerprint, so a joining server
    can check it against the link code before sending anything."""
    srv = request.app.state.server
    public, fp = keys.own_public(srv)
    return {
        "protocol": PROTOCOL,
        "version": srv.version,
        "fingerprint": fp,
        "key": keys.b64(public),
    }


@router.post("/ping")
@gate.route(link_in("active", "paused", "pending", "requested"))
def ping(call: Call):
    srv, link = call.srv, call.found
    with srv.db.tx() as s:
        row = s.get(Link, link.id)
        row.lastOkAt = clock.now()
        row.peerVersion = call.header("mk-link-version")
    return {"protocol": PROTOCOL, "version": srv.version, "state": link.state}


@router.post("/join")
@gate.route(max_body=JOIN_BODY)
def join(call: Call):
    """A server answering an invitation: signed by its own key, which the code vouches for."""
    from .manage import answer_join

    out = answer_join(call.srv, call.caller.public, call.json())
    if "error" in out:
        raise signing.Refused(*out["error"])
    return {**out, "state": "requested", "version": call.srv.version}


@router.post("/exchange")
@gate.route(link_in("active", "pending"))
def exchange(call: Call):
    """Each side's directory for the other's: users and household (S11.3)."""
    from .manage import answer_exchange

    return answer_exchange(call.srv, call.found, call.json(), call.header("mk-link-version"))


@router.post("/end")
@gate.route(link_in("requested", "pending", "active", "paused"))
def end(call: Call):
    from .manage import answer_end

    answer_end(call.srv, call.found)
    return {"state": "ended"}


@router.post("/next")
@gate.route(link_in("active"))
def next_part(call: Call):
    """The next part of a large change the caller is pulling (S11.4), oldest first."""
    from .manage import answer_next

    return answer_next(call.srv, call.found, call.json())


class Delivered:
    """Receipts delivered ahead of the change that names them, by link: each one's id and the
    random name it was kept under. Written and read from the thread pool."""

    def __init__(self):
        self._lock = threading.Lock()
        self._by_link: dict[str, dict[str, str]] = {}

    def put(self, link_id: str, file_id: str, name: str) -> None:
        with self._lock:
            self._by_link.setdefault(link_id, {})[file_id] = name

    def take(self, link_id: str) -> dict[str, str] | None:
        with self._lock:
            return self._by_link.pop(link_id, None)

    def names(self, link_id: str) -> set[str]:
        with self._lock:
            return set(self._by_link.get(link_id, {}).values())


DELIVERED = Delivered()
FILE_ID = re.compile(r"[A-Za-z]{2,8}_[0-9a-z]{26}")


@router.post("/deliver")
@gate.route(link_in("active"), files=True)
def deliver(call: Call):
    """The caller's change for this server, after an exchange it made (S11.4); or, before it,
    one of the receipts that change sends, sealed by the caller to this side's copy key, as
    `application/octet-stream` with `MK-Link-File` naming it (link-protocol.md §4.3): read as
    it arrives, never whole in memory, and kept as it came."""
    srv, link = call.srv, call.found
    if call.file is not None:
        fid = call.header("mk-link-file") or ""
        if not FILE_ID.fullmatch(fid):
            raise signing.Refused("file-refused", "The file isn't named.")
        from .receive import keep_delivered

        with open(call.file, "rb") as f:
            name = keep_delivered(srv, link.id, iter(lambda: f.read(1 << 16), b""))
        DELIVERED.put(link.id, fid, name)
        return {"ok": True}
    from .changes import ChangeError
    from .manage import answer_deliver

    try:
        return answer_deliver(srv, link, call.json())
    except ChangeError as e:
        raise signing.Refused("change-refused", str(e)) from None


@router.post("/certificate")
@gate.route(link_in("active", "paused"))
def certificate(call: Call):
    """The peer's next TLS certificate key, announced before it is used (link-protocol.md
    §4.5): accepted beside the pinned one until it is in use."""
    from .manage import answer_certificate

    return answer_certificate(call.srv, call.found, call.json())


@router.post("/file")
@gate.route(link_in("active"))
def file(call: Call):
    """One receipt, for a peer whose people may have it (S11.5.1): sealed to the caller's copy
    key, so only that copy opens it, and its answer signed over the sealed bytes' hash."""
    from .changes import ChangeError
    from .serve import allowed_file, sealed_receipt, stream_file

    srv, link = call.srv, call.found
    rid = str(call.json().get("id") or "")
    if not allowed_file(srv, link.id, rid):
        raise signing.Refused("not-shared", "That receipt isn't shared.")
    try:
        path, digest = sealed_receipt(srv, link.id, rid)
    except ChangeError as e:
        raise signing.Refused("not-shared", str(e)) from None
    # Sealed to the caller's copy key, and signed over the sealed bytes (link-protocol.md §4).
    return StreamingResponse(
        stream_file(path),
        media_type="application/octet-stream",
        headers=gate.signed_headers(srv, call.asked, digest),
    )
