"""Where a wallet's history comes from (requirements S1.6.2): each source's answers, and each
failure as the wallet's own reported one, which never names an address."""

import pytest
from test_wallets import (
    CHANGE,
    ELECTRUM_GOT,
    FIRST,
    SECOND,
    ZPUB,
    Wire,
    _electrum,
    _electrum_answers,
    _got,
    _raw,
)

from moolakata import net
from moolakata.bitcoin import keys, sources
from moolakata.store.entities.accounts import WalletKey

httpx = net.httpx


class Http:
    """An explorer's or a node's HTTP answers: `answer` gives a response, or an error raised."""

    def __init__(self, answer):
        self.answer = answer
        self.asked: list = []

    def get(self, url):
        self.asked.append(url)
        return self._out(self.answer(url))

    def post(self, url, json):
        self.asked.append((url, json["method"], json["params"]))
        return self._out(self.answer(json["method"], json["params"]))

    @staticmethod
    def _out(r):
        if isinstance(r, Exception):
            raise r
        return r


def _esplora(answer) -> sources.Esplora:
    e = sources.Esplora(sources.Config(), net.Guard())
    e.client = Http(answer)
    return e


def _core(answer) -> sources.Core:
    cfg = sources.Config(kind="core", host="node.lan", port=8332, tls=False)
    core = sources.Core(cfg, net.Guard())
    core.client = Http(answer)
    return core


def _rpc(result) -> httpx.Response:
    return httpx.Response(200, json={"result": result, "error": None, "id": "mk"})


# ---------- choosing a source


def test_each_kind_is_its_own_source_and_a_node_needs_its_host():
    g = net.Guard()
    assert isinstance(sources.make(sources.Config(), g), sources.Esplora)
    node = dict(host="node.lan")
    assert isinstance(sources.make(sources.Config(kind="electrum", **node), g), sources.Electrum)
    assert isinstance(sources.make(sources.Config(kind="core", **node), g), sources.Core)
    with pytest.raises(sources.SourceError, match="Name the Electrum server's host first"):
        sources.make(sources.Config(kind="electrum"), g)
    with pytest.raises(sources.SourceError, match="Name Bitcoin Core's host first"):
        sources.make(sources.Config(kind="core"), g)
    assert sources.Config(esploraUrl="/api").hosts() == ([], [])
    assert sources.Config(kind="core").hosts() == ([], [])


# ---------- Esplora


def test_esplora_gives_the_tip_as_text_as_mempool_space_does():
    e = _esplora(lambda url: httpx.Response(200, text="919402"))
    assert e.test() == "Esplora answered: block 919,402"


def test_esplora_pages_an_addresses_confirmed_transactions_25_at_a_time():
    def tx(i, confirmed=True):
        status = {"confirmed": True, "block_height": 900_000, "block_time": 1_780_000_000}
        return {
            "txid": f"{i:064x}",
            "status": status if confirmed else {"confirmed": False},
            "vin": [],
            "vout": [{"scriptpubkey_address": FIRST, "value": 1_000}],
        }

    first = [tx(99, confirmed=False)] + [tx(i) for i in range(25)]
    pages = {f"/address/{FIRST}/txs": first, f"/address/{FIRST}/txs/chain/{24:064x}": [tx(25)]}

    def answer(url):
        path = url.removeprefix(sources.DEFAULT_ESPLORA)
        return httpx.Response(200, text="900009") if path.endswith("height") else (
            httpx.Response(200, json=pages[path])
        )  # fmt: skip

    e = _esplora(answer)
    got = e.history([FIRST])
    assert len(got) == 27 and sum(t.net for t in got) == 27_000
    assert {t.confirmations for t in got} == {10, None}, "the unconfirmed one isn't counted"


@pytest.mark.parametrize(
    "answer, words",
    [
        (httpx.ConnectTimeout(f"/address/{FIRST}"), " didn't answer (ConnectTimeout)."),
        (httpx.Response(429), " asked to slow down (429); it is tried again later."),
        (httpx.Response(503), " answered 503."),
        (httpx.Response(200, json=[{"status": {}}]), "'s answer couldn't be read (KeyError)."),
        (httpx.Response(200, json={"txid": FIRST}), "'s answer couldn't be read (TypeError)."),
    ],
)
def test_an_explorers_failure_says_what_to_fix_without_naming_an_address(answer, words):
    e = _esplora(lambda url: httpx.Response(200, text="1") if url.endswith("height") else answer)
    with pytest.raises(sources.SourceError) as got:
        e.history([FIRST])
    assert str(got.value) == sources.DEFAULT_ESPLORA + words
    assert FIRST not in str(got.value)


# ---------- an Electrum server


