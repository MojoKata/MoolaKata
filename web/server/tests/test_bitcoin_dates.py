"""A bitcoin transaction's date (requirements S1.6.2.6, S14.9.3): a transaction is a moment on
the chain, its confirmation, and its ledger date is that moment's day in its owner's zone (the
taxpayer whose lots, holding periods and fee sales it makes), never the server's. It is dated
again when the owner's zone changes, except across a closed tax year (S2.8.1).

The year-end case: coins sent at 22:30 Pacific on Dec 31 2026 are 06:30 UTC and 00:30 Chicago
on Jan 1 2027. The server runs in Chicago (TZ)."""

import datetime as dt
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import change, make, saved
from sqlalchemy import select

from moolakata import clock
from moolakata.bitcoin import sources, sync
from moolakata.store.entities.accounts import Transaction
from moolakata.store.entities.prices import Price
from moolakata.store.entities.users import User
from moolakata.store.repos import ledger as repo

AT = dt.datetime(2027, 1, 1, 6, 30, tzinfo=dt.UTC)  # Dec 31 22:30 Pacific, Jan 1 00:30 Chicago
DEC31, JAN1 = dt.date(2026, 12, 31), dt.date(2027, 1, 1)
SENT = sources.Tx("a" * 64, AT, -(10_000_000 + 12_000), 12_000)


@pytest.fixture(autouse=True)
def chicago(monkeypatch):
    monkeypatch.setenv("TZ", "America/Chicago")
    clock.fix(dt.datetime(2027, 3, 1, 15, 0, tzinfo=dt.UTC))
    yield
    clock.fix(None)


@pytest.fixture
def jane(server):
    make_user(server, "jane")
    return sign_in(server, "jane")


def _wallet(c) -> str:
    return make(c, "Acct", name="Cold storage", type="crypto-wallet").json()["id"]


def _zone(server, c, zone: str) -> None:
    with server.db.tx(unscoped="test: the owner's zone") as s:
        s.get(User, c.get("/ui/api/session").json()["user"]["id"]).timeZone = zone


def _dates(server, account_id) -> dict[str, dt.date]:
    with server.db.read(unscoped="test") as s:
        rows = s.scalars(select(Transaction).where(Transaction.accountId == account_id))
        return {t.kind: t.date for t in rows}


def _read(server, account_id, *txs) -> None:
    with server.db.tx(unscoped="test: a read") as s:
        sync.record(s, account_id, list(txs))


def test_a_transaction_is_dated_in_its_owners_zone_not_the_servers(server, jane):
    _zone(server, jane, "America/Los_Angeles")
    w = _wallet(jane)
    _read(server, w, SENT)
    assert _dates(server, w) == {"transfer-out": DEC31, "sell": DEC31, "fee": DEC31}, (
        "the fee's sale lands in 2026, the owner's year"
    )


def test_an_owner_on_auto_has_the_servers_zone(server, jane):
    w = _wallet(jane)
    _read(server, w, SENT)
    assert _dates(server, w) == {"transfer-out": JAN1, "sell": JAN1, "fee": JAN1}


def test_a_zone_change_dates_the_transaction_again_and_values_its_fee_on_the_new_day(server, jane):
    _zone(server, jane, "America/Los_Angeles")
    from moolakata.prices import refresh

    refresh.install()  # stored closes value the fee, as the running server reads them
    w = _wallet(jane)
    with server.db.tx(unscoped="test: a price each day") as s:
        btc = repo.instrument(s, "BTC", "Bitcoin", "crypto")
        s.add(Price(instrumentId=btc.id, date=DEC31, close=D("60000"), source="test"))
        s.add(Price(instrumentId=btc.id, date=JAN1, close=D("70000"), source="test"))
    _read(server, w, SENT)
    with server.db.read(unscoped="test") as s:
        sell = s.scalars(select(Transaction).where(Transaction.kind == "sell")).one()
    assert sell.price == D("60000") and sell.amount == D("7.20")
    _zone(server, jane, "America/New_York")
    _read(server, w, SENT)
    assert _dates(server, w) == {"transfer-out": JAN1, "sell": JAN1, "fee": JAN1}
    with server.db.read(unscoped="test") as s:
        rows = {t.kind: t for t in s.scalars(select(Transaction).where(
            Transaction.accountId == w))}  # fmt: skip
    assert rows["sell"].price == D("70000") and rows["sell"].amount == D("8.40")
    assert rows["fee"].amount == D("-8.40"), "the cash still unchanged"


