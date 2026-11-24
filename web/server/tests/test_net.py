"""The ceiling on an answer (requirements S13.5), as every caller reads it: counted in decoded
bytes, whatever coding the answer comes in and whatever length it announces. The answers come
from `httpx.MockTransport` standing where the sockets are (`net.network`), so everything
`net.Client` does above them is the real code."""

import gzip
import itertools
import json
import zlib

import httpx
import pytest

from moolakata import net

CEILING = 10_000
CODINGS = ("none", "gzip", "deflate", "br")
LENGTHS = ("none", "true", "lie")
READS = ("json", "content", "stream", "get_bytes")
SIZES = ("under", "over")


def payload(size: str) -> bytes:
    """JSON that decodes to under the ceiling, or to five times it."""
    n = CEILING // 2 if size == "under" else CEILING * 5
    return json.dumps({"a": "x" * n}).encode()


def encoded(coding: str, raw: bytes) -> bytes:
    if coding == "gzip":
        return gzip.compress(raw)
    if coding == "deflate":
        return zlib.compress(raw)
    return raw  # `br` is sent as is: refused for its name before a byte is read


def answer(coding: str, length: str, size: str) -> httpx.Response:
    raw = payload(size)
    body = encoded(coding, raw)
    headers = {} if coding == "none" else {"Content-Encoding": coding}
    if length != "none":
        # Its length as sent, or less than it sends.
        headers["Content-Length"] = str(len(body)) if length == "true" else "100"
    return streamed(body, headers)


def streamed(body: bytes, headers: dict) -> httpx.Response:
    """An answer as the sockets give one: read as it arrives, in pieces. (Content in hand would
    be read, and decoded, by httpx as the answer is made, before `net` sees it.)"""
    pieces = [body[i : i + 1000] for i in range(0, len(body), 1000)]
    return httpx.Response(200, headers=headers, content=iter(pieces))


@pytest.fixture
def served(monkeypatch):
    """Whatever `answer` the test sets, from a host the guard allows."""
    box: dict = {}

    def network(guard, pins):
        return httpx.MockTransport(lambda request: box["answer"])

    monkeypatch.setattr(net, "network", network)
    guard = net.Guard(resolver=lambda host, port: ["192.0.2.10"])
    guard.allow(["peer.lan"])
    return box, net.Client(guard, max_bytes=CEILING)


def read(client: net.Client, how: str) -> bytes:
    url = "https://peer.lan/x"
    if how == "json":
        return json.dumps(client.get(url).json()).encode()
    if how == "content":
        return client.get(url).content
    if how == "get_bytes":
        return client.get_bytes(url)[1]
    with client.stream("GET", url) as r:
        return b"".join(r.iter_bytes())


@pytest.mark.parametrize(
    ("coding", "length", "how", "size"), list(itertools.product(CODINGS, LENGTHS, READS, SIZES))
)
def test_the_ceiling_counts_what_an_answer_decodes_to(served, coding, length, how, size):
    """Every coding × announced length × way of reading × size: an answer under the ceiling
    reads as it was sent; one that decodes past it is cut off at the ceiling, though gzip or
    deflate carries it in far fewer bytes; a coding MoolaKata doesn't decode is refused."""
    box, client = served
    box["answer"] = answer(coding, length, size)
    if coding == "br":
        with pytest.raises(net.EncodingRefused):
            read(client, how)
    elif size == "over":
        with pytest.raises(net.ResponseTooLarge):
            read(client, how)
    else:
        assert json.loads(read(client, how)) == json.loads(payload(size))


def test_a_raw_deflate_answer_is_read_and_a_damaged_one_refused(served):
    """Some servers send deflate without zlib's wrapper; an answer that isn't what it says it
    is fails as a decoding error, never as something read."""
    box, client = served
    raw = payload("under")
    squeeze = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    box["answer"] = streamed(
        squeeze.compress(raw) + squeeze.flush(), {"Content-Encoding": "deflate"}
    )
    assert client.get("https://peer.lan/x").content == raw
    box["answer"] = streamed(b"not gzip", {"Content-Encoding": "gzip"})
    with pytest.raises(httpx.DecodingError):
        client.get("https://peer.lan/x")


