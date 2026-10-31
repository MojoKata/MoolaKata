"""This server's own TLS certificate (requirements S11.1.3, S18.4, S13.3): when it is its own
rather than a public one, the fingerprint of its key, which link and pairing codes carry so
that peers and the connector pin it, and which is announced to them, signed, when it changes.

In `tls` mode the certificate is the listener's, read from its file. Behind a proxy it is the
proxy's, read by connecting to this server's own link address: one that the system's roots
verify for its name is public, and needs no pin."""

import datetime as dt
import logging
import socket
import ssl
import threading
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding

from . import clock, net

log = logging.getLogger("moolakata.certs")
CACHE_SECONDS = 600

_lock = threading.Lock()
_cached: dict[str, tuple[dt.datetime, str | None]] = {}


def _from_file(path) -> str | None:
    """The listener's certificate: a public one needs no pin."""
    try:
        cert = x509.load_pem_x509_certificate(path.read_bytes())
    except (OSError, ValueError) as e:
        log.warning("the certificate %s can't be read: %s", path, e)
        return None
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


def _probe(address: str) -> str | None:
    """The certificate presented at this server's own link address, by its key; None when the
    system's roots verify it for its name, or when the address can't be reached."""
    u = urlsplit(address or "")
    if u.scheme != "https" or not u.hostname:
        return None
    host, port = u.hostname, u.port or 443
    try:
        with (
            socket.create_connection((host, port), timeout=5) as raw,
            ssl.create_default_context().wrap_socket(raw, server_hostname=host),
        ):
            return None  # public
    except ssl.SSLCertVerificationError:
        pass
    except OSError as e:
        log.info(
            "this server's own link address %s can't be read for its certificate: %s", address, e
        )
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    try:
        with (
            socket.create_connection((host, port), timeout=5) as raw,
            ctx.wrap_socket(raw, server_hostname=host) as tls,
        ):
            der = tls.getpeercert(binary_form=True)
    except OSError:
        return None
    return net.key_fingerprint(der) if der else None


def own_key(srv) -> str | None:
    """The fingerprint of this server's own certificate's key, or None when it is public."""
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
        if hit and (now - hit[0]).total_seconds() < CACHE_SECONDS:
            return hit[1]
    fp = _probe(address)
    with _lock:
        _cached[address] = (now, fp)
    return fp
