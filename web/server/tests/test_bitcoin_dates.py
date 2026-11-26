"""A bitcoin transaction's date (requirements S1.6.2.6.1, S14.9.2): a transaction is a moment on
the chain, its confirmation, and its ledger date is that moment's day in the time zone in effect
for its owner at that moment (the taxpayer whose lots, holding periods and fee sales it makes),
never the server's. A move, from today, never dates the past again; a correction, from an
earlier date, dates again what it covers, in the Profile's save, and asks first when that moves a
filed year's gains (S2.8.2).

The year-end case: coins sent at 22:30 Pacific on Dec 31 2026 are 06:30 UTC and 00:30 Chicago
on Jan 1 2027. The server runs in Chicago (TZ); today is Mar 1 2027."""

import datetime as dt
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import change, create, make, new_id, remove, saved
from sqlalchemy import select

from moolakata import clock, ids, timezones, user_zones
from moolakata.bitcoin import sources, sync
from moolakata.store.entities.accounts import Lot, Transaction
from moolakata.store.entities.prices import Price
from moolakata.store.entities.taxes import TaxBookChange
from moolakata.store.entities.users import User, UserTimeZone
from moolakata.store.repos import ledger as repo

AT = dt.datetime(2027, 1, 1, 6, 30, tzinfo=dt.UTC)  # Dec 31 22:30 Pacific, Jan 1 00:30 Chicago
DEC31, JAN1 = dt.date(2026, 12, 31), dt.date(2027, 1, 1)
FEE = 12_000
SENT = sources.Tx("a" * 64, AT, -(10_000_000 + FEE), FEE)
NOW = dt.datetime(2027, 3, 1, 15, 0, tzinfo=dt.UTC)  # 09:00 in Chicago, 07:00 in Los Angeles


@pytest.fixture(autouse=True)
def chicago(monkeypatch):
    # The host's zone is read once and kept: forget it, so this TZ is the one read.
    monkeypatch.setenv("TZ", "America/Chicago")
    timezones.host_zone.cache_clear()
    clock.fix(NOW)
    yield
    clock.fix(None)
    timezones.host_zone.cache_clear()


@pytest.fixture
def jane(server):
    make_user(server, "jane")
    return sign_in(server, "jane")


def _wallet(c) -> str:
    return make(c, "Acct", name="Cold storage", type="crypto-wallet").json()["id"]


def _me(c) -> str:
    return c.get("/ui/api/session").json()["user"]["id"]


def _zone(server, c, zone: str) -> None:
    """The user's time zone as one they never changed: no history, theirs at every moment."""
    with server.db.tx(unscoped="test: the owner's time zone") as s:
        s.get(User, _me(c)).timeZone = zone


def _since(c, zone: str, since, confirm: bool = False):
    """Profile's Since when?: `zone` in effect from `since`, as its save makes it."""
    return create(c, "UsrTz", confirm, timeZone=zone, since=None if since is None else str(since))


def _rows(server, account_id) -> dict[str, Transaction]:
    with server.db.read(unscoped="test") as s:
        rows = s.scalars(select(Transaction).where(Transaction.accountId == account_id))
        return {t.fitId: t for t in rows}


def _dates(server, account_id) -> dict[str, dt.date]:
    return {t.kind: t.date for t in _rows(server, account_id).values()}


def _read(server, account_id, *txs) -> None:
    with server.db.tx(unscoped="test: a read") as s:
        sync.record(s, account_id, list(txs))


def _held(server, account_id) -> None:
    """A coin bought for $30,000 in 2025, and bitcoin's closes either side of the new year."""
    from moolakata.prices import refresh

    refresh.install()  # stored closes value the fee, as the running server reads them
    with server.db.tx(unscoped="test: coins held, and their price") as s:
        btc = repo.instrument(s, "BTC", "Bitcoin", "crypto")
        got = Transaction(id=ids.new_id("Txn"), accountId=account_id, date=dt.date(2025, 3, 1),
                          kind="transfer-in", amount=D(0), instrumentId=btc.id,
                          quantity=D(1))  # fmt: skip
        s.add(got)
        s.flush()
        s.add(Lot(id=ids.new_id("Lot"), accountId=account_id, instrumentId=btc.id,
                  transactionId=got.id, acquiredOn=got.date, quantity=D(1),
                  costBasis=D("30000")))  # fmt: skip
        s.add(Price(instrumentId=btc.id, date=DEC31, close=D("60000"), source="test"))
        s.add(Price(instrumentId=btc.id, date=JAN1, close=D("70000"), source="test"))


