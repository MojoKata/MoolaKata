"""This server's own certificate (S11.1.3, S18.4, S13.3): read at its link address, or, when
that can't be reached, from the listener's file in tls mode; a public one, which the system's
roots vouch for, needs no pin; one that can't be read is never taken for a public one."""

import datetime as dt
import ssl

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from moolakata import certs, net


def _name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _cert(subject, issuer, key, signer, sans=None, ca=False):
    now = dt.datetime.now(dt.UTC)
    b = (
        x509.CertificateBuilder()
        .subject_name(_name(subject))
        .issuer_name(_name(issuer))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=90))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
    )
    if ca:
        b = b.add_extension(
            x509.KeyUsage(
                digital_signature=False, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=True, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )  # fmt: skip
    else:
        b = b.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(signer.public_key()), critical=False
        ).add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
    if sans is not None:
        b = b.add_extension(x509.SubjectAlternativeName(sans), critical=False)
    return b.sign(signer, hashes.SHA256())


@pytest.fixture
def ca(tmp_path, monkeypatch):
    """A root the system trusts, here: the default verify paths lead to it alone."""
    key = ec.generate_private_key(ec.SECP256R1())
    root = _cert("Test Root", "Test Root", key, key, ca=True)
    bundle = tmp_path / "roots.pem"
    bundle.write_bytes(root.public_bytes(Encoding.PEM))
    paths = ssl.DefaultVerifyPaths(str(bundle), None, "", "", "", "")
    monkeypatch.setattr(ssl, "get_default_verify_paths", lambda: paths)
    return key


def _issued(ca_key, sans):
    key = ec.generate_private_key(ec.SECP256R1())
    return _cert("money.example.org", "Test Root", key, ca_key, sans=sans)


def _fingerprint(cert):
    return net.key_fingerprint(cert.public_bytes(Encoding.DER))


def test_a_certificate_the_roots_vouch_for_by_its_name_is_public(ca):
    assert certs._public_by_name(_issued(ca, [x509.DNSName("money.example.org")]))


@pytest.mark.parametrize(
    "sans",
    [
        None,  # no names at all
        [x509.IPAddress(__import__("ipaddress").ip_address("192.0.2.7"))],  # no DNS name
    ],
)
def test_a_certificate_with_no_name_to_check_is_not_public(ca, sans):
    assert not certs._public_by_name(_issued(ca, sans))


def test_a_certificate_no_root_vouches_for_is_not_public(ca):
    other = ec.generate_private_key(ec.SECP256R1())
    assert not certs._public_by_name(_issued(other, [x509.DNSName("money.example.org")]))


def test_the_listeners_file_gives_its_key_unless_it_is_public(ca, tmp_path, caplog):
    """S13.3: in tls mode the certificate is read from its file: a public one is no pin, any
    other is pinned by its key, and one that can't be read is Unread, the log saying why."""
    path = tmp_path / "listener.crt"
    public = _issued(ca, [x509.DNSName("money.example.org")])
    path.write_bytes(public.public_bytes(Encoding.PEM))
    assert certs._from_file(path) is None
    own = _issued(ec.generate_private_key(ec.SECP256R1()), [x509.DNSName("money.example.org")])
    path.write_bytes(own.public_bytes(Encoding.PEM))
    assert certs._from_file(path) == _fingerprint(own)
    path.write_text("not a certificate")
    with pytest.raises(certs.Unread):
        certs._from_file(path)
    with pytest.raises(certs.Unread):
        certs._from_file(tmp_path / "missing.crt")
    assert f"the certificate {tmp_path / 'missing.crt'} can't be read" in caplog.text


def test_in_tls_mode_with_its_address_unread_the_key_is_read_from_the_certificate_it_serves(
    server, monkeypatch, tmp_path
):
    """S11.1.1: a server that serves TLS itself and can't reach its own address reads the key
    from the certificate it was given, or the self-signed one; one that can't be read is
    Unread, never public."""
    import dataclasses

    from moolakata.listener import self_signed

    def unread(guard, address):
        raise certs.Unread

    monkeypatch.setattr(certs, "_probe", unread)
    tls = dataclasses.replace(server.config, mode="tls")
    cert, _ = self_signed(tls.tls_dir, ["money.lan"])
    made = x509.load_pem_x509_certificate(cert.read_bytes())
    server.config = tls
    assert certs.own_key_read(server) == _fingerprint(made)
    server.config = dataclasses.replace(tls, tls_cert=tmp_path / "gone.crt")
    with pytest.raises(certs.Unread):
        certs.own_key_read(server)
    assert certs.own_key(server) is None


class _Client:
    """Stands in for net.Client: the public check answers as told, the pinned one refuses."""

    public: Exception | None = None
    pinned: Exception | None = None

    def __init__(self, guard, use, pins=None):
        self.pins = pins

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def head(self, url, timeout):
        error = _Client.public if self.pins is None else _Client.pinned
        if error is not None:
            raise error


def _unverified():
    e = net.httpx.ConnectError("certificate verify failed")
    e.__cause__ = ssl.SSLCertVerificationError(1, "certificate verify failed")
    return e


@pytest.mark.parametrize(
    ("public", "pinned", "answer"),
    [
        (None, None, None),  # the roots vouch for it
        (_unverified(), net.CertificateRefused("ab" * 32), "ab" * 32),
        (_unverified(), net.CertificateRefused(""), certs.Unread),  # no key read in it
        (_unverified(), net.httpx.ConnectError("reset"), certs.Unread),
        (_unverified(), None, certs.Unread),  # answered with no pin: never so
        (net.httpx.ConnectTimeout("timed out"), None, certs.Unread),
    ],
)
def test_the_probe_of_the_link_address_tells_public_own_and_unread_apart(
    monkeypatch, public, pinned, answer
):
    monkeypatch.setattr(net, "Client", _Client)
    monkeypatch.setattr(_Client, "public", public)
    monkeypatch.setattr(_Client, "pinned", pinned)
    if answer is certs.Unread:
        with pytest.raises(certs.Unread):
            certs._probe(net.Guard(), "https://money.example.org")
    else:
        assert certs._probe(net.Guard(), "https://money.example.org") == answer


@pytest.mark.parametrize("address", ["", "ftp://money.example.org", "https://"])
def test_an_address_with_no_https_host_has_no_certificate_to_read(address):
    assert certs._probe(net.Guard(), address) is None
