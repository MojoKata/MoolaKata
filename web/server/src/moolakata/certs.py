"""This server's own TLS certificate (requirements S11.1.3, S18.4, S13.3): when it is its own
rather than a public one, the fingerprint of its key, which link and pairing codes carry so
that peers and the connector pin it, and which is announced to them, signed, when it changes.

In `tls` mode the certificate is the listener's, read from its file. Behind a proxy it is the
proxy's, read by connecting to this server's own link address through the egress guard
(S13.5): one that the system's roots verify for its name is public, and needs no pin."""

import datetime as dt
import logging
import ssl
import threading
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding

from . import clock, net

log = logging.getLogger("moolakata.certs")
CACHE_SECONDS = 600

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
UNREAD = "This server can't read its own certificate at its link address: check Settings › Network."


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


def own_key(srv) -> str | None:
    """The fingerprint of this server's own certificate's key, or None when it is public or
    can't be read."""
    try:
        return own_key_read(srv)
    except Unread:
        return None


def own_key_read(srv) -> str | None:
    """The fingerprint of this server's own certificate's key, or None when it is public;
    Unread when it can't be read."""
    config = srv.config
    if config.mode == "tls":
        path = config.tls_cert or config.tls_dir / "self-signed.crt"
        return _from_file(path)
    from .links.manage import own_address

    with srv.db.read(unscoped="certs: own key") as s:
        address = own_address(s) or ""
    now = clock.now()
    with _lock:
        hit = _cached.get(address)
    if hit is None or (now - hit[0]).total_seconds() >= CACHE_SECONDS:
        try:
            fp: str | Unread | None = _probe(srv.guard, address)
        except Unread as e:
            fp = e
        hit = (now, fp)
        with _lock:
            _cached[address] = hit
    if isinstance(hit[1], Unread):
        raise Unread
    return hit[1]
