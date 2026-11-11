"""Self-custody wallets (requirements S1.6.1, S1.6.3): extended public keys and addresses, the
addresses derived from a key, and keys and seed phrases refused."""

import logging

import pytest
from conftest import make_user, sign_in
from edits import save_settings, saved, wallet
from test_accounts import new_account

from moolakata.bitcoin import keys

# The BIP84, BIP49 and BIP44 test wallets ("abandon abandon … about"), whose addresses are
# published with those standards.
ZPUB = (
    "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868Rv"
    "UUkgDKf31mGDtKsAYz2oz2AGutZYs"
)
YPUB = (
    "ypub6Ww3ibxVfGzLrAH1PNcjyAWenMTbbAosGNB6VvmSEgytSER9azLDWCxoJwW7Ke7icmizBMXrzBx9979Ff"
    "aHxHcrArf3zbeJJJUZPf663zsP"
)
XPUB = (
    "xpub6BosfCnifzxcFwrSzQiqu2DBVTshkCXacvNsWGYJVVhhawA7d4R5WSWGFNbi8Aw6ZRc1brxMyWMzG3DSSS"
    "SoekkudhUd9yLb6qx39T9nMdj"
)
SEED = "abandon " * 11 + "about"
WIF = "5HueCGU8rMjxEXxiPuD5BDku4MkFqeZyd4dZ1jvhTVqvbTLvyTJ"
HEX = "0c28fca386c7a227600b2fe50b7cae11ec86d3bf1fbe471be89827e19d72aa1d"
XPRV = (
    "xprv9s21ZrQH143K3QTDL4LXw2F7HEK3wJUD2nW2nRk4stbPy6cq3jPPqjiChkVvvNKmPGJxWUtg6LnF5kejMR"
    "NNU3TGtRBeJgk33yuGBxrMPHi"
)


def test_keys_derive_the_published_addresses():
    z = keys.extended(ZPUB)
    assert z.address(0, 0) == "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
    assert z.address(0, 1) == "bc1qnjg0jd8228aq7egyzacy8cys3knf9xvrerkf9g"
    assert z.address(1, 0) == "bc1q8c6fshw2dlwun7ekn9qwf37cu2rn755upcp6el"
    assert keys.extended(YPUB).address(0, 0) == "37VucYSaXLCAsxYyAPfbSi9eh4iEcbShgf"
    assert keys.extended(XPUB).address(0, 0) == "1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA"


def test_addresses_are_checked():
    assert keys.address_script("bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu") == "p2wpkh"
    assert keys.address_script("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy") == "p2sh"
    assert keys.address_script("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2") == "p2pkh"
    tr = "bc1p5d7rjq7g6rdk2yhzks9smlaqtedr4dekq08ge8ztwac72sfr9rusxg3297"
    assert keys.address_script(tr) == "p2tr"
    for bad, code in (
        ("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN3", "address-invalid"),  # checksum
        ("tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx", "testnet"),
        ("hello", "address-invalid"),
    ):
        with pytest.raises(keys.Refused) as e:
            keys.address_script(bad)
        assert e.value.code == code


@pytest.mark.parametrize(
    "text,what",
    [
        (SEED, "seed phrase"),
        (SEED.upper(), "seed phrase"),
        (" ".join(["zoo"] * 23 + ["wrong"]), "seed phrase"),
        (WIF, "private key (WIF)"),
        ("KwdMAjGmerYanjeui5SHS7JkmpZvVipYvB2LJGU1ZxJwYvP98617", "private key (WIF)"),
        (HEX, "private key (64 hex digits)"),
        (XPRV, "extended private key"),
        (ZPUB + "\n" + WIF, "private key (WIF)"),
        ("\n".join(f"{i}. {w}" for i, w in enumerate(SEED.split(), 1)), "seed phrase"),
        (" ".join(f"{i}) {w}" for i, w in enumerate(SEED.split(), 1)), "seed phrase"),
        (",".join(SEED.split()), "seed phrase"),
        (f"wpkh({WIF})", "private key (WIF)"),
        (f"wpkh([d34db33f/84h/0h/0h]{XPRV}/0/*)#qwer1234", "extended private key"),
        (f"tr({HEX})", "private key (64 hex digits)"),
    ],
)
def test_secrets_are_recognised(text, what):
    assert keys.secret_kind(text) == what


def test_public_data_is_not_mistaken_for_a_secret():
    assert keys.secret_kind(ZPUB) is None
    assert (
        keys.secret_kind(
            "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu 37VucYSaXLCAsxYyAPfbSi9eh4iEcbShgf"
        )
        is None
    )


@pytest.fixture(autouse=True)
def bitcoin_saved(request):
    """Settings › Bitcoin as an admin saved it: no wallet is read before (S16.7)."""
    if "server" not in request.fixturenames:
        return
    from moolakata import settings

    srv = request.getfixturevalue("server")
    with srv.db.tx(unscoped="test") as s:
        settings.put(s, "bitcoinSource", "esplora", None)


@pytest.fixture
def alice(server):
    make_user(server, "alice")
    return sign_in(server, "alice")


