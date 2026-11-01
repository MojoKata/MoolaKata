"""The bitcoin backend mocks (requirements S17.9.7.8): each real source class in
bitcoin/sources.py against the fake Esplora, Electrum server and Bitcoin Core over real
sockets, reading the same chain, and a wallet synced from each through the server."""

import pytest
from edits import make, wallet

from moolakata import net
from moolakata.bitcoin import sources
from moolakata.dev.mocks import TIP, Mocks


@pytest.fixture(scope="module")
def mocks():
    m = Mocks(0, 0, 0, tls=True).start()
    yield m
    m.stop()


def guard() -> net.Guard:
    g = net.Guard()
    g.allow(["127.0.0.1"], ["127.0.0.1"])  # a node on the LAN is named by an admin (S13.5)
    return g


EXPECTED = {
    "fund": (50_000_000, 0, TIP - 900_000 + 1),
    "spend": (-20_001_000, 1_000, TIP - 900_100 + 1),
    "later": (10_000_000, 0, TIP - 919_390 + 1),
}


def _by_kind(chain, txs) -> dict:
    out = {}
    for t in txs:
        kind = "fund" if t.net == 50_000_000 else "later" if t.net == 10_000_000 else "spend"
        out[kind] = (t.net, t.fee, t.confirmations)
    return out


def test_the_fake_esplora_answers_as_mempool_space_does(mocks):
    cfg = sources.Config(esploraUrl=f"http://127.0.0.1:{mocks.ports()['esplora']}/api")
    e = sources.Esplora(cfg, guard())
    assert e.test() == f"Esplora answered: block {TIP:,}"
    c = mocks.chain
    got = _by_kind(c, e.history([c.first, c.change, c.far, "bc1qnothing"]))
    assert got == EXPECTED, got


def test_the_fake_electrum_server_speaks_the_protocol_with_tls_trusted_on_first_use(mocks):
    port = mocks.ports()["electrum"]
    cfg = sources.Config(kind="electrum", host="127.0.0.1", port=port, tls=True)
    e = sources.Electrum(cfg, guard())
    with pytest.raises(sources.CertificateChanged) as refused:
        e.history([mocks.chain.first])
    assert refused.value.sha256 == mocks.electrum.cert_sha256
    assert "not trusted yet" in sources.Electrum(cfg, guard()).test()
    trusted = sources.Config(
        kind="electrum",
        host="127.0.0.1",
        port=port,
        tls=True,
        certSha256=mocks.electrum.cert_sha256,
    )
    e = sources.Electrum(trusted, guard())
    c = mocks.chain
    got = _by_kind(c, e.history([c.first, c.change, c.far]))
    assert got == EXPECTED, got


def test_the_fake_core_makes_a_watch_only_wallet_and_lists_its_transactions(mocks):
    cfg = sources.Config(
        kind="core",
        host="127.0.0.1",
        port=mocks.ports()["core"],
        tls=False,
        rpcUser="mk",
        password="pw",
    )
    core = sources.Core(cfg, guard())
    assert core.test() == f"Bitcoin Core answered: block {TIP:,}"
    core.wallet("moolakata-test", [("wpkh(xpub/0/*)", 25), ("wpkh(xpub/1/*)", 25)])
    core.wallet("moolakata-test", [("wpkh(xpub/0/*)", 25)])  # already there: nothing imported twice
    txs, used = core.history_of("moolakata-test")
    c = mocks.chain
    assert used == {c.first, c.change, c.far}
    got = _by_kind(c, txs)
    assert got == EXPECTED, got


def test_a_wallet_syncs_from_the_fake_esplora_through_the_server(server, mocks):
    from conftest import make_user, sign_in

    from moolakata import settings
    from moolakata.bitcoin import sync
    from moolakata.dev.seed_wallets import TEST_ZPUB

    make_user(server, "alice")
    c = sign_in(server, "alice")
    with server.db.tx(unscoped="test") as s:
        settings.put(s, "bitcoinSource", "esplora", None)
        settings.put(
            s, "bitcoinEsploraUrl", f"http://127.0.0.1:{mocks.ports()['esplora']}/api", None
        )
    server.guard.allow(["127.0.0.1"], ["127.0.0.1"])
    r = make(c, "Acct", name="Cold storage", type="crypto-wallet")
    assert r.status_code == 200, r.text
    wid = r.json()["id"]
    assert wallet(c, wid, TEST_ZPUB).status_code == 200
    assert sync.sync_account(server, wid) == 3
    rows = c.get("/ui/api/transactions", params={"account": wid}).json()["items"]
    assert len(rows) >= 3
    from decimal import Decimal

    held = c.get(f"/ui/api/accounts/{wid}/holdings").json()["holdings"]
    assert [h["symbol"] for h in held] == ["BTC"]
    assert Decimal(str(held[0]["quantity"])) == Decimal("0.39999")