def _close_2026(c) -> str:
    book = make(c, "TaxBk", year=2026, filers=[_me(c)]).json()
    r = make(c, "Filng", bookId=book["id"], jurisdiction="federal", form="1040",
             progress="filed", filedOn="2027-02-20")  # fmt: skip
    assert r.status_code == 200, r.text
    return book["id"]


# ---------- reading


def test_a_transaction_is_dated_in_its_owners_time_zone_not_the_servers(server, jane):
    _zone(server, jane, "America/Los_Angeles")
    w = _wallet(jane)
    _read(server, w, SENT)
    assert _dates(server, w) == {"transfer-out": DEC31, "sell": DEC31, "fee": DEC31}, (
        "the fee's sale lands in 2026, the owner's year"
    )
    assert _rows(server, w)["btc:" + "a" * 64].confirmedAt == AT, "its moment kept"


def test_an_owner_on_auto_has_the_servers_time_zone(server, jane):
    w = _wallet(jane)
    _read(server, w, SENT)
    assert _dates(server, w) == {"transfer-out": JAN1, "sell": JAN1, "fee": JAN1}


def test_a_read_keeps_the_moment_of_one_recorded_without_it_and_leaves_its_date(server, jane):
    w = _wallet(jane)
    got = sources.Tx("b" * 64, AT, 5_000, 0)
    _read(server, w, got)
    with server.db.tx(unscoped="test: recorded before moments were kept") as s:
        row = s.scalars(select(Transaction).where(Transaction.accountId == w)).one()
        row.confirmedAt, row.date = None, dt.date(2026, 12, 30)
    _read(server, w, got)
    row = _rows(server, w)["btc:" + "b" * 64]
    assert (row.confirmedAt, row.date) == (AT, dt.date(2026, 12, 30))


def test_another_users_time_zones_never_date_ones_bitcoin(server, jane):
    make_user(server, "john")
    john = sign_in(server, "john")
    saved(_since(john, "Asia/Tokyo", "2020-01-01"))
    _zone(server, jane, "America/Los_Angeles")
    w = _wallet(jane)
    _read(server, w, SENT)
    assert _dates(server, w)["transfer-out"] == DEC31, "Jane's own, not John's Tokyo"
    with server.db.read(unscoped="test") as s:
        assert s.get(User, _me(jane)).timeZone == "America/Los_Angeles"


# ---------- a move and a correction


def test_a_move_never_dates_the_past_again(server, jane):
    """Jane in Los Angeles moves to New York today: her year-end coins stay on Dec 31, and a
    transaction found later from before the move is dated in Los Angeles too."""
    _zone(server, jane, "America/Los_Angeles")
    w = _wallet(jane)
    _read(server, w, SENT)
    saved(_since(jane, "America/New_York", "2027-03-01"))
    assert _dates(server, w) == {"transfer-out": DEC31, "sell": DEC31, "fee": DEC31}
    late = sources.Tx("b" * 64, AT + dt.timedelta(minutes=5), 5_000, 0)
    after = sources.Tx("c" * 64, dt.datetime(2027, 3, 1, 14, 0, tzinfo=dt.UTC), 6_000, 0)
    _read(server, w, SENT, late, after)
    rows = _rows(server, w)
    assert rows["btc:" + "a" * 64].date == DEC31, "a read dates nothing again"
    assert rows["btc:" + "b" * 64].date == DEC31, "found later, dated where she was then"
    assert rows["btc:" + "c" * 64].date == dt.date(2027, 3, 1)
    assert jane.get("/ui/api/profile").json()["timeZone"] == "America/New_York"


