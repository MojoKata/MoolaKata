"""Pairing, reports, credentials and file posts (requirements S18.4–S18.8,
docs/connector-protocol.md). One connector is paired at a time; its reports keep each
Connection's state, and its posts go through the same import as an upload."""

import datetime as dt
import hashlib
import json
import secrets
from urllib.parse import urlsplit

from sqlalchemy import false, select

from .. import activity, clock, ids, settings
from ..links import keys
from ..store.entities.accounts import Account
from ..store.entities.connector import Connection, Connector
from ..store.entities.users import User

CODE_HOURS = 24
SILENT_MINUTES = 15  # not heard from for this long: the alert of S18.5.2
VIA = "MoolaKata Connector"


class ConnectorError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def encode_code(address: str, fp: str, secret: str, cert: str | None = None) -> str:
    """A pairing code (protocol §4.1); `t`, this server's certificate key, only when the
    certificate is its own, for the connector to pin."""
    body = {"a": address, "f": fp, "c": secret, **({"t": cert} if cert else {})}
    raw = json.dumps(body, separators=(",", ":")).encode()
    return "mkp1." + keys.b64(raw)


def decode_code(code: str) -> dict:
    code = "".join(code.split())
    if not code.startswith("mkp1."):
        raise ConnectorError("code-invalid", "That isn't a pairing code: it starts mkp1.")
    try:
        out = json.loads(keys.unb64(code[5:]))
        assert isinstance(out, dict) and {"a", "f", "c"} <= set(out)
    except ValueError, AssertionError:
        raise ConnectorError(
            "code-invalid", "The pairing code is damaged: copy it whole."
        ) from None
    return out


def current(s) -> Connector | None:
    """The connector paired now, or the pairing that waits for its code to be used."""
    return s.scalars(
        select(Connector)
        .where(Connector.deleted == false(), Connector.state.in_(("paired", "pairing")))
        .order_by(Connector.createdAt.desc())
    ).first()


def paired(s) -> Connector | None:
    return s.scalars(
        select(Connector).where(Connector.deleted == false(), Connector.state == "paired")
    ).first()


def own_address(s) -> str | None:
    """The address a pairing code carries (S18.4.1): Settings › Connector's own, else the
    public URL."""
    return settings.get(s, "connectorAddress") or settings.get(s, "publicUrl")


def pair_code(srv, by: str) -> tuple[Connector, str]:
    """Settings › Connector › Pair (S18.4.1): a code shown once, valid 24 hours. A code already
    out is withdrawn by the new one."""
    from .. import certs

    cert = certs.own_key(srv)
    with srv.db.tx() as s:
        address = own_address(s)
        if not address:
            raise ConnectorError(
                "no-address",
                "Set the address the connector reaches this server at (Settings › Connector), or "
                "the public URL, first.",
            )
        own = keys.private_key(s, srv.keys.secrets, by)
        fp = keys.fingerprint(keys.raw_public(own.public_key()))
        for old in s.scalars(
            select(Connector).where(Connector.deleted == false(), Connector.state == "pairing")
        ):
            old.state = "ended"
            old.endedAt = clock.now()
            old.endedById = by
        secret = secrets.token_urlsafe(24)
        row = Connector(
            id=ids.new_id("Cnctr"),
            state="pairing",
            codeHash=_hash(secret),
            codeExpiresAt=clock.now() + dt.timedelta(hours=CODE_HOURS),
            pairedById=by,
        )
        s.add(row)
        activity.record(s, "connector.pairing", actor=by, for_admins=True)
        s.flush()
        return row, encode_code(address, fp, secret, cert)


def _end(s, row: Connector, by: str | None, reason: str) -> None:
    """Unpair (S18.4.4), or a replaced pairing: every Connection stops and every account's sync
    turns off."""
    row.state = "ended"
    row.endedAt = clock.now()
    row.endedById = by
    for c in s.scalars(
        select(Connection).where(Connection.connectorId == row.id, Connection.deleted == false())
    ):
        c.state = "removed"
        c.removedAt = clock.now()
        c.sealedCredential = None
        c.sealedAt = None
        for a in s.scalars(select(Account).where(Account.connectionId == c.id)):
            a.connectionId = None
            a.syncAccount = None
    activity.record(s, f"connector.{reason}", actor=by, for_admins=True)


# What a pairing's keys sign of one another (S18.4.2, S18.4.5): the action key signs the
# sealing key, so a browser seals only to the key of the connector an admin confirmed, and the
# status key; the status key signs the action key. So both are known to be one connector's.
SEALING_LABEL = b"moolakata connector sealing key\x00"
STATUS_LABEL = b"moolakata connector status key\x00"
ACTION_LABEL = b"moolakata connector action key\x00"