def test_a_wallet_watches_a_keys_addresses_up_to_the_gap_limit(alice):
    w = new_account(alice, name="Cold storage", type="crypto-wallet")
    r = wallet(alice, w["id"], ZPUB)
    assert r.status_code == 200, r.text
    v = alice.get(f"/ui/api/accounts/{w['id']}/wallet").json()
    assert v["keys"][0]["script"] == "p2wpkh" and v["keys"][0]["gapLimit"] == 20
    assert v["watched"] == 40, "20 receive and 20 change"
    first = v["addresses"][0]
    assert (first["address"], first["chain"], first["index"]) == (
        "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu",
        0,
        0,
    )
    assert len(v["addresses"]) == 20, "the first 10 a chain are shown"
    # An address added, the gap limit narrowed: the key keeps its addresses.
    saved(wallet(alice, w["id"], ZPUB + "\n3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy", 5))
    v = alice.get(f"/ui/api/accounts/{w['id']}/wallet").json()
    assert [k["kind"] for k in v["keys"]] == ["xpub", "address"]
    assert v["keys"][0]["gapLimit"] == 5 and v["watched"] == 41
    # The key taken out: its addresses go with it.
    saved(wallet(alice, w["id"], "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"))
    v = alice.get(f"/ui/api/accounts/{w['id']}/wallet").json()
    assert v["watched"] == 1 and v["addresses"][0]["chain"] is None
    assert alice.get(f"/ui/api/accounts/{w['id']}/wallet").json()["watched"] == 1


def test_a_seed_phrase_or_private_key_is_refused_and_never_repeated(alice, caplog):
    w = new_account(alice, name="Cold storage", type="crypto-wallet")
    caplog.set_level(logging.DEBUG)
    for text in (SEED, WIF, HEX, XPRV):
        r = wallet(alice, w["id"], text)
        assert r.status_code == 422
        assert r.json()["errors"][0]["code"] == "secret-refused"
        assert r.json()["errors"][0]["field"] == "walletKeys"
        assert text.split()[0] not in r.text
    assert not any(SEED.split()[1] in m or WIF in m or HEX in m for m in caplog.messages)
    assert alice.get(f"/ui/api/accounts/{w['id']}/wallet").json()["watched"] == 0


def test_only_a_wallet_holds_keys(alice):
    b = new_account(alice, name="Brokerage", type="brokerage")
    r = wallet(alice, b["id"], ZPUB)
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "not-a-wallet"
    w = new_account(alice, name="Cold storage", type="crypto-wallet")
    r = wallet(alice, w["id"], ZPUB[:-1] + "a")
    assert r.json()["errors"][0]["code"] == "key-invalid"


# ---------- reading wallets from an explorer or node (S1.6.2)

import dataclasses  # noqa: E402
import datetime as dt  # noqa: E402
from decimal import Decimal as D  # noqa: E402

from moolakata.bitcoin import sources, sync  # noqa: E402

FIRST = "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"  # receive 0
SECOND = "bc1qnjg0jd8228aq7egyzacy8cys3knf9xvrerkf9g"  # receive 1
CHANGE = "bc1q8c6fshw2dlwun7ekn9qwf37cu2rn755upcp6el"  # change 0
T1 = dt.datetime(2026, 3, 2, 15, tzinfo=dt.UTC)
T2 = dt.datetime(2026, 6, 9, 15, tzinfo=dt.UTC)


class Fake:
    """An explorer that knows a few transactions: 0.5 BTC in at receive 0; then 0.2 sent from
    it, the change at change 0; and 0.1 in at receive 19, past the first gap."""

    def __init__(self, far: str):
        self.far = far
        self.asked: list[list[str]] = []

    def test(self):
        return "Fake answered: block 1"

    def history(self, addresses):
        self.asked.append(addresses)
        out = []
        if FIRST in addresses:
            out.append(sources.Tx("a" * 64, T1, 50_000_000, 0, {FIRST}))
            out.append(
                sources.Tx("b" * 64, T2, -20_001_000, 1_000, {FIRST, CHANGE}),
            )
        if self.far in addresses:
            out.append(sources.Tx("c" * 64, T2, 10_000_000, 0, {self.far}))
        out.append(sources.Tx("d" * 64, None, 5_000, 0, {FIRST}))  # unconfirmed
        shallow = sources.Tx("e" * 64, T2, 7_000, 0, {FIRST})
        shallow.confirmations = 3  # waits for 6
        out.append(shallow)
        return out


