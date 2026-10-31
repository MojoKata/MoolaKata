"""The /connector/v1 listener (requirements S18.4.3, docs/connector-protocol.md): what the
paired MoolaKata Connector calls. Everything but `hello` is signed by one of the connector's
keys: its action key, or, for a report that it is locked and `unpaired` only, its status key
(S18.4.2). Every answer is signed back by this server's link key."""

import functools
import hashlib
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import false, select

from .. import exactjson
from ..links import keys, signing
from ..links.routes import own
from ..store.entities.accounts import Account
from ..store.entities.connector import Connector
from . import PROTOCOL, SUPPORTED, manage

router = APIRouter(prefix="/connector/v1", include_in_schema=False)
log = logging.getLogger("moolakata.connector")
DIGEST = "mk-conn-body-sha256"
STATUS = {
    "protocol-unsupported": 426,
    "limit": 429,
    "not-found": 404,
    "too-large": 413,
    "server-error": 500,
}


def answer(srv, data: dict, asked: signing.Asked, status: int = 200, headers=None) -> Response:
    """Signed to the call it answers: its nonce, the connector and its body (protocol §3.3)."""
    body = exactjson.dumps(data, separators=(",", ":")).encode()
    k, _ = own(srv)
    signed = signing.sign_answer(k, status, body, asked, scheme=signing.CONN)
    return Response(
        body,
        status_code=status,
        media_type="application/json",
        headers={**signed, **(headers or {})},
    )


def refusal(request: Request, e: signing.Refused, headers=None) -> Response:
    status = STATUS.get(e.code, 403)
    call = asked(request)
    if call is None:
        return JSONResponse(
            {"code": e.code, "message": e.message}, status_code=status, headers=headers
        )
    return answer(
        request.app.state.server, {"code": e.code, "message": e.message}, call, status, headers
    )


def asked(request: Request) -> signing.Asked | None:
    """The call being answered, by the body hash its signature covers, which it names in a
    header (protocol §3.1): an answer can be signed before, or without, reading the body."""
    digest = request.headers.get(DIGEST) or None
    return signing.asked_of(
        request.headers, getattr(request, "_body", b""), signing.CONN, digest=digest
    )


def _protocol(request: Request) -> int:
    asked = request.headers.get("mk-conn-protocol", str(PROTOCOL))
    if not asked.isdigit() or int(asked) not in SUPPORTED:
        raise signing.Refused(
            "protocol-unsupported",
            f"This server speaks connector protocol {', '.join(map(str, SUPPORTED))}; "
            f"yours sent {asked}. The older side needs updating.",
        )
    return int(asked)


async def _signed(request: Request, before_body=None) -> tuple[signing.Caller, bytes, int]:
    """The verified caller and body of a signed call, whoever the caller is. The signature is
    checked against the body hash the call names (`MK-Conn-Body-SHA256`), and `before_body`
    run with the caller, before a byte of the body is read; the body read must then hash to
    it (protocol §3.2). So only a call the paired connector signed has its body read."""
    srv = request.app.state.server
    protocol = _protocol(request)
    digest = request.headers.get(DIGEST, "")
    if len(digest) != 64 or digest.strip("0123456789abcdef"):
        raise signing.Refused("unsigned", "A call names its body's SHA-256 (MK-Conn-Body-SHA256).")
    _, fp = own(srv)
    path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    caller = signing.verify_request(
        request.headers,
        request.method,
        path,
        b"",
        fp,
        srv.conn_nonces,
        scheme=signing.CONN,
        digest=digest,
    )
    if before_body is not None:
        before_body(caller)
    wait = srv.conn_limit.hit(keys.b64(caller.public))
    if wait:
        raise signing.Refused("limit", "Too many calls: try again in a moment.")
    body = await request.body()
    if hashlib.sha256(body).hexdigest() != digest:
        raise signing.Refused("bad-signature", "The body isn't the one the call signed.")
    return caller, body, protocol


async def verified(request: Request, status: bool = False) -> tuple[Connector, str, bytes, int]:
    """The paired connector a signed call comes from and which of its keys signed it, or a
    signed refusal, both before the body is read. The status key only where `status` allows
    it: it can say no more than that the connector is locked, or unpaired."""
    srv = request.app.state.server
    found: list = []

    def paired_key(caller: signing.Caller) -> None:
        with srv.db.read() as s:
            got = manage.by_key(s, caller.public)
        if got is None:
            raise signing.Refused("not-paired", "This server has no pairing with that connector.")
        if got[1] == "status" and not status:
            raise signing.Refused(
                "status-key", "Only the connector's action key makes this call: unlock it first."
            )
        found.append(got)

    _, body, protocol = await _signed(request, paired_key)
    row, which = found[0]
    return row, which, body, protocol


def guarded(route):
    """A fault in a route is answered with a signed `server-error`, never an unsigned 500 the
    connector can't tell from a forgery (protocol §7); it is logged here."""

    @functools.wraps(route)
    async def run(**kwargs):
        request = kwargs["request"]
        try:
            return await route(**kwargs)
        except Exception:
            log.exception("a connector call failed: %s", request.url.path)
            return refusal(
                request,
                signing.Refused("server-error", "MoolaKata failed on this call; it is logged."),
            )

    return run


