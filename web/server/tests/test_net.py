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