def test_a_sync_records_each_transaction_once_and_extends_the_gap(server, alice, monkeypatch):
    w = new_account(alice, name="Cold storage", type="crypto-wallet")
    saved(wallet(alice, w["id"], ZPUB))
    far = keys.extended(ZPUB).address(0, 19)
    fake = Fake(far)
    monkeypatch.setattr(sync, "source", lambda srv, s: fake)
    r = alice.post(f"/ui/api/accounts/{w['id']}/wallet/sync")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["recorded"] == 3, "two received, one sent; the unconfirmed one waits"
    v = out["wallet"]
    assert v["used"] == 3
    assert v["watched"] == 40 + 20 + 1, "receive 19 used: 20 more past it; change 0: one more"
    items = alice.get("/ui/api/transactions", params={"account": w["id"]}).json()["items"]
    got = sorted((t["kind"], t["quantity"], t["date"]) for t in items)
    assert got == [
        ("fee", None, "2026-06-09"),
        ("sell", "0.00001", "2026-06-09"),
        ("transfer-in", "0.1", "2026-06-09"),
        ("transfer-in", "0.5", "2026-03-02"),
        ("transfer-out", "0.2", "2026-06-09"),
    ], "the fee's sats are sold, beside a fee of their value (S8.19)"
    assert alice.post(f"/ui/api/accounts/{w['id']}/wallet/sync").json()["recorded"] == 0
    held = next(
        p for p in alice.get("/ui/api/positions").json()["open"] if p["accountId"] == w["id"]
    )
    assert held["symbol"] == "BTC" and held["quantity"] == "0.39999"
    assert held["cost"] is None, "coins received carry no basis until it is entered"


def test_a_coinjoins_fee_is_the_wallets_share_never_the_whole(server, alice):
    # B13: others' inputs paid most of the 12,000-sat fee; the wallet put in 1,500 net, so its
    # share is 1,500, and nothing else left it.
    from moolakata.store.entities.accounts import Transaction

    w = new_account(alice, name="Mixer", type="crypto-wallet")
    with server.db.tx(unscoped="test") as s:
        sync.record(s, w["id"], [sources.Tx("f" * 64, T2, -1_500, 12_000, {FIRST})])
    with server.db.read(unscoped="test") as s:
        rows = {t.kind: t for t in s.query(Transaction).filter_by(accountId=w["id"])}
    assert rows["transfer-out"].quantity == 0 and rows["transfer-out"].payee == "Network fee"
    assert str(rows["sell"].quantity) == "0.000015"
    assert "this wallet's share" in rows["transfer-out"].memo


def test_a_failing_source_says_what_to_fix_without_naming_an_address(server, alice, monkeypatch):
    w = new_account(alice, name="Cold storage", type="crypto-wallet")
    saved(wallet(alice, w["id"], ZPUB))

    class Down:
        def history(self, addresses):
            raise sources.SourceError("https://mempool.space/api didn't answer (ConnectTimeout).")

    monkeypatch.setattr(sync, "source", lambda srv, s: Down())
    r = alice.post(f"/ui/api/accounts/{w['id']}/wallet/sync")
    assert r.status_code == 502 and r.json()["code"] == "source-failed"
    assert FIRST not in r.text
    with pytest.raises(sources.SourceError):
        sync.sync_all(server)


def test_the_stub_source_gives_dev_wallets_a_history(server, alice, admin_client):
    from moolakata import settings

    server.config = dataclasses.replace(server.config, stubs=True)
    w = new_account(alice, name="Cold storage", type="crypto-wallet")
    saved(wallet(alice, w["id"], ZPUB))
    # The stub too waits for Settings › Bitcoin (S16.7, S17.7), and is a source saved there.
    with server.db.tx(unscoped="test") as s:
        s.delete(settings.row_of(s, "bitcoinSource"))
    assert sync.sync_all(server) is None and sync_count(server, w["id"]) == 0
    assert save_settings(admin_client, {"bitcoinSource": "stub"}).status_code == 200
    sync.sync_all(server)
    v = alice.get(f"/ui/api/accounts/{w['id']}/wallet").json()
    assert v["used"] > 0 and v["checkedAt"]
    first = sync_count(server, w["id"])
    sync.sync_all(server)
    assert sync_count(server, w["id"]) == first > 0


def sync_count(server, account_id):
    from sqlalchemy import func, select

    from moolakata.store.entities.accounts import Transaction

    with server.db.read(unscoped="test") as s:
        return s.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.accountId == account_id, Transaction.fitId.like("btc:%"))
        )


def test_esplora_transactions_are_netted_over_the_wallets_addresses():
    t = sources._esplora_tx(
        {
            "txid": "e" * 64,
            "fee": 1_000,
            "status": {"confirmed": True, "block_time": 1_780_000_000},
            "vin": [{"prevout": {"scriptpubkey_address": FIRST, "value": 50_000_000}}],
            "vout": [
                {"scriptpubkey_address": "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy", "value": 20_000_000},
                {"scriptpubkey_address": CHANGE, "value": 29_999_000},
            ],
        },
        {FIRST, CHANGE},
    )
    assert (t.net, t.fee, t.addresses) == (-20_001_000, 1_000, {FIRST, CHANGE})
    assert t.confirmedAt == dt.datetime.fromtimestamp(1_780_000_000, dt.UTC)