class Guard:
    """The egress guard's answer for the node: its address, as checked."""

    def check(self, host, port, use=None):
        assert use == "bitcoin"
        return "192.168.1.20"


def _connected(monkeypatch, answer=None, **cfg):
    wires = []

    def connect(address, timeout):
        assert address == ("192.168.1.20", 50001)
        wires.append(Wire(answer or _electrum_answers()))
        return wires[-1]

    monkeypatch.setattr(sources.socket, "create_connection", connect)
    config = sources.Config(kind="electrum", host="node.lan", port=50001, tls=False, **cfg)
    return sources.Electrum(config, Guard()), wires


def test_an_electrum_server_without_tls_is_read_and_tested_on_connections_of_their_own(
    monkeypatch,
):
    e, wires = _connected(monkeypatch)
    assert _got(e.history([FIRST, SECOND, CHANGE])) == ELECTRUM_GOT
    assert e.test() == "Fulcrum 1.11 answered: block 900,105", "no certificate without TLS"
    assert len(wires) == 2 and all(w.closed for w in wires)
    assert wires[0].asked[0] == "server.version"


def test_an_electrum_servers_version_may_be_one_string(monkeypatch):
    answer = _electrum_answers()
    e, _ = _connected(
        monkeypatch, lambda m, *p: "ElectrumX 1.16" if m == "server.version" else answer(m, *p)
    )
    assert e.test() == "ElectrumX 1.16 answered: block 900,105"


def test_an_unconfirmed_or_coinbase_transaction_is_read_from_the_server(monkeypatch):
    import hashlib

    coinbase = _raw([("00" * 32, 0xFFFFFFFF)], [(keys.script_of(FIRST), 5_000)])
    sh = hashlib.sha256(keys.script_of(FIRST)).digest()[::-1].hex()

    def answer(method, *params):
        if method == "blockchain.scripthash.get_history":
            return [{"tx_hash": "ef" * 32, "height": 0}] if params[0] == sh else []
        if method == "blockchain.transaction.get":
            return coinbase.hex()
        return _electrum_answers()(method, *params)

    e, _ = _connected(monkeypatch, answer)
    (t,) = e.history([FIRST])
    assert (t.net, t.fee, t.confirmations, t.confirmedAt) == (5_000, 0, None, None)


def test_a_raw_transactions_long_counts_are_read():
    # A count of 253 or more takes the 0xFD form and two bytes (the Bitcoin varint).
    raw = (2).to_bytes(4, "little") + b"\x00" + b"\xfd" + (253).to_bytes(2, "little")
    raw += ((1).to_bytes(8, "little") + b"\x00") * 253 + bytes(4)
    ins, outs = sources.parse_tx(raw)
    assert ins == [] and len(outs) == 253 and outs[0] == (b"", 1)


@pytest.mark.parametrize(
    "refused, words",
    [
        (ConnectionRefusedError(111, "Connection refused"), "node.lan:50001 didn't answer"),
        (net.EgressRefused("node.lan is not a host"), "node.lan:50001 didn't answer"),
    ],
)
def test_an_electrum_server_that_cant_be_reached_says_so(monkeypatch, refused, words):
    def connect(address, timeout):
        raise refused

    monkeypatch.setattr(sources.socket, "create_connection", connect)
    cfg = sources.Config(kind="electrum", host="node.lan", port=50001, tls=False)
    with pytest.raises(sources.SourceError, match=words):
        sources.Electrum(cfg, Guard()).history([FIRST])


class Broken(Wire):
    """A connection that fails as `how` says once the server is asked for a transaction."""

    def __init__(self, how):
        super().__init__(_electrum_answers())
        self.how = how

    def sendall(self, data):
        if b"transaction.get" in data and self.how == "send":
            raise BrokenPipeError(32, "Broken pipe")
        super().sendall(data)
        if b"transaction.get" in data:
            self.out = {"recv": self.out, "closed": b"", "big": b"x" * 64}[self.how]

    def recv(self, n):
        if self.how == "recv" and b"transaction" in str(self.asked[-1:]).encode():
            raise TimeoutError("timed out")
        return super().recv(n)


@pytest.mark.parametrize(
    "how, words",
    [
        ("send", "The Electrum server stopped answering: [Errno 32] Broken pipe"),
        ("recv", "The Electrum server stopped answering: timed out"),
        ("closed", "The Electrum server closed the connection."),
        ("big", "The Electrum server's answer is larger than allowed."),
    ],
)
def test_an_electrum_connection_that_fails_mid_read_says_so(monkeypatch, how, words):
    monkeypatch.setattr(net, "MAX_RESPONSE", 32)
    wire = Broken(how)
    if how != "big":
        monkeypatch.setattr(net, "MAX_RESPONSE", 20 * 1024 * 1024)
    e = _electrum(wire)
    with pytest.raises(sources.SourceError) as got:
        e.history([FIRST])
    assert str(got.value) == words and wire.closed and e.sock is None


