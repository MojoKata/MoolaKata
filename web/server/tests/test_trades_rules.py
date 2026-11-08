"""Option trades, corporate actions and strategies (requirements S3.2, S2.4, S3.5): who may
record or change them and what a refusal says, a symbol as typed, an unnamed strategy's name
and a closed leg's day, through the routes and the save."""

import pytest
from conftest import make_user, sign_in
from edits import change, create, option_trade, remove, saved
from test_accounts import new_account
from test_options import T0, _holding
from test_options import opt as option
from test_strategies import _book_of_legs, _legs, _spread

from moolakata import clock

READ_ONLY = ("share-read-only", "You can read this account but not change it.")


@pytest.fixture(autouse=True)
def frozen():
    """Each test on the day the option tests are on, its contracts not yet expired."""
    clock.fix(T0)
    yield
    clock.fix(None)


@pytest.fixture
def alice(server):
    make_user(server, "alice")
    return sign_in(server, "alice")


def _errors(r):
    return [(e["field"], e["code"], e["message"]) for e in r.json()["errors"]]


def _shared_to_read(server, holding: bool = False):
    """Alice and Bob, with Bob reading Alice's brokerage account: their clients and the
    account, holding 10 FB with `holding` (and FB's instrument then)."""
    from edits import share
    from test_sharing import setup

    u, c = setup(server)
    if holding:
        a, fb = _holding(c["alice"])
    else:
        a, fb = new_account(c["alice"], type="brokerage")["id"], None
    assert share(c["alice"], "account", a, users={u["bob"].id: "read"}).status_code == 200
    return c["alice"], c["bob"], a, fb


# ---- Option trades (S3.2) ----


def test_an_underlying_typed_in_lower_case_is_its_symbol_in_capitals(alice):
    a = new_account(alice, type="brokerage")["id"]
    t = saved(option_trade(alice, a, "2026-09-02", "sell-to-open", " msft ", "put", "480",
                           "2026-11-20", "1", "6.40"))  # fmt: skip
    assert (t["symbol"], t["payee"]) == ("MSFT 20NOV26 480 P", "Sell to open MSFT 20NOV26 480 P")


def test_a_reader_of_the_account_records_no_option_trade_in_it(server):
    alice, bob, a, _ = _shared_to_read(server)
    r = option_trade(bob, a, "2026-09-02", "sell-to-open", "MSFT", "put", "480", "2026-11-20",
                     "1", "6.40")  # fmt: skip
    assert (r.status_code, _errors(r)) == (403, [("accountId", *READ_ONLY)])
    assert alice.get("/ui/api/positions").json()["open"] == []


# ---- Corporate actions (S2.4) ----


def test_a_reader_is_told_the_account_is_read_only_before_a_corporate_action_is_fixed(server):
    """Changing an action is refused to everyone (it is deleted and recorded again), but a
    reader hears first that the account is not theirs to change, as a delete tells them."""
    alice, bob, a, fb = _shared_to_read(server, holding=True)
    fields = {"accountId": a, "instrumentId": fb, "kind": "split", "date": "2026-06-09",
              "ratio": "2"}  # fmt: skip
    act = saved(create(alice, "CorpA", **fields))
    for r in (change(bob, "CorpA", act, **fields), remove(bob, "CorpA", act)):
        assert (r.status_code, _errors(r)) == (403, [(None, *READ_ONLY)])


# ---- Strategies (S3.5) ----


def test_a_strategy_turned_down_gone_or_unknown_is_not_found_by_its_roll_or_a_change(alice):
    a, held = _book_of_legs(alice)
    no = saved(create(alice, "Strat", accountId=a, legs=_legs(held, "put"), dismissed=True))
    st = saved(create(alice, "Strat", accountId=a, legs=_legs(held, "aapl")))
    assert remove(alice, "Strat", st).status_code == 200
    for x in (no, st, {"id": "Strat_01m4tj4gg0f02s596bvjcn26rw", "version": 1}):
        r = alice.post(f"/ui/api/strategies/{x['id']}/roll", json={})
        assert (r.status_code, r.json()["code"], r.json()["detail"]) == (
            404, "not-found", "Not found")  # fmt: skip
        r = change(alice, "Strat", x, accountId=a, name="Mine")
        assert (r.status_code, _errors(r)) == (404, [(None, "not-found", "Not found")])


def test_a_reader_is_told_the_account_is_read_only_by_a_strategys_roll_change_or_undo(server):
    alice, bob, a, _ = _shared_to_read(server)
    st = saved(create(alice, "Strat", accountId=a, legs=_spread(alice, a)))
    r = bob.post(f"/ui/api/strategies/{st['id']}/roll", json={})
    assert (r.status_code, r.json()["code"], r.json()["detail"]) == (403, *READ_ONLY)
    legs = [{"instrumentId": x["instrumentId"]} for x in st["legs"]]
    for r in (change(bob, "Strat", st, accountId=a, legs=legs, name="Mine"),
              remove(bob, "Strat", st)):  # fmt: skip
        assert (r.status_code, _errors(r)) == (403, [(None, *READ_ONLY)])
    [v] = alice.get("/ui/api/positions/strategies").json()["strategies"]
    assert (v["name"], v["version"]) == (st["name"], st["version"])


def test_a_strategy_grouped_with_no_name_is_named_by_its_shape(alice):
    a, held = _book_of_legs(alice)
    st = saved(create(alice, "Strat", accountId=a, legs=_legs(held, "aapl")))
    assert st["name"] == "Short put"


def test_a_strategys_legs_each_say_the_day_they_closed(alice):
    a = new_account(alice, type="brokerage")["id"]
    st = saved(create(alice, "Strat", accountId=a, legs=_spread(alice, a)))
    option(alice, a, "buy-to-close", "2026-10-08", "1.00", strike="540", fees="0")
    [v] = alice.get("/ui/api/positions/strategies").json()["strategies"]
    assert v["id"] == st["id"]
    assert {(x["symbol"], x["closedOn"]) for x in v["legs"]} == {
        ("MSFT 20NOV26 540 P", "2026-10-08"), ("MSFT 20NOV26 530 P", None)}  # fmt: skip