def signed_by(signer: bytes, label: bytes, key: bytes, signature: bytes) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        Ed25519PublicKey.from_public_bytes(signer).verify(signature, label + key)
    except InvalidSignature, ValueError:
        return False
    return True


def _key_field(body: dict, name: str, size: int) -> bytes:
    raw = keys.unb64(str(body.get(name) or ""))
    if len(raw) != size:
        raise ValueError(name)
    return raw


def answer_pair(srv, caller_public: bytes, body: dict, version: str | None, protocol: int | None):
    """The connector introduces itself with the code (S18.4.2), the call signed by its new
    action key: the code's secret must match the hash kept, within its time; the keys, each
    signed by the other, are then recorded, and a connector paired before is replaced as Unpair
    would."""
    try:
        c = decode_code(str(body.get("code") or ""))
        sealing = _key_field(body, "sealingKey", 32)
        status = _key_field(body, "statusKey", 32)
    except ConnectorError, ValueError:
        return {"error": ("code-used", "The pairing code was used, expired or withdrawn.")}
    signatures = {}
    for name in ("sealingSignature", "statusSignature", "actionSignature"):
        try:
            signatures[name] = keys.unb64(str(body.get(name) or ""))
        except ValueError:
            signatures[name] = b""
    if not signed_by(caller_public, SEALING_LABEL, sealing, signatures["sealingSignature"]):
        return {
            "error": (
                "sealing-unsigned",
                "The sealing key isn't signed by the connector's action key: update it.",
            )
        }
    if status == caller_public or not (
        signed_by(caller_public, STATUS_LABEL, status, signatures["statusSignature"])
        and signed_by(status, ACTION_LABEL, caller_public, signatures["actionSignature"])
    ):
        return {
            "error": (
                "keys-unsigned",
                "The status and action keys don't sign each other: update the connector.",
            )
        }
    now = clock.now()
    with srv.db.tx() as s:
        row = s.scalars(
            select(Connector).where(
                Connector.deleted == false(),
                Connector.state == "pairing",
                Connector.codeHash == _hash(c["c"]),
            )
        ).first()
        if row is None or row.codeExpiresAt is None or row.codeExpiresAt < now:
            return {"error": ("code-used", "The pairing code was used, expired or withdrawn.")}
        for old in s.scalars(
            select(Connector).where(Connector.deleted == false(), Connector.state == "paired")
        ):
            _end(s, old, row.pairedById, "replaced")
        row.state = "paired"
        row.codeHash = None
        row.codeExpiresAt = None
        row.actionKey = keys.b64(caller_public)
        row.statusKey = keys.b64(status)
        row.sealingKey = keys.b64(sealing)
        row.sealingSignature = keys.b64(signatures["sealingSignature"])
        row.pairedAt = now
        row.lastReportAt = now
        row.connectorVersion = version
        row.protocol = protocol
        activity.record(
            s,
            "connector.paired",
            actor=row.pairedById,
            for_admins=True,
            detail={"fingerprint": keys.short(keys.fingerprint(caller_public))},
        )
        own = keys.private_key(s, srv.keys.secrets)
        return {
            "fingerprint": keys.fingerprint(keys.raw_public(own.public_key())),
            "connectorFingerprint": keys.fingerprint(caller_public),
            "serverName": settings.get(s, "serverName"),
        }


def confirm(srv, by: str) -> bool:
    """Settings › Connector › Confirm (S18.4.3): an admin compared the fingerprints. Only then
    are sealed credentials handed over and files taken."""
    with srv.db.tx() as s:
        row = paired(s)
        if row is None:
            return False
        if row.confirmedAt is None:
            row.confirmedAt = clock.now()
            row.confirmedById = by
            activity.record(s, "connector.confirmed", actor=by, for_admins=True)
        return True


def accept_address(srv, by: str) -> bool:
    """Settings › Connector › Accept: the address the connector now reports from is its own
    (S18.2.4.4)."""
    with srv.db.tx() as s:
        row = paired(s)
        if row is None:
            return False
        accepted = row.newAddress or row.lastAddress
        row.knownAddress, row.newAddress = accepted, None
        activity.record(
            s,
            "connector.address-accepted",
            actor=by,
            for_admins=True,
            detail={"to": accepted},
        )
        return True


