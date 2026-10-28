"""Adjusted contracts (requirements S3.10): a whole-number split taking open options with it,
an adjustment from the OCC's memo with a new root and deliverable, assignment by deliverable,
and OCC tickers on import. The lot carries over: nothing is sold."""

import datetime as dt
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import remove, saved
from test_accounts import new_account
from test_options import opt

from moolakata import clock
from moolakata.options.adjust import parse_occ

T0 = dt.datetime(2026, 10, 13, 12, tzinfo=dt.UTC)


@pytest.fixture
def alice(server):
    clock.fix(T0)
    make_user(server, "alice")
    yield sign_in(server, "alice")
    clock.fix(None)


def held(c):
    return {
        r["symbol"]: (r["quantity"], r["cost"], r["lots"][0]["acquiredOn"])
        for r in c.get("/ui/api/positions").json()["open"]
    }


def test_a_whole_split_takes_the_open_options_with_it_and_undoes_with_it(alice):
    a = new_account(alice, type="brokerage")["id"]
    assert (
        opt(alice, a, "sell-to-open", "2026-09-01", "6.40", contracts="2", fees="0").status_code
        == 201
    )
    r = alice.post(
        "/ui/api/transactions",
        json={
            "accountId": a,
            "date": "2026-10-01",
            "kind": "split",
            "symbol": "MSFT",
            "amount": "0",
            "splitRatio": "2",
        },
    )
    assert r.status_code == 201, r.text
    after = held(alice)
    assert after == {"MSFT 20NOV26 240 P": (-4, -1280, "2026-09-01")}, "basis and days carry"
    gains = alice.get("/ui/api/positions").json()["closed"]
    assert gains == [], "nothing was sold"
    split = r.json()
    saved(remove(alice, "Txn", split))
    assert held(alice) == {"MSFT 20NOV26 480 P": (-2, -1280, "2026-09-01")}


def test_an_adjustment_from_the_memo_changes_root_and_deliverable(alice):
    a = new_account(alice, type="brokerage")["id"]
    opt(alice, a, "sell-to-open", "2026-09-01", "3.00", contracts="2", fees="0")
    [g] = alice.get("/ui/api/options/adjustable").json()["items"]
    [cn] = g["contracts"]
    assert (g["underlying"], cn["held"]) == ("MSFT", ["Short 2 in Checking"])
    r = alice.post(
        "/ui/api/options/adjust",
        json={
            "date": "2026-10-05",
            "contracts": [
                {
                    "instrumentId": cn["instrumentId"],
                    "root": "MSFT1",
                    "strike": "480",
                    "deliverable": [{"symbol": "MSFT", "shares": "150"}],
                }
            ],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"contracts": 1, "accounts": 1}
    pos = held(alice)
    assert pos == {"MSFT1 20NOV26 480 P": (-2, -600, "2026-09-01")}
    # Assigned: it buys its deliverable, 150 shares a contract, at the strike on 100.
    row = next(r for r in alice.get("/ui/api/positions").json()["open"])
    r = alice.post(
        f"/ui/api/accounts/{a}/options/{row['instrumentId']}/settle",
        json={"how": "assign", "date": "2026-11-20"},
    )
    assert r.status_code in (200, 201), r.text
    after = held(alice)
    qty, cost, _ = after["MSFT"]
    assert qty == 300 and D(str(cost)) == D("96000") - D("600")


def test_occ_tickers_are_read_with_their_root():
    assert parse_occ("O:XYZ1270115C00060000") == ("XYZ1", dt.date(2027, 1, 15), "call", D("60"))
    assert parse_occ("MSFT  261120P00480000") == ("MSFT", dt.date(2026, 11, 20), "put", D("480"))
    assert parse_occ("Microsoft Corp") is None
