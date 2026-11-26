"""Bitcoin moved between the owner's wallets (requirements S1.7.1): a pair turned down is never
proposed again."""

import datetime as dt

from conftest import make_user, sign_in
from sqlalchemy import select
from test_accounts import new_account

from moolakata.bitcoin import sources, sync
from moolakata.bitcoin import transfers as btcmatch
from moolakata.store.entities.accounts import Transaction, TransferMatch

T1 = dt.datetime(2026, 3, 2, 15, tzinfo=dt.UTC)


def test_a_pair_turned_down_is_not_proposed_again(server):
    make_user(server, "jane")
    jane = sign_in(server, "jane")
    me = jane.get("/ui/api/session").json()["user"]["id"]
    hot = new_account(jane, name="Hot wallet", type="crypto-wallet")["id"]
    cold = new_account(jane, name="Cold storage", type="crypto-wallet")["id"]
    with server.db.tx(unscoped="test: both wallets read") as s:
        sync.record(s, hot, [sources.Tx("a" * 64, T1, -(10_000_000 + 1_000), 1_000)])
        sync.record(s, cold, [sources.Tx("a" * 64, T1, 10_000_000, 0)])
        assert btcmatch.propose(s, me) == 1
    [pair] = jane.get("/ui/api/transfers/bitcoin").json()["items"]
    r = jane.post(
        f"/ui/api/transfers/bitcoin/{pair['id']}",
        json={"confirm": False},
        headers={"If-Match": f'"{pair["version"]}"'},
    )
    assert r.status_code == 200 and r.json() == []
    with server.db.tx(unscoped="test: the next read") as s:
        assert btcmatch.propose(s, me) == 0
    assert jane.get("/ui/api/transfers/bitcoin").json()["items"] == []
    again = jane.post(
        f"/ui/api/transfers/bitcoin/{pair['id']}",
        json={"confirm": True},
        headers={"If-Match": f'"{pair["version"] + 1}"'},
    )
    assert again.status_code == 404, "a pair turned down is answered"


def _two_wallets(server, name="jane"):
    make_user(server, name)
    who = sign_in(server, name)
    me = who.get("/ui/api/session").json()["user"]["id"]
    hot = new_account(who, name="Hot wallet", type="crypto-wallet")["id"]
    cold = new_account(who, name="Cold storage", type="crypto-wallet")["id"]
    return who, me, hot, cold


def _side(s, account_id, fit):
    return s.scalars(
        select(Transaction).where(Transaction.accountId == account_id, Transaction.fitId == fit)
    ).one()


SENT = sources.Tx("a" * 64, T1, -(10_000_000 + 1_000), 1_000)
GOT = sources.Tx("a" * 64, T1, 10_000_000, 0)


def test_two_wallets_sides_pair_by_their_transaction_whatever_their_dates(server):
    _, me, hot, cold = _two_wallets(server)
    with server.db.tx(unscoped="test: both wallets read") as s:
        sync.record(s, hot, [SENT])
        sync.record(s, cold, [GOT])
        _side(s, cold, "btc:" + "a" * 64).date += dt.timedelta(days=9)
        assert btcmatch.propose(s, me) == 1, "one transaction on the chain: days don't matter"


def test_two_different_transactions_never_pair_however_close(server):
    _, me, hot, cold = _two_wallets(server)
    with server.db.tx(unscoped="test: both wallets read") as s:
        sync.record(s, hot, [SENT])
        sync.record(s, cold, [sources.Tx("b" * 64, T1, 10_000_000, 0)])
        assert btcmatch.propose(s, me) == 0, "the same amount on the same day, but not the same"


def test_a_side_with_no_transaction_on_the_chain_pairs_within_days(server):
    _, me, hot, cold = _two_wallets(server)
    with server.db.tx(unscoped="test: a wallet read, a line typed") as s:
        sync.record(s, hot, [SENT])
        sync.record(s, cold, [GOT])
        line = _side(s, cold, "btc:" + "a" * 64)
        line.fitId = None  # as an exchange's line: no transaction on the chain
        line.date += dt.timedelta(days=btcmatch.DAYS + 1)
        assert btcmatch.propose(s, me) == 0, "past the days"
        line.date -= dt.timedelta(days=1)
        assert btcmatch.propose(s, me) == 1, "within them"


def test_the_same_transaction_in_two_owners_wallets_is_never_paired(server):
    _, jane, hot, _ = _two_wallets(server)
    _, bob, _, bobs = _two_wallets(server, "bob")
    with server.db.tx(unscoped="test: each wallet read") as s:
        sync.record(s, hot, [SENT])
        sync.record(s, bobs, [GOT])
        assert btcmatch.propose(s, jane) == 0
        assert btcmatch.propose(s, bob) == 0


def test_a_new_date_never_changes_a_pair_proposed_or_confirmed(server):
    who, me, hot, cold = _two_wallets(server)
    with server.db.tx(unscoped="test: both wallets read") as s:
        sync.record(s, hot, [SENT])
        sync.record(s, cold, [GOT])
        assert btcmatch.propose(s, me) == 1
    [pair] = who.get("/ui/api/transfers/bitcoin").json()["items"]
    with server.db.tx(unscoped="test: re-dated, as a time zone correction does") as s:
        _side(s, hot, "btc:" + "a" * 64).date -= dt.timedelta(days=1)
        assert btcmatch.propose(s, me) == 0
    assert [p["id"] for p in who.get("/ui/api/transfers/bitcoin").json()["items"]] == [pair["id"]]
    r = who.post(
        f"/ui/api/transfers/bitcoin/{pair['id']}",
        json={"confirm": True},
        headers={"If-Match": f'"{pair["version"]}"'},
    )
    assert r.status_code == 200
    with server.db.tx(unscoped="test: re-dated again") as s:
        _side(s, cold, "btc:" + "a" * 64).date += dt.timedelta(days=2)
        assert btcmatch.propose(s, me) == 0
        matches = s.scalars(select(TransferMatch).where(TransferMatch.ownerId == me)).all()
        assert [(m.id, m.state) for m in matches] == [(pair["id"], "confirmed")]
