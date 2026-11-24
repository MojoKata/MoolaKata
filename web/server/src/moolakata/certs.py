"""This server's own TLS certificate (requirements S11.1.3, S18.4, S13.3): when it is its own
rather than a public one, the fingerprint of its key, which link and pairing codes carry so
that peers and the connector pin it, and which is announced to them, signed, when it changes.

It is read by connecting to this server's own address through the egress guard (S13.5), the
one peers or the connector will connect to: one that the system's roots verify for its name is
public, and needs no pin. When that address can't be reached, a server that serves TLS itself
(`tls` mode) reads its listener's certificate from its file; one behind a proxy can't be
read."""

import datetime as dt
import logging
import ssl
import threading
from typing import Literal
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding

from . import clock, net

log = logging.getLogger("moolakata.certs")
CACHE_SECONDS = 600

# Whose address the certificate is read at: a linked server's or the connector's.
Use = Literal["link", "connector"]

_lock = threading.Lock()
_cached: dict[str, tuple[dt.datetime, str | Unread | None]] = {}


def _from_file(path) -> str | None:
    """The listener's certificate: a public one needs no pin. Unread when it can't be read."""
    try:
        cert = x509.load_pem_x509_certificate(path.read_bytes())
    except (OSError, ValueError) as e:
        log.warning("the certificate %s can't be read: %s", path, e)
        raise Unread from None
    der = cert.public_bytes(Encoding.DER)
    if cert.issuer != cert.subject and _public_by_name(cert):
        return None
    return net.key_fingerprint(der)


def _public_by_name(cert) -> bool:
    """Whether the system's roots vouch for this certificate, which isn't self-signed."""
    try:
        from cryptography.x509 import DNSName
        from cryptography.x509.verification import PolicyBuilder, Store

        paths = ssl.get_default_verify_paths()
        with open(paths.cafile or paths.openssl_cafile, "rb") as f:
            bundle = f.read()
        store = Store(x509.load_pem_x509_certificates(bundle))
        names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        dns = names.get_values_for_type(DNSName)
        if not dns:
            return False
        PolicyBuilder().store(store).build_server_verifier(DNSName(dns[0])).verify(cert, [])
        return True
    except Exception:  # anything short of a verified chain is not public
        return False


class Unread(Exception):
    """This server's own certificate couldn't be read, at its link address or from its file:
    not the same as a public one, which needs no pin."""


# Why no invitation or pairing code is made meanwhile (S11.1.3, S18.4.1): it would carry no
# key for the peer or the connector to pin.
UNREAD = (
    "This server can't read its own certificate at its link address: check the link address in "
    "Settings › Linked Servers."
)


def _verify_failed(e: BaseException | None) -> bool:
    while e is not None:
        if isinstance(e, ssl.SSLCertVerificationError):
            return True
        e = e.__cause__ or e.__context__
    return False


def _probe(guard: net.Guard, address: str) -> str | None:
    """The certificate presented at this server's own link address, by its key; None when the
    system's roots verify it for its name. Read as any outbound call is, through the guard and
    to the address it checked (S13.5); Unread when it can't be reached or the guard refuses
    it."""
    u = urlsplit(address or "")
    if u.scheme != "https" or not u.hostname:
        return None
    try:
        with net.Client(guard, use="link") as c:
            c.head(address, timeout=5)
        return None  # public
    except net.httpx.HTTPError as e:
        if not _verify_failed(e):
            log.info(
                "this server's own link address %s can't be read for its certificate: %s",
                address,
                type(e).__name__,
            )
            raise Unread from None
    # Its own: the key, read in a handshake held to no pin, so nothing is sent.
    try:
        with net.Client(guard, use="link", pins=()) as c:
            c.head(address, timeout=5)
    except net.CertificateRefused as e:
        if e.fingerprint:
            return e.fingerprint
    except net.httpx.HTTPError:
        pass
    raise Unread


def own_key(srv, use: Use = "link") -> str | None:
    """The fingerprint of this server's own certificate's key, or None when it is public or
    can't be read."""
    try:
        return own_key_read(srv, use)
    except Unread:
        return None


def own_key_read(srv, use: Use = "link") -> str | None:
    """The fingerprint of this server's own certificate's key, or None when it is public;
    Unread when it can't be read.

    It is read first at the address the code carries, where the peer will connect: the link
    address for a link (S11.1.1), the connector address for the connector (S18.4.1), whose
    proxy may differ. When that can't be reached (a router with no NAT hairpinning) and this
    server serves TLS itself, the certificate is its listener's, from the file it loads; behind
    a proxy that terminates TLS there is nowhere else to read it."""
    if use == "connector":
        from .connector.manage import own_address
    else:
        from .links.manage import own_address

    with srv.db.read(unscoped="certs: own key") as s:
        address = own_address(s) or ""
    try:
        return _at(srv.guard, address)
    except Unread:
        config = srv.config
        if config.mode != "tls":
            raise
        return _from_file(config.tls_cert or config.tls_dir / "self-signed.crt")


def _at(guard: net.Guard, address: str) -> str | None:
    """The probe of an address, kept CACHE_SECONDS, an Unread among them."""
    now = clock.now()
    with _lock:
        hit = _cached.get(address)
    if hit is None or (now - hit[0]).total_seconds() >= CACHE_SECONDS:
        try:
            fp: str | Unread | None = _probe(guard, address)
        except Unread as e:
            fp = e
        hit = (now, fp)
        with _lock:
            _cached[address] = hit
    if isinstance(hit[1], Unread):
        raise Unread
    return hit[1]
