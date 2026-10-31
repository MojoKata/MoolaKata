"""Calling a linked server (requirements S11.1.3, S11.2): signed requests over HTTPS through
the egress guard, TLS verified (a public certificate against the system's roots, a server's own
against the key pinned for it), and their signed answers checked against the call they answer."""

import json
import logging
import re
import time
from urllib.parse import urlsplit, urlunsplit

from .. import exactjson, net
from . import PROTOCOL, keys, signing

log = logging.getLogger("moolakata.links")

_CODE = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
# The refusals made before a call's signature could be checked, so unsigned (§7), by status.
UNSIGNED = {429: "limit", 503: "locked", 413: "too-large"}
# A peer's refusal in this server's own words, by its code (link-protocol.md §7).
REFUSALS = {
    "unsigned": "The other server says the call wasn't signed.",
    "clock-skew": "The other server says this server's time is more than a minute off.",
    "bad-signature": "The other server didn't accept this server's signature.",
    "replayed": "The other server says it has seen this call already.",
    "not-linked": "The other server has no link with this one.",
    "limit": "The other server is limiting calls; it is asked again later.",
    "locked": "The other server is locked; it is asked again at the next exchange.",
    "not-shared": "The other server shares no such file with this one.",
    "protocol-unsupported": "The other server doesn't answer this protocol.",
    "code-used": "The link code was used, has expired, or was withdrawn.",
    "already-linked": "The two servers are already linked.",
    "change-refused": "The other server refused a change this one sent.",
    "too-large": "The other server says the call is larger than it takes.",
    "server-error": "The other server failed on the call; its admin can read its log.",
}


def refusal(code: str, status: int, protocols=None) -> str:
    if code == "protocol-unsupported" and isinstance(protocols, list) and protocols:
        spoken = ", ".join(str(int(p)) for p in protocols if isinstance(p, int))
        return (
            f"The other server speaks link protocol {spoken}; this one speaks {PROTOCOL}. "
            "The older server needs updating."
        )
    if code.startswith("link-"):
        return f"The link is {code.removeprefix('link-')} on the other server."
    return REFUSALS.get(code, f"The other server refused the call ({code}, HTTP {status}).")