def test_only_the_codings_decoded_are_asked_for(monkeypatch):
    asked = {}

    def network(guard, pins):
        def handler(request):
            asked["accept"] = request.headers.get("accept-encoding")
            return httpx.Response(200, content=b"{}")

        return httpx.MockTransport(handler)

    monkeypatch.setattr(net, "network", network)
    guard = net.Guard(resolver=lambda host, port: ["192.0.2.10"])
    guard.allow(["peer.lan"])
    net.Client(guard).get("https://peer.lan/")
    assert asked["accept"] == "gzip, deflate"


@pytest.mark.parametrize(
    ("address", "why"),
    [
        ("::ffff:127.0.0.1", "a loopback address"),  # an IPv4 address written as IPv6
        ("::ffff:169.254.169.254", "a cloud metadata address"),
        ("169.254.10.1", "a link-local address"),
        ("fe80::1", "a link-local address"),
        ("0.0.0.0", "not a host address"),
        ("224.0.0.1", "not a host address"),
        ("240.0.0.1", "not a host address"),
        ("::", "not a host address"),
    ],
)
def test_an_address_that_is_no_host_to_reach_is_refused_saying_why(address, why):
    """S13.5: every address a name resolves to is checked; one that isn't a host on the
    network is refused, the words naming what it is."""
    guard = net.Guard(resolver=lambda host, port: [address])
    guard.allow(["peer.lan"])
    with pytest.raises(net.EgressRefused) as e:
        guard.check("peer.lan", 443)
    assert str(e.value) == f"peer.lan resolves to {why}; an admin can allow it by name"


def test_a_name_that_resolves_to_nothing_is_not_reached():
    guard = net.Guard(resolver=lambda host, port: [])
    guard.allow(["peer.lan"])
    with pytest.raises(httpx.ConnectError, match=r"cannot resolve peer\.lan"):
        guard.check("peer.lan", 443)

    def failing(host, port):
        raise OSError("Name or service not known")

    guard = net.Guard(resolver=failing)
    guard.allow(["peer.lan"])
    with pytest.raises(httpx.ConnectError, match=r"cannot resolve peer\.lan: Name or service"):
        guard.check("peer.lan", 443)


def test_a_scheme_other_than_http_or_https_is_refused(served):
    with pytest.raises(net.EgressRefused, match="ftp is not allowed"):
        served[1].get("ftp://peer.lan/x")


class _Tls:
    """A TLS connection as httpcore hands one back, presenting no certificate (a test's)."""

    def get_extra_info(self, info):
        return {"socket": None, "alpn": "h2"}.get(info)

    def close(self):
        pass


class _Plain:
    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        return _Tls()


def test_a_public_connection_carries_no_pinned_key_and_a_pinned_one_names_its_own():
    """S11.1.3: over a public check no pinned key is named; with pins, one that presents none
    is refused before anything is sent."""
    public = net._Stream(_Plain(), None).start_tls(None, "peer.lan")
    assert public.get_extra_info(net.PRESENTED) is None
    assert public.get_extra_info("alpn") == "h2", "what it doesn't keep, the connection says"
    with pytest.raises(net.CertificateRefused) as e:
        net._Stream(_Plain(), frozenset({"ab" * 32})).start_tls(None, "peer.lan")
    assert e.value.fingerprint == ""
    assert net._Stream(_Plain(), None, presented="cd" * 32).get_extra_info(net.PRESENTED) == (
        "cd" * 32
    )


def test_a_gzip_answer_in_pieces_too_small_to_decode_alone_is_read_whole(served):
    """A piece that decodes to nothing yet (part of gzip's header) yields nothing, and the
    answer is read whole once the rest arrives."""
    box, client = served
    raw = payload("under")
    body = gzip.compress(raw)
    pieces = [body[i : i + 5] for i in range(0, len(body), 5)]
    box["answer"] = httpx.Response(200, headers={"Content-Encoding": "gzip"}, content=iter(pieces))
    assert client.get("https://peer.lan/x").content == raw
