"""Keeping wallets current (requirements S1.6.2): which source a read asks, Bitcoin Core's
watch-only wallet, the rounds a read extends the gap by, and how the hourly read stops or fails."""

import datetime as dt
import threading
import types
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import saved, wallet
from sqlalchemy import select
from test_accounts import new_account

from moolakata import settings
from moolakata.bitcoin import sources, sync
from moolakata.store.entities.accounts import Transaction
from moolakata.store.entities.prices import Price
from moolakata.store.repos import ledger as repo

ZPUB = (
    "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868Rv"
    "UUkgDKf31mGDtKsAYz2oz2AGutZYs"
)
FIRST = "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"  # receive 0
LONE = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"  # an address typed alone
T1 = dt.datetime(2026, 3, 2, 15, tzinfo=dt.UTC)


def _source(server, kind: str) -> None:
    with server.db.tx(unscoped="test: Settings › Bitcoin saved") as s:
        settings.put(s, "bitcoinSource", kind, None)


@pytest.fixture
def jane(server):
    _source(server, "esplora")
    make_user(server, "jane")
    return sign_in(server, "jane")


def _wallet(c, text: str = ZPUB, gap: int | None = None) -> str:
    w = new_account(c, name="Cold storage", type="crypto-wallet")
    saved(wallet(c, w["id"], text, gap))
    return w["id"]


def test_the_stub_is_dev_modes_and_any_other_source_is_made_from_its_settings(server):
    _source(server, "stub")
    with server.db.read(unscoped="test") as s, pytest.raises(sources.SourceError) as e:
        sync.source(server, s)
    assert "dev mode's" in str(e.value)
    _source(server, "esplora")
    with server.db.read(unscoped="test") as s:
        assert isinstance(sync.source(server, s), sources.Esplora)


def test_no_wallet_is_read_now_until_settings_bitcoin_is_saved(server, jane):
    w = _wallet(jane)
    with server.db.tx(unscoped="test") as s:
        s.delete(settings.row_of(s, "bitcoinSource"))
    with pytest.raises(sources.SourceError, match="Settings › Bitcoin"):
        sync.sync_account(server, w)


class Core(sources.Core):
    """Bitcoin Core's watch-only wallet, as its RPC answers: what was imported, and its
    history, with an address that received but no transaction this read lists."""

    def __init__(self):
        self.imported: list[tuple[str, list]] = []

    def wallet(self, name, wanted):
        self.imported.append((name, wanted))

    def history_of(self, name):
        return [sources.Tx("a" * 64, T1, 50_000, 0, {FIRST})], {LONE}


def test_bitcoin_core_is_given_each_keys_descriptors_and_its_history_read(
    server, jane, monkeypatch
):
    w = _wallet(jane, f"{ZPUB}\n{LONE}")
    core = Core()
    monkeypatch.setattr(sync, "source", lambda srv, s: core)
    assert sync.sync_account(server, w) == 1
    (name, wanted), *_ = core.imported
    assert name == f"moolakata-{w}"
    assert (f"addr({LONE})", None) in wanted
    ranged = [d for d, top in wanted if top is not None]
    assert len(ranged) == 2 and all(top == 19 for d, top in wanted if top is not None), (
        "a key's two chains, ranged to the highest index derived"
    )
    v = jane.get(f"/ui/api/accounts/{w}/wallet").json()
    assert v["used"] == 2, "the one the transaction touched and the one Core says received"


class Growing:
    """An explorer that finds the last address asked for used, every time: the wallet's gap
    never closes."""

    def __init__(self):
        self.asked = 0

    def history(self, addresses):
        self.asked += 1
        return [sources.Tx(f"{self.asked:064x}", None, 1, 0, {addresses[-1]})]


def test_a_read_extends_the_gap_at_most_ten_rounds(server, jane, monkeypatch):
    w = _wallet(jane, gap=1)  # one address more a round, so the rounds are quick
    src = Growing()
    monkeypatch.setattr(sync, "source", lambda srv, s: src)
    assert sync.sync_account(server, w) == 0, "nothing confirmed"
    assert src.asked == sync.ROUNDS


def test_the_hourly_read_stops_when_the_server_does(server, jane, monkeypatch):
    _wallet(jane)
    read = []
    monkeypatch.setattr(sync, "sync_account", lambda srv, a: read.append(a))
    stop = threading.Event()
    stop.set()
    assert sync.sync_all(server, types.SimpleNamespace(stop=stop)) is None
    assert read == []


def test_a_changed_node_certificate_is_kept_for_an_admin_and_reported(server, jane, monkeypatch):
    _wallet(jane)
    sha = "ab" * 32

    def changed(srv, account_id):
        raise sources.CertificateChanged("the node's certificate changed", sha)

    monkeypatch.setattr(sync, "sync_account", changed)
    with pytest.raises(sources.SourceError, match="certificate changed"):
        sync.sync_all(server)
    with server.db.read(unscoped="test") as s:
        assert settings.get(s, "bitcoinNodeCertOffered") == sha


def test_a_fee_valued_later_moves_its_own_wallets_cash_only(server, jane):
    """Two of the owner's wallets both spend in one transaction: each fee is valued on its own
    wallet once bitcoin has a price (S1.6.2.6), its cash beside it."""
    from moolakata.prices import refresh

    refresh.install()
    one = new_account(jane, name="One", type="crypto-wallet")["id"]
    two = new_account(jane, name="Two", type="crypto-wallet")["id"]
    with server.db.tx(unscoped="test: a read, before a price") as s:
        sync.record(s, one, [sources.Tx("f" * 64, T1, -11_000, 1_000)])
        sync.record(s, two, [sources.Tx("f" * 64, T1, -2_000, 2_000)])
    with server.db.tx(unscoped="test: a price, and the next read") as s:
        btc = repo.instrument(s, "BTC", "Bitcoin", "crypto")
        s.add(Price(instrumentId=btc.id, date=T1.date(), close=D("100000"), source="test"))
        s.flush()
        assert sync.revalue_fees(s, two) == 1
        assert sync.revalue_fees(s, one) == 1
    with server.db.read(unscoped="test") as s:
        cash = {t.accountId: t.amount for t in s.scalars(
            select(Transaction).where(Transaction.kind == "fee"))}  # fmt: skip
    assert cash == {one: D("-1.00"), two: D("-2.00")}