def _raw(ins, outs, segwit=False) -> bytes:
    b = (2).to_bytes(4, "little") + (b"\x00\x01" if segwit else b"")
    b += bytes([len(ins)])
    for txid, idx in ins:
        b += bytes.fromhex(txid)[::-1] + idx.to_bytes(4, "little") + b"\x00" + b"\xff" * 4
    b += bytes([len(outs)])
    for script, value in outs:
        b += value.to_bytes(8, "little") + bytes([len(script)]) + script
    if segwit:
        b += b"\x00" * len(ins)
    return b + b"\x00" * 4


def test_an_electrum_servers_history_is_read_from_raw_transactions(monkeypatch):
    first, change = keys.script_of(FIRST), keys.script_of(CHANGE)
    other = keys.script_of("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy")
    fund = _raw([("11" * 32, 0)], [(first, 50_000_000)], segwit=True)
    spend = _raw([("ab" * 32, 0)], [(other, 20_000_000), (change, 29_999_000)], segwit=True)
    header = bytes(68) + (1_780_000_000).to_bytes(4, "little") + bytes(8)
    hist = {
        first: [
            {"tx_hash": "ab" * 32, "height": 900_000},
            {"tx_hash": "cd" * 32, "height": 900_100},
        ],
        change: [{"tx_hash": "cd" * 32, "height": 900_100}],
    }
    import hashlib

    by_hash = {hashlib.sha256(s).digest()[::-1].hex(): v for s, v in hist.items()}

    def call(self, method, *params):
        if method == "blockchain.scripthash.get_history":
            return by_hash.get(params[0], [])
        if method == "blockchain.block.header":
            return header.hex()
        if method == "blockchain.headers.subscribe":
            return {"height": 900_105}
        if method == "blockchain.transaction.get":
            return {
                "ab" * 32: fund,
                "cd" * 32: spend,
                "11" * 32: _raw([("22" * 32, 0)], [(other, 1)]),
            }[params[0]].hex()
        raise AssertionError(method)

    monkeypatch.setattr(sources.Electrum, "call", call)
    e = sources.Electrum(sources.Config(kind="electrum", host="node.lan"), guard=None)
    got = {t.txid: (t.net, t.fee, t.confirmations) for t in e.history([FIRST, SECOND, CHANGE])}
    assert got == {"ab" * 32: (50_000_000, 0, 106), "cd" * 32: (-20_001_000, 1_000, 6)}


def test_core_gets_the_keys_as_watch_only_descriptors():
    from moolakata.store.entities.accounts import WalletKey

    k = WalletKey(id="WKey_x", accountId="a", kind="xpub", value=ZPUB, script="p2wpkh")
    (recv, top), (chg, _) = sources.descriptors(k, 24)
    assert recv.startswith("wpkh(xpub6") and recv.endswith("/0/*)") and top == 24
    assert chg.endswith("/1/*)")
    y = WalletKey(id="WKey_y", accountId="a", kind="xpub", value=YPUB, script="p2sh-p2wpkh")
    assert sources.descriptors(y, 3)[0][0].startswith("sh(wpkh(xpub")
    a = WalletKey(id="WKey_z", accountId="a", kind="address", value=FIRST, script="p2wpkh")
    assert sources.descriptors(a, None) == [(f"addr({FIRST})", None)]


def test_a_named_node_is_reachable_and_a_public_explorer_is_not_named():
    assert sources.Config().hosts() == (["mempool.space"], [])
    own = sources.Config(esploraUrl="http://192.168.1.20:3006/api")
    assert own.hosts() == (["192.168.1.20"], ["192.168.1.20"])
    node = sources.Config(kind="electrum", host="umbrel.local")
    assert node.hosts() == (["umbrel.local"], ["umbrel.local"])


def test_settings_bitcoin_keeps_the_password_secret_and_tests_the_source(server, admin_client):
    c = admin_client
    r = save_settings(
        c, {"bitcoinSource": "core", "bitcoinNodeHost": "192.168.1.20", "bitcoinNodePort": 8332}
    )
    assert r.status_code == 200, r.text
    r = save_settings(c, {"bitcoinPassword": "rpc-pass-1"})
    assert r.status_code == 200 and "rpc-pass-1" not in r.text
    v = c.get("/ui/api/settings/bitcoin").json()
    assert v["password"]["setBy"] and "rpc-pass-1" not in str(v)
    with server.db.read(unscoped="test") as s:
        cfg = sync.config(s, server.keys.secrets)
    assert (cfg.kind, cfg.host, cfg.port, cfg.password) == (
        "core",
        "192.168.1.20",
        8332,
        "rpc-pass-1",
    )
    bad = save_settings(c, {"bitcoinSource": "infura"})
    assert bad.status_code == 422
    stub = save_settings(c, {"bitcoinSource": "stub"})
    assert stub.status_code == 422, "the stub is dev mode's"
    server.config = dataclasses.replace(server.config, stubs=True)
    r = c.post("/ui/api/settings/bitcoin/test")
    assert r.status_code == 200 and "answered" in r.json()["answer"]
    # A new host clears the password, so it is never sent there (S16.7).
    assert save_settings(c, {"bitcoinNodeHost": "192.168.1.30"}).status_code == 200
    assert c.get("/ui/api/settings/bitcoin").json()["password"] is None