def unpair(srv, by: str | None, reason: str = "unpaired") -> bool:
    """Settings › Connector › Unpair, or the connector's own `unpaired` call: the paired
    connector ends, and so does any code still out, which a thief could otherwise use
    (S18.4.4)."""
    with srv.db.tx() as s:
        rows = list(
            s.scalars(
                select(Connector).where(
                    Connector.deleted == false(), Connector.state.in_(("paired", "pairing"))
                )
            )
        )
        if not rows:
            return False
        for row in rows:
            row.newAddress = None
            _end(s, row, by, reason)
        return True


def by_key(s, public: bytes) -> tuple[Connector, str] | None:
    """The paired connector a key is one of, and which: `action` or `status` (S18.4.2)."""
    key = keys.b64(public)
    row = s.scalars(
        select(Connector).where(
            Connector.deleted == false(),
            Connector.state == "paired",
            (Connector.actionKey == key) | (Connector.statusKey == key),
        )
    ).first()
    if row is None:
        return None
    return row, "action" if row.actionKey == key else "status"


STATES = ("new", "ok", "needs-sign-in", "failing")


def _accounts_of(s, c: Connection) -> list[dict]:
    out = []
    for a in s.scalars(
        select(Account).where(Account.connectionId == c.id, Account.deleted == false())
    ):
        out.append(
            {"id": a.id, "syncAccount": a.syncAccount, "formats": ["ofx", "csv", "statement"]}
        )
    return out


def apply_report(
    srv,
    row: Connector,
    body: dict,
    version: str | None,
    protocol: int | None,
    address: str | None = None,
):
    """A report (S18.5, protocol §4.2): what the connector says of itself and each Connection,
    answered with what waits for it. Nothing in a report is a credential, an amount or an
    account number beyond its last four digits: what it says is kept as its words."""
    with srv.db.tx() as s:
        row = s.get(Connector, row.id)
        _heard(s, row, version, protocol, address)
        row.locked = bool(body.get("locked", False))
        row.pageAddress = _page(body.get("page"))
        # Removed Connections (deleted here, S18.6.4) are listed so the connector deletes
        # their credentials, until it has reported without them once.
        mine = {
            c.id: c for c in s.scalars(select(Connection).where(Connection.connectorId == row.id))
        }
        for rep in body.get("connections") or []:
            if not isinstance(rep, dict):
                continue
            c = mine.get(str(rep.get("id") or ""))
            if c is None or c.deleted or c.state == "removed":
                continue
            state = rep.get("state")
            if state in STATES:
                c.state = state
            c.message = _short(rep.get("message"))
            c.lastRunAt = _when(rep.get("lastRunAt")) or c.lastRunAt
            added = rep.get("lastRunAdded")
            c.lastRunAdded = (
                added if isinstance(added, int) and not isinstance(added, bool) else None
            )
            found = rep.get("institutionAccounts")
            if isinstance(found, list):
                c.institutionAccounts = json.dumps(
                    [
                        {"name": _short(x.get("name")) or "", "last4": _last4(x.get("last4"))}
                        for x in found
                        if isinstance(x, dict)
                    ][:50]
                )
            # Held to the driver's own sign-in page, as the sign-in call is: a report is no
            # way round that check (S18.7.1).
            address = rep.get("signInAddress")
            c.signInAddress = (
                address
                if isinstance(address, str)
                and len(address) < 2000
                and sign_in_allowed(c.driver, address)
                else None
            )
        live = []
        removed = []
        for c in mine.values():
            if c.deleted or c.state == "removed":
                removed.append(c.id)
                continue
            owner = s.get(User, c.ownerId)
            live.append(
                {
                    "id": c.id,
                    "ownerName": owner.displayName if owner else "?",
                    "driver": c.driver,
                    "label": c.label,
                    "settings": json.loads(c.settings or "{}"),
                    "accounts": _accounts_of(s, c),
                    # A box opens only with the sealing key in the connector's vault, so it
                    # is handed over only to a connector that reports unlocked, and only
                    # once an admin confirmed the pairing (protocol §4.2, S18.4.3).
                    "sealed": (
                        {"ciphertext": c.sealedCredential, "sealedAt": c.sealedAt.isoformat()}
                        if c.sealedCredential and not row.locked and row.confirmedAt
                        else None
                    ),
                }
            )
        # Whether an admin confirmed the pairing, which its page shows (S18.11.3).
        return {"connections": live, "removed": removed, "confirmed": row.confirmedAt is not None}


