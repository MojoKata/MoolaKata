"""Calls out (requirements S18.2.2, S18.1.1): the connector only opens connections, to
MoolaKata and to each driver's declared hosts, through one egress allowlist that refuses any
other host. The standard library's HTTPS client, TLS always verified before anything is sent:
a public certificate against the system's roots, and MoolaKata's own against the key its
pairing code pinned (protocol §1.2). The signature on each answer proves who wrote it."""

import contextlib
import hashlib
import http.client
import ipaddress
import json
import os
import socket
import ssl
import threading
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from . import PROTOCOL, VERSION, signing
from .keys import Pairing, unb64


class EgressRefused(Exception):
    pass


MAX_ANSWER = 25 * 1024 * 1024  # what one answer may hold (S18.1.2)
DEADLINE = 60  # seconds a whole call may take, an answer that trickles in included (S18.2.2)
LOOPBACK_OK = os.environ.get("MOOLAKATA_CONNECTOR_DEV") == "1"  # a dev MoolaKata on localhost


# Cloud metadata services, as MoolaKata's guard names them (S13.5): AWS's IPv6 one is a
# unique local address, not link-local, so it is named.
METADATA = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("fd00:ec2::254"),
    ipaddress.ip_address("100.100.100.200"),
}


def vetted(host: str, port: int) -> str:
    """The address to connect to, resolved once: cloud metadata, loopback, link-local,
    multicast, reserved and unspecified addresses are refused, as MoolaKata's guard does
    (S13.5), and the connection goes to the address checked, never a second lookup's."""
    addr = None
    for *_, sa in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        ip = ipaddress.ip_address(sa[0])
        ip = ip.ipv4_mapped or ip if ip.version == 6 else ip
        if ip in METADATA or (ip.is_loopback and not LOOPBACK_OK) or ip.is_link_local:
            raise EgressRefused(f"{host} resolves to {ip}, an address the connector never calls")
        if ip.is_unspecified or ip.is_multicast or ip.is_reserved:
            raise EgressRefused(f"{host} resolves to {ip}, not a host address")
        addr = addr or sa[0]
    if addr is None:
        raise EgressRefused(f"{host} doesn't resolve")
    return addr


@dataclass
class Egress:
    """The hosts that may be reached: MoolaKata's for the connector's own calls, and for each
    driver's run only the hosts that driver declared (S18.1.2)."""

    allowed: set[str] = field(default_factory=set)

    def allow(self, *hosts: str) -> None:
        self.allowed |= {h.lower() for h in hosts if h}

    def check(self, host: str) -> None:
        if host.lower() not in self.allowed:
            raise EgressRefused(f"{host} is not a host this connector may reach")


@dataclass
class Answer:
    status: int
    headers: dict
    body: bytes
    cert: str | None = None  # the pinned certificate key it came over

    def json(self) -> dict:
        return json.loads(self.body) if self.body else {}


class CertificateRefused(Exception):
    def __init__(self, fingerprint: str):
        super().__init__(
            f"MoolaKata's certificate key {fingerprint[:16]} isn't the one this pairing pinned: "
            "pair again, or wait for the server to announce it"
        )
        self.fingerprint = fingerprint


def key_fingerprint(der: bytes) -> str:
    """A certificate's key, as pinned: the SHA-256 of its SubjectPublicKeyInfo, in hex."""
    key = x509.load_der_x509_certificate(der).public_key()
    return hashlib.sha256(
        key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    ).hexdigest()