# ---------- the rest (S1.6.2.4, S1.6.2.7, S1.7.1)


def test_a_transfer_between_the_owners_wallets_carries_its_lots(server, alice, monkeypatch):
    from moolakata import ids
    from moolakata.store.entities.accounts import Lot, Transaction
    from moolakata.store.repos import ledger as repo

    one = new_account(alice, name="Hot wallet", type="crypto-wallet")
    two = new_account(alice, name="Cold storage", type="crypto-wallet")
    with server.db.tx(unscoped="test") as s:
        btc = repo.instrument(s, "BTC", "Bitcoin", "crypto")
        buy = Transaction(
            id=ids.new_id("Txn"),
            accountId=one["id"],
            date=dt.date(2025, 1, 5),
            kind="transfer-in",
            amount=0,
            instrumentId=btc.id,
            quantity=D("0.3"),
        )
        s.add(buy)
        s.flush()
        s.add(
            Lot(
                id=ids.new_id("Lot"),
                accountId=one["id"],
                instrumentId=btc.id,
                transactionId=buy.id,
                acquiredOn=dt.date(2025, 1, 5),
                quantity=D("0.3"),
                costBasis=D("27000"),
            )
        )
        for acct, kind, day in ((one, "transfer-out", 10), (two, "transfer-in", 11)):
            s.add(
                Transaction(
                    id=ids.new_id("Txn"),
                    accountId=acct["id"],
                    date=dt.date(2026, 6, day),
                    kind=kind,
                    amount=0,
                    instrumentId=btc.id,
                    quantity=D("0.1"),
                    fitId=f"btc:{kind}",
                )
            )
        from moolakata.bitcoin import transfers

        users = alice.get("/ui/api/session").json()["user"]["id"]
        assert transfers.propose(s, users) == 1
    [pair] = alice.get("/ui/api/transfers/bitcoin").json()["items"]
    assert (pair["fromAccount"], pair["toAccount"], pair["sats"]) == (
        "Hot wallet",
        "Cold storage",
        10_000_000,
    )
    r = alice.post(
        f"/ui/api/transfers/bitcoin/{pair['id']}",
        json={"confirm": True},
        headers={"If-Match": f'"{pair["version"]}"'},
    )
    assert r.status_code == 200 and r.json() == []
    held = {
        p["accountName"]: p
        for p in alice.get("/ui/api/positions").json()["open"]
        if p["symbol"] == "BTC"
    }
    cold = held["Cold storage"]
    assert (cold["quantity"], cold["cost"]) == ("0.1", 9000), "the basis came with the coins"
    assert cold["lots"][0]["acquiredOn"] == "2025-01-05", "and the day they were acquired"
    assert held["Hot wallet"]["cost"] == 18000


def test_a_transaction_that_leaves_the_chain_is_marked_and_kept_or_deleted(
    server, alice, monkeypatch
):
    w = new_account(alice, name="Cold storage", type="crypto-wallet")
    saved(wallet(alice, w["id"], ZPUB))
    fake = Fake(keys.extended(ZPUB).address(0, 19))
    monkeypatch.setattr(sync, "source", lambda srv, s: fake)
    alice.post(f"/ui/api/accounts/{w['id']}/wallet/sync")

    class Reorged(Fake):
        def history(self, addresses):
            return [t for t in super().history(addresses) if t.txid != "a" * 64]

    monkeypatch.setattr(sync, "source", lambda srv, s: Reorged(fake.far))

    def gone():
        alice.post(f"/ui/api/accounts/{w['id']}/wallet/sync")
        items = alice.get("/ui/api/transactions", params={"account": w["id"]}).json()["items"]
        return [t for t in items if t["offChainAt"]]

    assert gone() == [], "one read that misses it isn't enough"
    assert [t["quantity"] for t in gone()] == ["0.5"], "two in a row: marked, never deleted"
    from moolakata import alerts

    alerts.evaluate(server)
    titles = [a["title"] for a in alice.get("/ui/api/alerts").json()["open"]]
    assert "Cold storage: a bitcoin transaction is no longer on the chain" in titles
    t = alice.get("/ui/api/transactions", params={"account": w["id"]}).json()["items"]
    t = next(x for x in t if x["offChainAt"])
    r = alice.post(
        f"/ui/api/transactions/{t['id']}/keep", headers={"If-Match": f'"{t["version"]}"'}
    )
    assert r.status_code == 200 and r.json()["offChainAt"] is None
    assert gone() == [] and gone() == [], "a transaction kept stays kept"


def test_an_address_two_keys_derive_is_watched_once(server, alice):
    # The same zpub typed with one of its own addresses: neither is refused, nor stops a sync.
    w = new_account(alice, name="Cold storage", type="crypto-wallet")
    first = keys.extended(ZPUB).address(0, 0)
    saved(wallet(alice, w["id"], f"{first}\n{ZPUB}"))
    view = alice.get(f"/ui/api/accounts/{w['id']}/wallet").json()
    watched = [a["address"] for a in view["addresses"]]
    assert watched.count(first) == 1