def test_a_date_typed_by_hand_stays(server, jane):
    w = _wallet(jane)
    got = sources.Tx("b" * 64, AT, 5_000, 0)
    _read(server, w, got)
    with server.db.tx(unscoped="test: the owner types a date") as s:
        t = s.scalars(select(Transaction).where(Transaction.accountId == w)).one()
        t.date = dt.date(2026, 12, 20)
    _zone(server, jane, "America/Los_Angeles")
    _read(server, w, got)
    assert _dates(server, w) == {"transfer-in": dt.date(2026, 12, 20)}


def _close_2026(c) -> None:
    me = c.get("/ui/api/session").json()["user"]["id"]
    book = make(c, "TaxBk", year=2026, filers=[me]).json()
    r = make(c, "Filng", bookId=book["id"], jurisdiction="federal", form="1040",
             progress="filed", filedOn="2027-02-20")  # fmt: skip
    assert r.status_code == 200, r.text


def test_a_zone_change_never_moves_a_transaction_out_of_a_closed_year(server, jane):
    _zone(server, jane, "America/Los_Angeles")
    w = _wallet(jane)
    got = sources.Tx("b" * 64, AT, 5_000, 0)
    # Mid-year, near midnight UTC: Jun 30 in Los Angeles, Jul 1 in New York, both 2026.
    june = sources.Tx("c" * 64, dt.datetime(2026, 7, 1, 4, 30, tzinfo=dt.UTC), 7_000, 0)
    _read(server, w, got, june)
    _close_2026(jane)
    _zone(server, jane, "America/New_York")
    _read(server, w, got, june)
    with server.db.read(unscoped="test") as s:
        dates = {t.fitId: t.date for t in s.scalars(select(Transaction).where(
            Transaction.accountId == w))}  # fmt: skip
    assert dates["btc:" + "b" * 64] == DEC31, "held in the closed year"
    assert dates["btc:" + "c" * 64] == dt.date(2026, 7, 1), "within it, dated again"


def test_a_zone_change_never_moves_a_transaction_into_a_closed_year(server, jane):
    w = _wallet(jane)
    got = sources.Tx("b" * 64, AT, 5_000, 0)
    _read(server, w, got)  # Auto: Chicago, Jan 1 2027
    _close_2026(jane)
    _zone(server, jane, "America/Los_Angeles")
    _read(server, w, got)
    assert _dates(server, w) == {"transfer-in": JAN1}


def test_changing_ones_zone_reads_the_wallets_again(server, jane, monkeypatch):
    asked = []
    monkeypatch.setattr(server.tasks, "run_now", lambda name, ended=None: asked.append(name))
    p = jane.get("/ui/api/profile").json()
    saved(change(jane, "User", p, theme="light"))
    assert asked == [], "no zone changed"
    p = jane.get("/ui/api/profile").json()
    saved(change(jane, "User", p, timeZone="America/Denver"))
    assert asked == [], "no wallet to date"
    _wallet(jane)
    p = jane.get("/ui/api/profile").json()
    saved(change(jane, "User", p, timeZone="America/Chicago"))
    assert asked == ["bitcoin"], "a new zone: the wallets are read, and dated again"
    p = jane.get("/ui/api/profile").json()
    saved(change(jane, "User", p, timeZone="auto"))
    assert asked == ["bitcoin"], "Auto is the server's zone, Chicago: the same days"
