"""The /connector/v1 listener (requirements S18.4.3, docs/connector-protocol.md): what the
paired MoolaKata Connector calls. Everything but `hello` is signed by one of the connector's
keys: its action key, or, for a report that it is locked and `unpaired` only, its status key
(S18.4.2), checked by the gate before a byte of the body is read; every answer is signed back
by this server's link key (`links/gate.py`)."""

from fastapi import APIRouter, Request
from sqlalchemy import false, select

from ..links import keys, signing
from ..links.gate import Call, Gate, Kind
from ..links.routes import own
from ..store.entities.accounts import Account
from . import PROTOCOL, SUPPORTED, manage

KIND = Kind(
    scheme=signing.CONN,
    name="connector protocol",
    protocol=PROTOCOL,
    supported=tuple(SUPPORTED),
    nonces=lambda srv: srv.conn_nonces,
    limit=lambda srv: srv.conn_limit,
    unknown=lambda srv: srv.conn_unknown,
)
gate = Gate(KIND)
router = APIRouter(prefix="/connector/v1", include_in_schema=False)

# A pairing's body is a code and the connector's keys: a few kilobytes.
PAIR_BODY = 64 * 1024


def paired(status: bool = False):
    """The finder for a route only the paired connector calls, and which of its keys it signs
    with: the status key only where `status` allows it, since it can say no more than that the
    connector is locked, or unpaired (S18.4.2). Its calls count against that connector."""

    def find(srv, caller: signing.Caller):
        with srv.db.read() as s:
            got = manage.by_key(s, caller.public)
        if got is None:
            raise signing.Refused("not-paired", "This server has no pairing with that connector.")
        if got[1] == "status" and not status:
            raise signing.Refused(
                "status-key", "Only the connector's action key makes this call: unlock it first."
            )
        return got, keys.b64(caller.public)

    return find


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
@gate.route(max_body=PAIR_BODY)
def pair(call: Call):
    """The connector introduces itself with a pairing code, signed by its new action key,
    which the code vouches for (protocol §4.1)."""
    out = manage.answer_pair(
        call.srv, call.caller.public, call.json(), call.header("mk-conn-version"), call.protocol
    )
    if "error" in out:
        raise signing.Refused(*out["error"])
    return out


@router.post("/report")
@gate.route(paired(status=True))
def report(call: Call):
    srv, (row, which) = call.srv, call.found
    version = call.header("mk-conn-version")
    if which == "status":
        # The status key's report: locked, and nothing more is taken or told (S18.5).
        out = manage.apply_locked(srv, row, version, call.protocol, call.address)
    else:
        out = manage.apply_report(srv, row, call.json(), version, call.protocol, call.address)
    srv.tasks.run_now("alerts")
    from .. import certs

    # This server's own certificate key, in every answer, so a key the connector hasn't pinned
    # is announced, signed, before it is in use (protocol §1.2).
    if key := certs.own_key(srv):
        out = {**out, "certificate": key}
    return out


@router.post("/connections/{connection_id}/credential/taken")
@gate.route(paired())
def credential_taken(call: Call, connection_id: str):
    row, _ = call.found
    at = call.json().get("sealedAt")
    if not manage.credential_taken(
        call.srv, row, connection_id, at if isinstance(at, str) else None
    ):
        raise signing.Refused("not-found", "No such Connection.")
    return {"ok": True}


@router.post("/connections/{connection_id}/sign-in")
@gate.route(paired())
def sign_in(call: Call, connection_id: str):
    row, _ = call.found
    address = str(call.json().get("address") or "")
    if not address.startswith("https://"):
        raise signing.Refused("address-invalid", "The address must be https.")
    took = manage.sign_in_address(call.srv, row, connection_id, address)
    if took is None:
        raise signing.Refused("address-invalid", "That isn't the institution's own sign-in page.")
    if not took:
        raise signing.Refused("not-found", "No such Connection.")
    call.srv.tasks.run_now("alerts")
    return {"ok": True}


@router.post("/unpaired")
@gate.route(paired(status=True))
def unpaired(call: Call):
    """`moolakata-connector unpair` on the connector's host: this side ends the pairing as
    Unpair would (S18.4.4). Either key may say so: a locked connector, or one reset because its
    words were lost, has only its status key."""
    manage.unpair(call.srv, None, "unpaired-by-connector")
    return {"state": "ended"}


@router.post("/accounts/{account_id}/files")
@gate.route(paired())
def post_file(call: Call, account_id: str):
    """A driver's file for one account, through the same import as an upload (S18.8,
    protocol §4.4): multipart, one `file` part and a `meta` part."""
    from . import files

    srv, (row, _) = call.srv, call.found
    if row.confirmedAt is None:
        raise signing.Refused(
            "not-confirmed", "An admin has not confirmed the pairing yet (S18.4.3)."
        )
    try:
        data, meta = files.parts(call.request, call.body)
    except ValueError as e:
        raise signing.Refused("file-refused", str(e)) from None
    connection_id = str(meta.get("connectionId") or "")
    with srv.db.read() as s:
        c = manage.connection_of(s, row, connection_id)
        a = s.scalars(
            select(Account).where(Account.id == account_id, Account.deleted == false())
        ).first()
        if c is None or a is None or a.connectionId != c.id or a.ownerId != c.ownerId:
            raise signing.Refused(
                "account-not-synced", "The account's sync doesn't name this Connection."
            )
    try:
        return files.post(srv, c, a, data, meta)
    except files.Limit as e:
        raise signing.Refused("limit", e.message, float(e.retry_after)) from None
    except files.Refused as e:
        raise signing.Refused(e.code, e.message) from None