def test_one_wallet_failing_leaves_the_others_read(server, alice, monkeypatch):
    one = new_account(alice, name="One", type="crypto-wallet")
    two = new_account(alice, name="Two", type="crypto-wallet")
    read = []

    def sync_one(srv, account_id):
        read.append(account_id)
        if account_id == one["id"]:
            raise RuntimeError("an answer it couldn't read")

    monkeypatch.setattr(sync, "sync_account", sync_one)
    with pytest.raises(sync.SourceError):
        sync.sync_all(server)
    assert set(read) == {one["id"], two["id"]}


def test_a_node_certificate_is_trusted_once_confirmed(server, admin_client):
    from moolakata import alerts, settings

    with server.db.tx(unscoped="test") as s:
        settings.put(s, "bitcoinNodeCertOffered", "ab" * 32, None)
    alerts.evaluate(server)
    titles = [a["title"] for a in admin_client.get("/ui/api/alerts").json()["open"]]
    assert "The bitcoin node's certificate changed" in titles
    r = admin_client.post("/ui/api/settings/bitcoin/certificate", json={"sha256": "nope"})
    assert r.json()["code"] == "fingerprint-invalid"
    v = admin_client.post("/ui/api/settings/bitcoin/certificate", json={"sha256": "AB" * 32}).json()
    assert (v["certificate"], v["certificateOffered"]) == ("ab" * 32, None)
    alerts.evaluate(server)
    titles = [a["title"] for a in admin_client.get("/ui/api/alerts").json()["open"]]
    assert "The bitcoin node's certificate changed" not in titles


def test_no_wallet_is_read_until_settings_bitcoin_is_saved(server, alice):
    # S16.7, R3.5: nothing asked of a public explorer before an admin chooses it.
    from moolakata import settings
    from moolakata.bitcoin import sync

    w = new_account(alice, name="Cold storage", type="crypto-wallet")
    saved(wallet(alice, w["id"], ZPUB))
    with server.db.tx(unscoped="test") as s:
        s.delete(settings.row_of(s, "bitcoinSource"))
    r = alice.post(f"/ui/api/accounts/{w['id']}/wallet/sync")
    assert r.status_code == 409 and r.json()["code"] == "bitcoin-not-set"
    assert sync.sync_all(server) is None
    with server.db.tx(unscoped="test") as s:
        settings.put(s, "bitcoinSource", "esplora", None)
    with server.db.read(unscoped="test") as s:
        assert sync.chosen(server, s)


def test_saving_the_suggested_source_turns_reading_on(server, admin_client):
    """CR3-62: the section's first save writes the source at its default, mempool.space, and
    that is what turns wallet reading on (S16.7)."""
    from edits import save_settings

    from moolakata import settings

    with server.db.tx(unscoped="test") as s:
        s.delete(settings.row_of(s, "bitcoinSource"))
    assert settings.DEFINITIONS["bitcoinSource"].default == "esplora"
    assert save_settings(admin_client, {"bitcoinSource": "esplora"}).status_code == 200
    with server.db.read(unscoped="test") as s:
        assert sync.chosen(server, s)


def test_a_wallets_keys_are_bounded(alice):
    # B37: the text and the number of keys and addresses are capped, so no wallet stalls the
    # server (S1.6.1).
    w = new_account(alice, name="Huge", type="crypto-wallet")
    r = wallet(alice, w["id"], "x" * 200_001)
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "too-long"
    from moolakata.ui import wallets

    z = keys.extended(ZPUB)
    lines = "\n".join(z.address(0, i) for i in range(wallets.MAX_ENTRIES + 1))
    r = wallet(alice, w["id"], lines)
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "too-many", r.text


# ---------- a key taken out (S1.6.1.3, CR3-20)

TYPED = "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"


def _off_chain(server, account_id) -> dict[str, tuple[bool, bool]]:
    """Each recorded transaction by txid: (marked no longer on the chain, has a key link)."""
    from sqlalchemy import select

    from moolakata.store.entities.accounts import Transaction, TransactionWalletKey

    with server.db.read(unscoped="test") as s:
        linked = set(s.scalars(select(TransactionWalletKey.transactionId)))
        return {
            r.fitId[4:]: (r.offChainAt is not None, r.id in linked)
            for r in s.scalars(
                select(Transaction).where(
                    Transaction.accountId == account_id, Transaction.fitId.like("btc:%")
                )
            )
        }