def test_a_correction_dates_again_and_asks_first_at_a_filed_year(server, jane):
    """Jane was in New York since December, not Los Angeles: her year-end coins and their
    fee's sale move to Jan 1 2027, out of 2026, whose return is filed. Asked first; confirmed,
    the fee is valued at Jan 1's price and the move listed on the 2026 book."""
    _zone(server, jane, "America/Los_Angeles")
    w = _wallet(jane)
    _held(server, w)
    _read(server, w, SENT)
    rows = {t.kind: t for t in _rows(server, w).values()}
    assert (rows["sell"].price, rows["sell"].amount) == (D("60000"), D("7.20"))
    book = _close_2026(jane)
    r = _since(jane, "America/New_York", "2026-12-01")
    assert r.status_code == 409 and [a["code"] for a in r.json()["asks"]] == ["closed-year"]
    assert "2026" in r.json()["asks"][0]["message"]
    assert _dates(server, w)["transfer-out"] == DEC31, "nothing changed until confirmed"
    with server.db.read(unscoped="test") as s:
        assert s.get(User, _me(jane)).timeZone == "America/Los_Angeles"
    saved(_since(jane, "America/New_York", "2026-12-01", confirm=True))
    rows = {t.kind: t for t in _rows(server, w).values()}
    assert {k: rows[k].date for k in ("transfer-out", "sell", "fee")} == dict.fromkeys(
        ("transfer-out", "sell", "fee"), JAN1
    )
    assert (rows["sell"].price, rows["sell"].amount, rows["fee"].amount) == (
        D("70000"), D("8.40"), D("-8.40"),
    )  # fmt: skip
    with server.db.read(unscoped="test") as s:
        moved = list(s.scalars(select(TaxBookChange).where(TaxBookChange.bookId == book)))
    assert [(c.accountId, c.gains) for c in moved] == [(w, D("-3.60"))], (
        "the fee's $3.60 gain left 2026"
    )


def test_a_move_mid_year_dates_coins_before_it_in_the_old_time_zone_and_after_in_the_new(
    server, jane
):
    _zone(server, jane, "America/Los_Angeles")
    w = _wallet(jane)
    june = sources.Tx("b" * 64, dt.datetime(2026, 6, 15, 5, 0, tzinfo=dt.UTC), 5_000, 0)
    august = sources.Tx("c" * 64, dt.datetime(2026, 8, 1, 5, 0, tzinfo=dt.UTC), 6_000, 0)
    midday = sources.Tx("f" * 64, dt.datetime(2026, 8, 15, 18, 0, tzinfo=dt.UTC), 9_000, 0)
    _read(server, w, june, august, midday)
    saved(_since(jane, "America/New_York", "2026-07-01"))
    rows = _rows(server, w)
    assert rows["btc:" + "b" * 64].date == dt.date(2026, 6, 14), "before: Los Angeles"
    assert rows["btc:" + "c" * 64].date == dt.date(2026, 8, 1), "after: New York, dated again"
    assert rows["btc:" + "f" * 64].date == dt.date(2026, 8, 15), "the same day in both"
    # Found later, each side of the move.
    before = sources.Tx("d" * 64, dt.datetime(2026, 6, 20, 5, 0, tzinfo=dt.UTC), 7_000, 0)
    later = sources.Tx("e" * 64, dt.datetime(2026, 9, 1, 5, 0, tzinfo=dt.UTC), 8_000, 0)
    _read(server, w, june, august, midday, before, later)
    rows = _rows(server, w)
    assert rows["btc:" + "d" * 64].date == dt.date(2026, 6, 19)
    assert rows["btc:" + "e" * 64].date == dt.date(2026, 9, 1)


def test_a_correction_to_auto_dates_in_the_servers_time_zone(server, jane):
    _zone(server, jane, "America/Los_Angeles")
    w = _wallet(jane)
    _read(server, w, SENT)
    saved(_since(jane, "auto", "2026-12-01"))
    assert _dates(server, w) == {"transfer-out": JAN1, "sell": JAN1, "fee": JAN1}, "Chicago's day"
    p = jane.get("/ui/api/profile").json()
    assert (p["timeZone"], p["zone"]) == ("auto", "America/Chicago")


def test_a_date_typed_by_hand_stays(server, jane):
    _zone(server, jane, "America/Los_Angeles")
    w = _wallet(jane)
    got = sources.Tx("b" * 64, AT, 5_000, 0)
    _read(server, w, got)
    with server.db.tx(unscoped="test: the owner types a date") as s:
        t = s.scalars(select(Transaction).where(Transaction.accountId == w)).one()
        t.date = dt.date(2026, 12, 20)
    saved(_since(jane, "America/New_York", "2026-12-01"))
    assert _dates(server, w) == {"transfer-in": dt.date(2026, 12, 20)}


