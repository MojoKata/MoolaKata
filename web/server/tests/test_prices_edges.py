"""Settings › Prices and typed prices at their edges (requirements S4.2.3, S4.10, R3.11): each
refusal at its field, with its code and words, and who may change what."""

import datetime as dt
from decimal import Decimal as D

from conftest import make_user, sign_in
from edits import change, create, make, remove, saved

from moolakata import clock, ids
from moolakata.store.entities.accounts import Account, Lot, Transaction
from moolakata.store.repos import ledger as repo

TODAY = dt.date.today()


def _refused(r, status: int, field: str, code: str, words: str) -> None:
    assert r.status_code == status, r.text
    [e] = r.json()["errors"]
    assert (e["field"].rsplit(".", 1)[-1] if "." in e["field"] else e["field"], e["code"],
            e["message"]) == (field, code, words)  # fmt: skip


def _turned_away(r, status: int, code: str) -> None:
    """A save refused as a whole: nothing saved, the reason its one error's."""
    assert r.status_code == status, r.text
    assert [e["code"] for e in r.json()["errors"]] == [code]


def test_a_source_takes_its_place_after_those_added_before_for_each_class(admin_client):
    """S4.2.3: a source added goes last for each class it serves, after every source already
    ranked for it; a class no other source serves starts it first."""
    cboe = make(admin_client, "Src", name="cboe").json()
    assert cboe["preference"] == {"equity": 1, "etf": 1, "option": 1}
    tiingo = make(admin_client, "Src", name="tiingo").json()
    assert tiingo["preference"] == {"equity": 2, "etf": 2, "mutual-fund": 1}


def test_a_source_is_an_admins_to_add_and_change(server, admin_client):
    """S4.2.3, S12.19.1: Settings › Prices is admins' alone: another user's save is refused,
    and one never added, or removed, isn't found."""
    make_user(server, "jane")
    jane = sign_in(server, "jane")
    _turned_away(make(jane, "Src", name="cboe"), 403, "admins-only")
    src = make(admin_client, "Src", name="cboe").json()
    _turned_away(change(jane, "Src", src, enabled=False), 403, "admins-only")
    assert remove(admin_client, "Src", src).status_code == 200
    _turned_away(change(admin_client, "Src", src, enabled=False), 404, "not-found")


def test_a_sources_key_is_set_with_it_or_after_and_refused_when_it_cant_be_one(admin_client):
    """S4.2.3, S14.4, R3.11: a key given as the source is added is kept with it; one for a
    source that needs none, too short, too long or with a space is refused at the key; a
    source keeps its name."""
    tiingo = make(admin_client, "Src", name="tiingo", apiKey="abcdef0123456789").json()
    assert tiingo["key"]["setBy"] == "Ada Admin" and tiingo["enabled"] is False
    coinbase = make(admin_client, "Src", name="coinbase").json()
    _refused(change(admin_client, "Src", coinbase, apiKey="abcdef0123456789"), 422, "apiKey",
             "no-key", "Coinbase needs no key.")  # fmt: skip
    for bad in ("short", "x" * 201, "abcd efgh ijkl", "  "):
        _refused(change(admin_client, "Src", tiingo, apiKey=bad), 422, "apiKey", "key-invalid",
                 "Paste the key as the source gives it.")  # fmt: skip
    assert saved(change(admin_client, "Src", tiingo, apiKey="  " + "k" * 200 + " "))["key"]
    tiingo = admin_client.get("/ui/api/price-sources").json()["sources"][0]
    _refused(change(admin_client, "Src", tiingo, name="cboe"), 422, "name", "source-fixed",
             "A source keeps its name; add another.")  # fmt: skip


def test_a_sources_order_is_for_the_classes_it_serves(admin_client):
    """S4.2.3: a place for a class the source doesn't serve is refused at that class; one for
    the classes it serves is kept."""
    src = make(admin_client, "Src", name="coinbase").json()
    r = change(admin_client, "Src", src, preference={"crypto": 2, "bond": 1})
    assert r.status_code == 422, r.text
    [e] = r.json()["errors"]
    assert (e["field"], e["code"], e["message"]) == (
        "preference.bond", "class-not-served", "Coinbase doesn't serve bond.")  # fmt: skip
    got = saved(change(admin_client, "Src", src, preference={"crypto": 2}))
    assert got["preference"] == {"crypto": 2}
    # The same again changes nothing, and records nothing.
    again = saved(change(admin_client, "Src", got, preference={"crypto": 2}, enabled=True))
    assert again["version"] == got["version"]