@router.get("/hello")
def hello(request: Request):
    """Unsigned: the protocol this server speaks and its key's fingerprint, so a connector can
    check it against the pairing code before sending anything."""
    srv = request.app.state.server
    k, fp = own(srv)
    return {
        "protocol": PROTOCOL,
        "version": srv.version,
        "fingerprint": fp,
        "key": keys.b64(keys.raw_public(k.public_key())),
    }


@router.post("/pair")
@guarded
async def pair(request: Request):
    """The connector introduces itself with a pairing code, signed by its new action key,
    which the code vouches for (protocol §4.1)."""
    srv = request.app.state.server
    try:
        caller, body, protocol = await _signed(request)
    except signing.Refused as e:
        return refusal(request, e)
    out = manage.answer_pair(
        srv,
        caller.public,
        exactjson.loads(body or b"{}"),
        request.headers.get("mk-conn-version"),
        protocol,
    )
    if "error" in out:
        code, message = out["error"]
        return refusal(request, signing.Refused(code, message))
    return answer(srv, out, asked(request))


@router.post("/report")
@guarded
async def report(request: Request):
    srv = request.app.state.server
    try:
        row, which, body, protocol = await verified(request, status=True)
    except signing.Refused as e:
        return refusal(request, e)
    version = request.headers.get("mk-conn-version")
    address = request.client.host if request.client else None
    if which == "status":
        # The status key's report: locked, and nothing more is taken or told (S18.5).
        out = manage.apply_locked(srv, row, version, protocol, address)
    else:
        out = manage.apply_report(
            srv, row, exactjson.loads(body or b"{}"), version, protocol, address
        )
    srv.tasks.run_now("alerts")
    from .. import certs

    # This server's own certificate key, in every answer, so a key the connector hasn't pinned
    # is announced, signed, before it is in use (protocol §1.2).
    if key := certs.own_key(srv):
        out = {**out, "certificate": key}
    return answer(srv, out, asked(request))


@router.post("/connections/{connection_id}/credential/taken")
@guarded
async def credential_taken(connection_id: str, request: Request):
    srv = request.app.state.server
    try:
        row, _, body, _ = await verified(request)
    except signing.Refused as e:
        return refusal(request, e)
    at = exactjson.loads(body or b"{}").get("sealedAt")
    if not manage.credential_taken(srv, row, connection_id, at if isinstance(at, str) else None):
        return refusal(request, signing.Refused("not-found", "No such Connection."))
    return answer(srv, {"ok": True}, asked(request))


@router.post("/connections/{connection_id}/sign-in")
@guarded
async def sign_in(connection_id: str, request: Request):
    srv = request.app.state.server
    try:
        row, _, body, _ = await verified(request)
    except signing.Refused as e:
        return refusal(request, e)
    address = str(exactjson.loads(body or b"{}").get("address") or "")
    if not address.startswith("https://"):
        return refusal(request, signing.Refused("address-invalid", "The address must be https."))
    took = manage.sign_in_address(srv, row, connection_id, address)
    if took is None:
        return refusal(
            request,
            signing.Refused("address-invalid", "That isn't the institution's own sign-in page."),
        )
    if not took:
        return refusal(request, signing.Refused("not-found", "No such Connection."))
    srv.tasks.run_now("alerts")
    return answer(srv, {"ok": True}, asked(request))


@router.post("/unpaired")
@guarded
async def unpaired(request: Request):
    """`moolakata-connector unpair` on the connector's host: this side ends the pairing as
    Unpair would (S18.4.4). Either key may say so: a locked connector, or one reset because its
    words were lost, has only its status key."""
    srv = request.app.state.server
    try:
        await verified(request, status=True)
    except signing.Refused as e:
        return refusal(request, e)
    manage.unpair(srv, None, "unpaired-by-connector")
    return answer(srv, {"state": "ended"}, asked(request))


@router.post("/accounts/{account_id}/files")
@guarded
async def post_file(account_id: str, request: Request):
    """A driver's file for one account, through the same import as an upload (S18.8,
    protocol §4.4): multipart, one `file` part and a `meta` part."""
    from . import files

    srv = request.app.state.server
    try:
        row, _, body, _ = await verified(request)
    except signing.Refused as e:
        return refusal(request, e)
    if row.confirmedAt is None:
        return refusal(
            request,
            signing.Refused(
                "not-confirmed", "An admin has not confirmed the pairing yet (S18.4.3)."
            ),
        )
    try:
        data, meta = files.parts(request, body)
    except ValueError as e:
        return refusal(request, signing.Refused("file-refused", str(e)))
    connection_id = str(meta.get("connectionId") or "")
    with srv.db.read() as s:
        c = manage.connection_of(s, row, connection_id)
        a = s.scalars(
            select(Account).where(Account.id == account_id, Account.deleted == false())
        ).first()
        if c is None or a is None or a.connectionId != c.id or a.ownerId != c.ownerId:
            return refusal(
                request,
                signing.Refused(
                    "account-not-synced", "The account's sync doesn't name this Connection."
                ),
            )
    try:
        out = files.post(srv, c, a, data, meta)
    except files.Limit as e:
        return refusal(request, signing.Refused("limit", e.message), {"Retry-After": e.retry_after})
    except files.Refused as e:
        return refusal(request, signing.Refused(e.code, e.message))
    return answer(srv, out, asked(request))