def test_a_correction_replaces_the_entries_it_covers(server, jane):
    _zone(server, jane, "America/Los_Angeles")
    saved(_since(jane, "America/Denver", "2027-02-01"))
    saved(_since(jane, "America/New_York", "2026-12-01"))
    with server.db.read(unscoped="test") as s:
        kept = [(e.timeZone, e.since) for e in user_zones.entries(s, _me(jane))]
    assert kept == [
        ("America/Los_Angeles", dt.date(1900, 1, 1)),  # the time zone she had all along
        ("America/New_York", dt.date(2026, 12, 1)),
    ], "Denver's, from a later date, replaced"
    assert jane.get("/ui/api/profile").json()["timeZone"] == "America/New_York"


def test_the_time_zone_in_effect_at_a_moment():
    la = UserTimeZone(id="UsrTz_a", userId="u", timeZone="America/Los_Angeles",
                      since=dt.date(2026, 1, 1))  # fmt: skip
    ny = UserTimeZone(id="UsrTz_b", userId="u", timeZone="America/New_York",
                      since=dt.date(2026, 7, 1))  # fmt: skip
    at = lambda m: user_zones.at([la, ny], "UTC", m).key  # noqa: E731
    assert at(dt.datetime(2025, 6, 1, tzinfo=dt.UTC)) == "America/Los_Angeles", "before every one"
    # New York's starts at 00:00 there: 04:00 UTC.
    assert at(dt.datetime(2026, 7, 1, 3, 59, tzinfo=dt.UTC)) == "America/Los_Angeles"
    assert at(dt.datetime(2026, 7, 1, 4, 0, tzinfo=dt.UTC)) == "America/New_York"
    assert user_zones.at([], "Asia/Tokyo", AT).key == "Asia/Tokyo", "no history: their own"


# ---------- Since when?


def test_since_when_is_refused_blank_or_in_the_future(server, jane):
    """R3.11: a blank date is refused at its field, never read as today; one whose 00:00 in the
    new time zone hasn't come is refused too, and one before 1900. Today in a time zone already
    a day ahead is not."""
    for zone, since, field, code in (
        ("America/New_York", None, "since", "since-required"),
        ("America/New_York", "2027-03-02", "since", "since-future"),
        ("America/New_York", "1899-12-31", "since", "since-invalid"),
        ("Mars/Olympus", "2027-03-01", "timeZone", "zone-invalid"),
    ):
        r = _since(jane, zone, since)
        assert r.status_code == 422, r.text
        (e,) = r.json()["errors"]
        assert (e["field"], e["code"]) == (field, code)
    words = {e["code"]: e["message"] for e in _since(jane, "UTC", None).json()["errors"]}
    assert words == {"since-required": "The date it is in effect from."}
    r = _since(jane, "UTC", "1899-12-31")
    assert r.json()["errors"][0]["message"] == "A date from 1900 on."
    r = _since(jane, "America/New_York", "2027-03-02")
    assert r.json()["errors"][0]["message"] == "Today or an earlier date."
    # Kiritimati is UTC+14: it is already Mar 2 there.
    saved(_since(jane, "Pacific/Kiritimati", "2027-03-02"))


def test_a_time_zone_from_a_date_is_replaced_never_changed_and_its_users_alone(server, jane):
    r = _since(jane, "America/New_York", "2027-03-01")
    entry = saved(r)
    assert (entry["timeZone"], entry["since"]) == ("America/New_York", "2027-03-01")
    for done in (change(jane, "UsrTz", entry, since="2027-02-01"), remove(jane, "UsrTz", entry)):
        assert done.status_code == 422 and done.json()["errors"][0]["code"] == "time-zone-kept"
    make_user(server, "john")
    john = sign_in(server, "john")
    assert change(john, "UsrTz", entry, since="2027-02-01").status_code == 404
    with server.db.read(user=_me(john)) as s:
        assert s.get(UserTimeZone, entry["id"]) is None, "her history isn't his to read"
    other = create(john, "UsrTz", timeZone="Asia/Tokyo", since="2027-03-01")
    with server.db.read(unscoped="test") as s:
        row = s.get(UserTimeZone, saved(other)["id"])
    assert row.userId == _me(john), "made as the saver's own"
    assert new_id("UsrTz").startswith("UsrTz_")