def test_refresh_prices_follows_the_daily_task_as_a_job(server, admin_client, monkeypatch):
    """S4.4, S13.8.7: Refresh prices runs the daily task now and answers with its job."""
    asked = []
    monkeypatch.setattr(server.tasks, "run_now", lambda name, job: asked.append(name) or True)
    r = admin_client.post("/ui/api/prices/refresh")
    assert r.status_code == 202, r.text
    assert asked == ["prices"] and r.json()["id"]


def _held(server, user) -> str:
    """An instrument the user holds, bought 20 days ago."""
    with server.db.tx(unscoped="test") as s:
        a = Account(id=ids.new_id("Acct"), ownerId=user.id, name="B", type="brokerage")
        s.add(a)
        s.flush()
        inst = repo.instrument(s, "VTI", "Total market", "etf")
        t = Transaction(id=ids.new_id("Txn"), accountId=a.id, date=TODAY - dt.timedelta(days=20),
                        kind="buy", amount=D("-1000.00"), instrumentId=inst.id, quantity=D(4),
                        price=D(250))  # fmt: skip
        s.add(t)
        s.flush()
        s.add(Lot(id=ids.new_id("Lot"), accountId=a.id, instrumentId=inst.id, transactionId=t.id,
                  acquiredOn=t.date, quantity=D(4), costBasis=D(1000)))  # fmt: skip
        return inst.id


def test_a_typed_price_is_refused_in_the_future_below_zero_and_on_another_day(server):
    """R3.11, S4.10: a price dated after today or below zero is refused at its field; a typed
    price keeps its day; it is its typer's alone to change; removed, it values nothing."""
    jane_user = make_user(server, "jane")
    make_user(server, "john")
    inst = _held(server, jane_user)
    jane, john = sign_in(server, "jane"), sign_in(server, "john")
    today = clock.today()
    tomorrow = (today + dt.timedelta(days=1)).isoformat()
    _refused(create(jane, "TyPrc", instrumentId=inst, date=tomorrow, close="10"), 422, "date",
             "date-in-future", "A price can't be dated in the future.")  # fmt: skip
    _refused(create(jane, "TyPrc", instrumentId=inst, date=today.isoformat(), close="-0.01"),
             422, "close", "price-negative", "A price can't be negative.")  # fmt: skip
    typed = saved(create(jane, "TyPrc", instrumentId=inst, date=today.isoformat(), close="0"))
    _refused(change(jane, "TyPrc", typed, date=(today - dt.timedelta(days=1)).isoformat()), 422,
             "date", "price-fixed", "A typed price keeps its day: type another.")  # fmt: skip
    _turned_away(change(john, "TyPrc", typed, close="11"), 404, "not-found")
    week = (today - dt.timedelta(days=7)).isoformat()
    older = saved(create(jane, "TyPrc", instrumentId=inst, date=week, close="9"))
    prices = f"/ui/api/instruments/{inst}/prices"
    # S4.6: a range's closes, each end kept: from a day, to a day, or both.
    assert [p["date"] for p in jane.get(prices, params={"from": week}).json()["items"]] == [
        week, today.isoformat()]  # fmt: skip
    assert [p["date"] for p in jane.get(prices, params={"to": week}).json()["items"]] == [week]
    between = {"from": today.isoformat(), "to": today.isoformat()}
    assert [p["close"] for p in jane.get(prices, params=between).json()["items"]] == ["0.0"]
    assert remove(jane, "TyPrc", typed).status_code == 200
    assert remove(jane, "TyPrc", older).status_code == 200
    assert jane.get(prices).json()["items"] == []
    _turned_away(change(jane, "TyPrc", typed, close="11"), 404, "not-found")


def test_an_instruments_closes_are_not_found_for_one_that_isnt(admin_client):
    r = admin_client.get(f"/ui/api/instruments/{ids.new_id('Instr')}/prices")
    assert (r.status_code, r.json()["code"]) == (404, "not-found")