def _heard(s, row: Connector, version: str | None, protocol: int | None, address: str | None):
    """What any report tells, under either key: when, what it runs, and where from."""
    row.lastReportAt = clock.now()
    row.connectorVersion = version
    row.protocol = protocol
    if address and address != row.lastAddress:
        # A report from somewhere new (S18.2.4.4): the first address is taken as known; a later
        # change is alerted until an admin accepts it.
        if row.lastAddress is None and row.knownAddress is None:
            row.knownAddress = address
        elif address != row.knownAddress:
            row.newAddress = address  # kept until accepted or unpaired
            activity.record(
                s,
                "connector.address-changed",
                actor=None,
                for_admins=True,
                detail={"from": row.lastAddress, "to": address},
            )
        row.lastAddress = address


def apply_locked(
    srv, row: Connector, version: str | None, protocol: int | None, address: str | None = None
) -> dict:
    """A report under the status key (S18.5): the connector is locked, and nothing else is
    taken from it; the answer acknowledges it and carries nothing about a Connection, an owner
    or an account, since a copy of the connector's volume holds this key (S18.2.4.4)."""
    with srv.db.tx() as s:
        row = s.get(Connector, row.id)
        _heard(s, row, version, protocol, address)
        row.locked = True
    return {"ok": True}


def _short(v) -> str | None:
    return v.strip()[:200] if isinstance(v, str) and v.strip() else None


def _page(v) -> str | None:
    """The connector's page as it reports it (S18.11.1): an https address of a host and
    port, nothing more, since Settings › Connector links to it."""
    if not isinstance(v, str) or len(v) > 300:
        return None
    try:
        u = urlsplit(v.strip())
        u.port  # noqa: B018 - a port that isn't a number raises here
    except ValueError:
        return None
    if u.scheme != "https" or not u.hostname or u.username or u.password:
        return None
    if u.path not in ("", "/") or u.query or u.fragment:
        return None
    return f"https://{u.netloc}"


def _last4(v) -> str | None:
    v = str(v or "").strip()
    return v[-4:] if v.isdigit() and len(v) >= 4 else None


def _when(v) -> dt.datetime | None:
    try:
        t = dt.datetime.fromisoformat(v) if isinstance(v, str) else None
    except ValueError:
        return None
    return t if t is None or t.tzinfo else t.replace(tzinfo=dt.UTC)


def connection_of(s, row: Connector, connection_id: str) -> Connection | None:
    c = s.get(Connection, connection_id)
    if c is None or c.deleted or c.connectorId != row.id or c.state == "removed":
        return None
    return c


def credential_taken(srv, row: Connector, connection_id: str, at: str | None = None) -> bool:
    """The connector filed the sealed credential in its vault: MoolaKata deletes its copy
    (S18.7.1); the Connection waits for its first run. The call names the box taken by when
    it was sealed (protocol §4.3.2): a newer one sealed since stays for the next report."""
    with srv.db.tx() as s:
        c = connection_of(s, row, connection_id)
        if c is None:
            return False
        if c.sealedAt is not None and at != c.sealedAt.isoformat():
            return True  # another box waits now; this one was already replaced
        c.sealedCredential = None
        c.sealedAt = None
        c.signInAddress = None
        if c.state in ("new", "needs-sign-in"):
            c.state = "ok"
            c.message = "credentials received"
        return True


# The only sign-in pages a driver may send its owner to (S18.7.1): its institution's own
# OAuth page, so a connector that isn't ours can't phish a password with "Open Schwab's
# sign-in".
SIGN_IN_PAGES = {"schwab": ("api.schwabapi.com", "/v1/oauth/authorize")}


def sign_in_allowed(driver: str, address: str) -> bool:
    from urllib.parse import urlsplit

    page = SIGN_IN_PAGES.get(driver)
    u = urlsplit(address)
    return page is not None and u.scheme == "https" and (u.hostname, u.path) == page


def sign_in_address(srv, row: Connector, connection_id: str, address: str) -> bool | None:
    """A driver needs the owner to sign in at the institution's page (S18.7.1): the address is
    shown to the owner under Profile › Connections. None when it isn't the driver's own page."""
    with srv.db.tx() as s:
        c = connection_of(s, row, connection_id)
        if c is None:
            return False
        if not sign_in_allowed(c.driver, address):
            return None
        c.signInAddress = address[:2000]
        c.state = "needs-sign-in"
        c.message = "sign in at the institution's page"
        return True


def silent_for(row: Connector, now: dt.datetime | None = None) -> dt.timedelta | None:
    """How long since the connector last reported, past the 15 minutes allowed."""
    if row.state != "paired" or row.lastReportAt is None:
        return None
    gap = (now or clock.now()) - row.lastReportAt
    return gap if gap > dt.timedelta(minutes=SILENT_MINUTES) else None