class LinkError(Exception):
    """The linked server couldn't be reached, or refused: the message says which."""

    def __init__(self, code: str, message: str, offered: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        # A certificate key the peer presented that isn't the one pinned for it.
        self.offered = offered


def checked_address(address: str) -> str:
    """A link address as S11.2 has it: `https`, a host, no query or fragment."""
    try:
        u = urlsplit((address or "").strip())
    except ValueError:
        u = None
    if u is None or u.scheme != "https" or not u.hostname or u.query or u.fragment:
        raise LinkError(
            "address-invalid", "A link address is https://, with a host and nothing after its path."
        )
    return urlunsplit((u.scheme, u.netloc, u.path.rstrip("/"), "", ""))


def _url(address: str, path: str) -> str:
    """The base's own path with the call's appended, never the two strings run together."""
    u = urlsplit(checked_address(address))
    return urlunsplit((u.scheme, u.netloc, u.path + path, "", ""))


def _client(srv, pins, max_bytes: int = net.MAX_RESPONSE) -> net.Client:
    return net.Client(srv.guard, max_bytes=max_bytes, pins=pins)


def _unreachable(address: str, e: Exception) -> LinkError:
    if isinstance(e, net.CertificateRefused):
        return LinkError(
            "certificate-changed",
            f"{address} presented a certificate key ({keys.short(e.fingerprint)}) other than "
            "the one this link was made with: its admin can read out the new one.",
            offered=e.fingerprint,
        )
    return LinkError("unreachable", f"{address} didn't answer ({type(e).__name__}).")


def _own(srv):
    return keys.signing_key(srv), keys.own_public(srv)[1]


def hello(srv, address: str, pins=None) -> dict:
    """The unsigned hello: the peer's protocol, version and fingerprint."""
    try:
        r = _client(srv, pins).get(_url(address, "/link/v1/hello"))
    except net.httpx.HTTPError as e:
        raise _unreachable(address, e) from None
    if r.status_code != 200:
        raise LinkError("not-moolakata", f"{address} doesn't answer as a MoolaKata server.")
    return r.json()


def call(
    srv,
    address: str,
    peer_key: bytes,
    path: str,
    data: dict | None = None,
    pins=None,
    seen: list | None = None,
) -> dict:
    """A signed POST to the peer, its answer checked against the peer's key and this call.
    `seen` gets the pinned certificate key the answer came over."""
    own, own_fp = _own(srv)
    body = exactjson.dumps(data or {}, separators=(",", ":")).encode()
    signed = signing.sign_request(own, "POST", path, body, keys.fingerprint(peer_key))
    headers = {
        **signed.headers,
        "MK-Link-Body-SHA256": signed.body_hash,
        "Content-Type": "application/json",
        "MK-Link-Protocol": str(PROTOCOL),
        "MK-Link-Version": srv.version,
    }
    try:
        with _client(srv, pins).stream(
            "POST", _url(address, path), content=body, headers=headers
        ) as r:
            # The answer's time is held to when it arrived, not to when its body was read
            # (link-protocol.md §3.3): a large change over a slow line is no clock problem.
            arrived = time.time()
            content = r.read()
    except net.httpx.HTTPError as e:
        raise _unreachable(address, e) from None
    if r.status_code in UNSIGNED and "mk-link-signature" not in r.headers:
        # Refused before the answering server could sign to the call: it limits calls, it is
        # locked, or the call is past its size; asked again later (link-protocol.md §7).
        code = UNSIGNED[r.status_code]
        raise LinkError(code, refusal(code, r.status_code))
    asked = signing.Asked(signed.nonce, own_fp, signed.body_hash)
    try:
        signing.verify_answer(peer_key, r.status_code, content, asked, r.headers, now=arrived)
    except signing.Refused as e:
        raise LinkError(e.code, e.message) from None
    if seen is not None and (key := net.presented(r)):
        seen.append(key)
    out = exactjson.loads(content) if content else {}
    if r.status_code >= 400:
        code = out.get("code")
        code = code if isinstance(code, str) and _CODE.match(code) else "refused"
        # The peer's own words go to the log only, never into an alert or email (S13.7.9).
        log.info("%s refused %s: %s %r", address, path, code, str(out.get("message", ""))[:200])
        raise LinkError(code, refusal(code, r.status_code, out.get("protocols")))
    return out


def iter_file(srv, address: str, peer_key: bytes, file_id: str, digest_out: list, pins=None):
    """One receipt's sealed bytes from the peer, piece by piece as they arrive. When the stream
    ends, the peer's signature over their SHA-256 is checked, and the digest appended to
    `digest_out`; a bad one raises before the last piece is taken as good. The answer is read
    up to the longest a receipt crosses as, not the 20 MB of a JSON answer (link-protocol.md
    §1.4)."""
    import hashlib

    from .sealed import max_receipt

    own, own_fp = _own(srv)
    path = "/link/v1/file"
    body = json.dumps({"id": file_id}, separators=(",", ":")).encode()
    signed = signing.sign_request(own, "POST", path, body, keys.fingerprint(peer_key))
    headers = {
        **signed.headers,
        "MK-Link-Body-SHA256": signed.body_hash,
        "Content-Type": "application/json",
        "MK-Link-Protocol": str(PROTOCOL),
        "MK-Link-Version": srv.version,
    }
    h = hashlib.sha256()
    try:
        c = _client(srv, pins, max_receipt())
        with c.stream("POST", _url(address, path), content=body, headers=headers) as r:
            # Its time is held to when it arrived: a receipt takes as long as the line needs.
            arrived = time.time()
            if r.status_code != 200:
                r.read()
                raise LinkError("file-refused", f"The file was refused ({r.status_code}).")
            for piece in r.iter_bytes():
                h.update(piece)
                yield piece
            answer_headers = r.headers
    except net.httpx.HTTPError as e:
        raise _unreachable(address, e) from None
    digest = h.hexdigest()
    asked = signing.Asked(signed.nonce, own_fp, signed.body_hash)
    try:
        signing.verify_answer(peer_key, 200, b"", asked, answer_headers, now=arrived, digest=digest)
    except signing.Refused as e:
        raise LinkError(e.code, e.message) from None
    digest_out.append(digest)


def send_file(srv, address: str, peer_key: bytes, file_id: str, path, digest: str, pins=None):
    """One receipt, sealed to the peer's copy key, sent ahead of the change that names it: its
    sealed bytes as the body, read from the file as they go (link-protocol.md §4.3)."""
    own, own_fp = _own(srv)
    call_path = "/link/v1/deliver"
    # Signed over the sealed bytes' hash in place of a body in hand.
    signed = signing.sign_request_digest(own, "POST", call_path, digest, keys.fingerprint(peer_key))
    headers = {
        **signed.headers,
        "MK-Link-Body-SHA256": digest,
        "Content-Type": "application/octet-stream",
        "MK-Link-File": file_id,
        "MK-Link-Protocol": str(PROTOCOL),
        "MK-Link-Version": srv.version,
    }

    def body():
        with open(path, "rb") as f:
            while chunk := f.read(1 << 16):
                yield chunk

    try:
        r = _client(srv, pins).post(_url(address, call_path), content=body(), headers=headers)
    except net.httpx.HTTPError as e:
        raise _unreachable(address, e) from None
    if r.status_code in UNSIGNED and "mk-link-signature" not in r.headers:
        code = UNSIGNED[r.status_code]
        raise LinkError(code, refusal(code, r.status_code))
    asked = signing.Asked(signed.nonce, own_fp, digest)
    try:
        signing.verify_answer(peer_key, r.status_code, r.content, asked, r.headers)
    except signing.Refused as e:
        raise LinkError(e.code, e.message) from None
    if r.status_code >= 400:
        out = exactjson.loads(r.content) if r.content else {}
        raise LinkError(out.get("code", "refused"), out.get("message", "the file was refused"))