def test_taking_a_key_out_never_marks_its_transactions_off_the_chain(server, alice, monkeypatch):
    """The review's case: a zpub's three transactions recorded, the zpub replaced by another
    key, two reads: none is marked, so no alert invites deleting coins still there. Typed in
    again, it is read again, and a transaction the chain dropped meanwhile is marked."""
    w = new_account(alice, name="Cold storage", type="crypto-wallet")
    saved(wallet(alice, w["id"], ZPUB))
    fake = Fake(keys.extended(ZPUB).address(0, 19))
    monkeypatch.setattr(sync, "source", lambda srv, s: fake)
    assert sync.sync_account(server, w["id"]) == 3
    saved(wallet(alice, w["id"], YPUB))
    sync.sync_account(server, w["id"])
    sync.sync_account(server, w["id"])
    assert _off_chain(server, w["id"]) == dict.fromkeys(
        ["a" * 64, "b" * 64, "c" * 64], (False, True)
    )

    class Reorged(Fake):
        def history(self, addresses):
            return [t for t in super().history(addresses) if t.txid != "a" * 64]

    monkeypatch.setattr(sync, "source", lambda srv, s: Reorged(fake.far))
    sync.sync_account(server, w["id"])  # a miss while unread is no miss
    saved(wallet(alice, w["id"], ZPUB))
    sync.sync_account(server, w["id"])
    assert not _off_chain(server, w["id"])["a" * 64][0], "one read that misses it isn't enough"
    sync.sync_account(server, w["id"])
    assert _off_chain(server, w["id"])["a" * 64] == (True, True)


class Chain:
    """A chain the test changes, read as an explorer reads it: each transaction touching
    `addresses` that is still on it."""

    def __init__(self, txs: list[sources.Tx]):
        self.all = {t.txid: t for t in txs}
        self.on = set(self.all)

    def test(self):
        return "Chain answered"

    def history(self, addresses):
        asked = set(addresses)
        return [dataclasses.replace(self.all[t]) for t in sorted(self.on)
                if self.all[t].addresses & asked]  # fmt: skip


@pytest.mark.parametrize("seed", range(6))
def test_no_transaction_still_on_the_chain_is_ever_marked_whatever_keys_come_and_go(
    server, alice, monkeypatch, seed
):
    """CR3-20's category, generated: keys taken out and typed in again, transactions leaving
    the chain and coming back, reads between. A model says what each read must leave marked:
    a transaction is judged only while a key that read it is in the wallet, and marked after
    two judged reads in a row miss it; one back on the chain is unmarked. Every recorded
    transaction is linked to a key."""
    import random

    rnd = random.Random(seed)
    z = keys.extended(ZPUB)
    r0, r1 = z.address(0, 0), z.address(0, 1)
    of_key = {ZPUB: {r0, r1}, TYPED: {TYPED}}
    chain = Chain([
        sources.Tx("1" * 64, T1, 1_000, 0, {r0}),
        sources.Tx("2" * 64, T1, 2_000, 0, {r1}),
        sources.Tx("3" * 64, T1, 3_000, 0, {TYPED}),
        sources.Tx("4" * 64, T2, 4_000, 0, {r0, TYPED}),
    ])  # fmt: skip
    monkeypatch.setattr(sync, "source", lambda srv, s: chain)
    w = new_account(alice, name="Cold storage", type="crypto-wallet")
    live = [ZPUB, TYPED]
    saved(wallet(alice, w["id"], "\n".join(live)))
    read_by: dict[str, set[str]] = {}  # txid: the keys that have read it
    missed: dict[str, int] = {}
    marked: set[str] = set()
    for step in range(12):
        op = rnd.choice(["keys", "drop", "back", "read", "read"])
        if op == "keys":
            live = rnd.choice([[ZPUB], [TYPED], [ZPUB, TYPED]])
            saved(wallet(alice, w["id"], "\n".join(live)))
        elif op == "drop" and chain.on:
            chain.on.discard(rnd.choice(sorted(chain.on)))
        elif op == "back":
            chain.on = set(chain.all)
        else:
            sync.sync_account(server, w["id"])
            watched = set().union(*(of_key[k] for k in live))
            for txid, t in chain.all.items():
                if txid in chain.on and t.addresses & watched:
                    read_by.setdefault(txid, set()).update(
                        k for k in live if of_key[k] & t.addresses
                    )
                    missed[txid] = 0
                    marked.discard(txid)
                elif txid not in read_by or txid in marked:
                    continue
                elif read_by[txid] & set(live):
                    missed[txid] = missed.get(txid, 0) + 1
                    if missed[txid] >= 2:
                        marked.add(txid)
                else:
                    missed[txid] = 0
            got = _off_chain(server, w["id"])
            assert set(got) == set(read_by), f"step {step}"
            assert {t for t, (m, _) in got.items() if m} == marked, f"step {step}: {op}"
            assert all(linked for _, linked in got.values()), "every one linked to a key"
            assert not marked & chain.on, "nothing still on the chain is marked"


def _links(server, account_id) -> set[str]:
    """The accounts whose keys the account's transactions are linked to."""
    from sqlalchemy import select

    from moolakata.store.entities.accounts import Transaction, TransactionWalletKey, WalletKey

    with server.db.read(unscoped="test") as s:
        return set(
            s.scalars(
                select(WalletKey.accountId)
                .join(TransactionWalletKey)
                .join(Transaction, Transaction.id == TransactionWalletKey.transactionId)
                .where(Transaction.accountId == account_id)
            )
        )