class Transport:
    """One HTTPS request, its TLS verified before anything is sent: against the system's roots
    and the name, or, with `pins`, against the certificate keys pinned for that server."""

    def __init__(self, egress: Egress):
        self.egress = egress

    def with_egress(self, egress: Egress) -> Transport:
        """The same transport held to another allowlist: one driver run's."""
        import copy

        other = copy.copy(self)
        other.egress = egress
        return other

    def request(self, method: str, url: str, headers: dict, body: bytes, pins=None) -> Answer:
        u = urlsplit(url)
        host = u.hostname or ""
        self.egress.check(host)
        if u.scheme != "https":
            raise EgressRefused(f"{url} is not https")
        ctx = ssl.create_default_context()
        if pins is not None:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        port = u.port or 443
        conn = http.client.HTTPSConnection(host, port, timeout=DEADLINE, context=ctx)
        # The socket's timeout bounds each read; the whole call is bounded by closing the
        # socket at its deadline, so an answer of a byte a minute ends too.
        ended = threading.Event()
        live: list[socket.socket] = []  # the socket now in use: the TCP one, then the TLS one

        def end() -> None:
            ended.set()
            for s in live[-1:]:
                with contextlib.suppress(OSError):
                    s.shutdown(socket.SHUT_RDWR)

        timer = threading.Timer(DEADLINE, end)
        timer.daemon = True
        timer.start()
        try:
            live.append(socket.create_connection((vetted(host, port), port), timeout=DEADLINE))
            if ended.is_set():
                end()
            conn.sock = ctx.wrap_socket(live[0], server_hostname=host)
            live.append(conn.sock)
            if ended.is_set():
                end()
            cert = None
            if pins is not None:
                cert = key_fingerprint(conn.sock.getpeercert(binary_form=True) or b"")
                if cert not in pins:
                    raise CertificateRefused(cert)
            path = u.path + (f"?{u.query}" if u.query else "")
            conn.request(method, path, body=body, headers=headers)
            r = conn.getresponse()
            body = r.read(MAX_ANSWER + 1)
            if ended.is_set():
                raise TimeoutError(f"{host} took longer than {DEADLINE} seconds")
            if len(body) > MAX_ANSWER:
                raise EgressRefused(f"{host} answered more than 25 MB")
            return Answer(r.status, {k: v for k, v in r.getheaders()}, body, cert)
        except OSError, http.client.HTTPException:
            if ended.is_set():
                raise TimeoutError(f"{host} took longer than {DEADLINE} seconds") from None
            raise
        finally:
            timer.cancel()
            conn.close()


class ServerError(Exception):
    def __init__(self, code: str, message: str, status: int = 0, retry_after: int = 0):
        super().__init__(message)
        self.code, self.message, self.status, self.retry_after = code, message, status, retry_after


class Server:
    """MoolaKata, as the connector calls it: signed calls, signed answers."""

    def __init__(self, pairing: Pairing, transport: Transport, server_public: bytes, on_cert=None):
        self.pairing = pairing
        self.transport = transport
        self.server_public = server_public
        # Called with (pinned, next) when the server announces its next certificate key, or
        # starts using the one it announced, so the pairing keeps them (protocol §1.2).
        self.on_cert = on_cert

    def call(self, path: str, data: dict | None = None, body: bytes | None = None, ctype=None):
        payload = body if body is not None else json.dumps(data or {}).encode()
        headers, nonce = signing.sign(
            self.pairing.identity, "POST", path, payload, self.pairing.server_fp
        )
        headers |= {
            "Content-Type": ctype or "application/json",
            "MK-Conn-Protocol": str(PROTOCOL),
            "MK-Conn-Version": VERSION,
        }
        p, url = self.pairing, self.pairing.address.rstrip("/") + path
        try:
            r = self.transport.request("POST", url, headers, payload, pins=p.pins())
        except CertificateRefused as e:
            raise ServerError("certificate-changed", str(e)) from None
        call = signing.body_hash(payload)
        signing.verify_answer(
            self.server_public, r.status, r.body, nonce, r.headers, p.fingerprint, call
        )
        if r.cert is not None and r.cert == p.cert_next and self.on_cert:
            self.on_cert(r.cert, None)  # the announced key is in use now
        out = r.json()
        new = out.get("certificate") if isinstance(out, dict) else None
        if p.cert and isinstance(new, str) and new not in (p.cert, p.cert_next) and self.on_cert:
            self.on_cert(p.cert, new)
        if r.status >= 400:
            retry = r.headers.get("Retry-After") or r.headers.get("retry-after") or "0"
            raise ServerError(
                out.get("code", "refused"),
                out.get("message", f"refused ({r.status})"),
                r.status,
                int(retry) if retry.isdigit() else 0,
            )
        return out


def hello(transport: Transport, address: str, pins=None) -> dict:
    try:
        r = transport.request(
            "GET", address.rstrip("/") + "/connector/v1/hello", {}, b"", pins=pins
        )
    except CertificateRefused as e:
        raise ServerError("certificate-changed", str(e)) from None
    if r.status != 200:
        raise ServerError("not-moolakata", f"{address} doesn't answer as a MoolaKata server.")
    return r.json()


def server_key(hello_answer: dict) -> bytes:
    return unb64(hello_answer["key"])
