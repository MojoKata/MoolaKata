"""Bitcoin moved between the owner's wallets (requirements S1.7.1): a pair turned down is never
proposed again."""

import datetime as dt

from conftest import make_user, sign_in
from test_accounts import new_account

from moolakata.bitcoin import sources, sync
from moolakata.bitcoin import transfers as btcmatch

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