def test_a_transfer_between_two_wallets_is_linked_to_each_ones_own_keys(server, alice, monkeypatch):
    """One transaction, recorded in both wallets it moved coins between: each record is linked
    to its own wallet's keys only, so taking a key out of one never judges the other's."""
    r0 = keys.extended(ZPUB).address(0, 0)
    chain = Chain([sources.Tx("5" * 64, T1, 1_000, 0, {r0, TYPED})])
    monkeypatch.setattr(sync, "source", lambda srv, s: chain)
    hot = new_account(alice, name="Hot wallet", type="crypto-wallet")
    cold = new_account(alice, name="Cold storage", type="crypto-wallet")
    saved(wallet(alice, hot["id"], ZPUB))
    saved(wallet(alice, cold["id"], TYPED))
    sync.sync_account(server, hot["id"])
    sync.sync_account(server, cold["id"])
    sync.sync_account(server, hot["id"])
    assert _links(server, hot["id"]) == {hot["id"]}
    assert _links(server, cold["id"]) == {cold["id"]}


def test_a_deleted_link_brings_a_transaction_no_key(server, alice, monkeypatch):
    """A link marked deleted counts as none: the transaction is judged again, as one no key
    brought is (CR3-20), and marked once two reads miss it."""
    from sqlalchemy import update

    from moolakata import clock
    from moolakata.store.entities.accounts import TransactionWalletKey

    r0 = keys.extended(ZPUB).address(0, 0)
    chain = Chain([sources.Tx("6" * 64, T1, 1_000, 0, {r0})])
    monkeypatch.setattr(sync, "source", lambda srv, s: chain)
    w = new_account(alice, name="Cold storage", type="crypto-wallet")
    saved(wallet(alice, w["id"], ZPUB))
    sync.sync_account(server, w["id"])
    saved(wallet(alice, w["id"], TYPED))  # the key that read it taken out
    with server.db.tx(unscoped="test") as s:
        s.execute(update(TransactionWalletKey).values(deletedAt=clock.now()))
    chain.on.clear()
    sync.sync_account(server, w["id"])
    sync.sync_account(server, w["id"])
    assert _off_chain(server, w["id"])["6" * 64][0], "judged, and marked"


def test_a_read_judges_only_its_own_wallets_live_transactions(server, alice, monkeypatch):
    """Another wallet's transactions are not in this one's read, nor is a deleted one: neither
    is ever counted as missed by it, even one with no key link, which a read judges."""
    from sqlalchemy import select, update

    from moolakata import clock
    from moolakata.store.entities.accounts import Transaction, TransactionWalletKey

    r0 = keys.extended(ZPUB).address(0, 0)
    chain = Chain([sources.Tx("7" * 64, T1, 1_000, 0, {TYPED}),
                   sources.Tx("8" * 64, T1, 2_000, 0, {r0})])  # fmt: skip
    monkeypatch.setattr(sync, "source", lambda srv, s: chain)
    hot = new_account(alice, name="Hot wallet", type="crypto-wallet")
    cold = new_account(alice, name="Cold storage", type="crypto-wallet")
    saved(wallet(alice, hot["id"], ZPUB))
    saved(wallet(alice, cold["id"], TYPED))
    sync.sync_account(server, hot["id"])
    sync.sync_account(server, cold["id"])
    with server.db.tx(unscoped="test") as s:
        s.execute(
            update(Transaction)
            .where(Transaction.fitId == "btc:" + "8" * 64)
            .values(deletedAt=clock.now())
        )
    chain.on.discard("8" * 64)
    with server.db.tx(unscoped="test") as s:
        s.execute(update(TransactionWalletKey).values(deletedAt=clock.now()))
    for _ in range(3):
        sync.sync_account(server, hot["id"])
    with server.db.read(unscoped="test") as s:
        rows = s.scalars(select(Transaction).where(Transaction.fitId.like("btc:%")))
        got = {r.fitId[4:5]: (r.offChainMissedAt, r.offChainAt) for r in rows}
    assert got == {"7": (None, None), "8": (None, None)}


def test_a_kept_transaction_leaves_the_others_judged(server, alice, monkeypatch):
    """One the owner kept stays kept, and the read goes on to judge those after it."""
    from sqlalchemy import update

    from moolakata import clock
    from moolakata.store.entities.accounts import Transaction

    r0 = keys.extended(ZPUB).address(0, 0)
    chain = Chain([sources.Tx("1" * 64, T1, 1_000, 0, {r0}),
                   sources.Tx("2" * 64, T2, 2_000, 0, {r0})])  # fmt: skip
    monkeypatch.setattr(sync, "source", lambda srv, s: chain)
    w = new_account(alice, name="Cold storage", type="crypto-wallet")
    saved(wallet(alice, w["id"], ZPUB))
    sync.sync_account(server, w["id"])
    with server.db.tx(unscoped="test") as s:
        s.execute(
            update(Transaction)
            .where(Transaction.fitId == "btc:" + "1" * 64)
            .values(offChainKeptAt=clock.now())
        )
    chain.on.clear()
    sync.sync_account(server, w["id"])
    sync.sync_account(server, w["id"])
    got = _off_chain(server, w["id"])
    assert (got["1" * 64][0], got["2" * 64][0]) == (False, True)