def test_an_electrum_servers_refusal_names_what_it_refused():
    def refuse(req, res):
        if req["method"] != "blockchain.transaction.get":
            return res
        return {"jsonrpc": "2.0", "id": req["id"], "error": {"code": 2, "message": "unknown"}}

    with pytest.raises(sources.SourceError, match=r"refused blockchain\.transaction\.get"):
        _electrum(Wire(_electrum_answers(), reply=refuse)).history([FIRST])


# ---------- Bitcoin Core


@pytest.mark.parametrize(
    "answer, words",
    [
        (httpx.ConnectError("refused"), "Bitcoin Core at http://node.lan:8332 didn't answer"),
        (httpx.Response(401), "Bitcoin Core refused the RPC user or password."),
        (httpx.Response(502, text="<html>Bad gateway</html>"), "Bitcoin Core answered 502."),
        (
            httpx.Response(500, json={"result": None, "error": {"message": "Method not found"}}),
            "Bitcoin Core refused getblockchaininfo: Method not found",
        ),
        (_rpc({"chain": "test", "blocks": 1}), "Bitcoin Core follows test, not mainnet."),
        (_rpc(["main"]), "Bitcoin Core's answer couldn't be read (AttributeError)."),
        (_rpc({"chain": "main"}), "Bitcoin Core's answer couldn't be read (KeyError)."),
    ],
)
def test_a_nodes_failure_says_what_to_fix(answer, words):
    with pytest.raises(sources.SourceError) as got:
        _core(lambda method, params: answer).test()
    assert str(got.value).startswith(words)


def test_core_watches_a_typed_address_whole_and_imports_it_once():
    have: list[dict] = []

    def answer(method, params):
        if method == "listwallets":
            return _rpc(["moolakata-0a1b"])
        if method == "listdescriptors":
            return _rpc({"descriptors": have})
        if method == "getdescriptorinfo":
            return _rpc({"descriptor": params[0] + "#chk"})
        if method == "importdescriptors":
            have.extend(params[0])
            return _rpc([{"success": True}])
        raise AssertionError(method)

    core = _core(answer)
    core.wallet("moolakata-0a1b", [(f"addr({FIRST})", None)])
    assert have == [{"desc": f"addr({FIRST})#chk", "timestamp": 0, "watchonly": True}]
    core.wallet("moolakata-0a1b", [(f"addr({FIRST})", None)])
    assert len(have) == 1 and core.client.asked[-1][1] == "getdescriptorinfo"
    assert core.client.asked[0][0] == "http://node.lan:8332/"
    assert core.client.asked[1][0] == "http://node.lan:8332/wallet/moolakata-0a1b"


def test_core_lists_a_wallets_transactions_500_at_a_time():
    # Amounts in BTC as Core sends them, read as decimals.
    received = [
        {"txid": f"{i:064x}", "category": "receive", "amount": 0.00001,
         "address": FIRST, "confirmations": 7, "blocktime": 1_780_000_000}
        for i in range(500)
    ]  # fmt: skip
    later = [
        {"txid": "ab" * 32, "category": "send", "amount": -0.2, "fee": -0.00001,
         "address": "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy", "confirmations": 0},
        {"txid": "cd" * 32, "category": "immature", "amount": 6.25, "address": CHANGE},
    ]  # fmt: skip

    def answer(method, params):
        if method == "listtransactions":
            return _rpc(received if params[2] == 0 else later)
        return _rpc([{"address": FIRST}])

    txs, used = _core(answer).history_of("moolakata-0a1b")
    by = {t.txid: t for t in txs}
    assert len(by) == 502 and used == {FIRST}
    assert by[f"{0:064x}"].net == 1_000 and by[f"{0:064x}"].confirmations == 7
    sent = by["ab" * 32]
    assert (sent.net, sent.fee, sent.confirmedAt) == (-20_001_000, 1_000, None)
    assert by["cd" * 32].net == 0 and not by["cd" * 32].addresses, "only receive and send count"


def test_a_descriptor_key_is_given_to_core_a_chain_at_a_time():
    raw = keys.b58check_decode(ZPUB)
    xpub = keys.b58check_encode(bytes.fromhex("0488b21e") + raw[4:])
    k = WalletKey(
        id="WKey_d", accountId="a", kind="descriptor", value=f"wpkh({xpub}/<0;1>/*)",
        script="p2wpkh",
    )  # fmt: skip
    (recv, top), (chg, _) = sources.descriptors(k, None)
    assert recv.startswith(f"wpkh({xpub}/0/*)") and chg.startswith(f"wpkh({xpub}/1/*)")
    assert top == 0, "nothing derived yet: the first address"
