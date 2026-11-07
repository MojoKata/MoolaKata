import datetime as dt
import json
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import change, create, make, remove, saved
from sqlalchemy import func, select

from moolakata import clock, figures, ids, valuation
from moolakata.ledger.types import investing
from moolakata.prices import SOURCES, SourceError, TickerSource, register
from moolakata.prices import refresh as pricing
from moolakata.prices.base import Ref
from moolakata.prices.coinbase import Coinbase
from moolakata.prices.stub import Stub, walk
from moolakata.prices.tiingo import Tiingo
from moolakata.store.entities.accounts import Account
from moolakata.store.entities.prices import Price, PriceSource
from moolakata.store.repos import ledger as repo

TODAY = dt.date.today()


class FakeResponse:
    def __init__(self, status):
        self.status_code = status


class FakeClient:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def get_bytes(self, url, **kw):
        self.calls.append((url, kw))
        status, body = self.answers(url)
        return FakeResponse(status), json.dumps(body).encode()


def test_stub_is_repeatable_and_waits_for_the_close():
    assert walk("VTI", dt.date(2026, 3, 2)) == walk("VTI", dt.date(2026, 3, 2))
    # The clock held on TODAY: a run crossing midnight UTC would otherwise end a day later.
    clock.fix(dt.datetime.combine(TODAY, dt.time(21), dt.UTC))
    try:
        rows = Stub(None, None).history(
            Ref("i", "VTI", "etf"), TODAY - dt.timedelta(days=10), TODAY
        )
        crypto = Stub(None, None).history(
            Ref("i", "BTC", "crypto"), TODAY - dt.timedelta(days=3), TODAY
        )
    finally:
        clock.fix(None)
    assert rows and rows[-1][0] < TODAY
    assert all(d.weekday() < 5 for d, _ in rows)
    assert crypto[-1][0] == TODAY


def test_tiingo_reads_closes_and_sends_its_key_in_a_header():
    client = FakeClient(
        lambda url: (
            200,
            [
                {"date": "2026-10-08T00:00:00.000Z", "close": 250.5},
                {"date": "2026-10-09T00:00:00.000Z", "close": 251.25},
            ],
        )
    )
    rows = Tiingo(client, "secret-key").history(
        Ref("i", "VTI", "etf"), dt.date(2026, 10, 8), dt.date(2026, 10, 9)
    )
    assert rows == [(dt.date(2026, 10, 8), D("250.5")), (dt.date(2026, 10, 9), D("251.25"))]
    url, kw = client.calls[0]
    assert "secret-key" not in url and kw["headers"]["Authorization"] == "Token secret-key"
    with pytest.raises(SourceError, match="refused the key"):
        Tiingo(FakeClient(lambda u: (401, {})), "bad").history(Ref("i", "VTI", "etf"), TODAY, TODAY)
    with pytest.raises(SourceError, match="needs its API key"):
        Tiingo(client, None).history(Ref("i", "VTI", "etf"), TODAY, TODAY)


def test_coinbase_pages_daily_candles():
    def answers(url):
        return 200, [
            [int(dt.datetime(2026, 1, 2, tzinfo=dt.UTC).timestamp()), 1, 2, 1, 98000.5, 10]
        ]

    client = FakeClient(answers)
    rows = Coinbase(client, None).history(
        Ref("i", "BTC", "crypto"), dt.date(2025, 1, 1), dt.date(2026, 1, 31)
    )
    assert rows == [(dt.date(2026, 1, 2), D("98000.5"))]
    assert len(client.calls) == 2  # 300 days a call


def test_coinbase_leaves_out_todays_open_candle():
    def stamp(day):
        return int(dt.datetime.combine(day, dt.time(), dt.UTC).timestamp())

    yesterday = TODAY - dt.timedelta(days=1)
    client = FakeClient(
        lambda url: (200, [[stamp(TODAY), 1, 2, 1, 101.0, 1], [stamp(yesterday), 1, 2, 1, 99.5, 1]])
    )
    clock.fix(dt.datetime.combine(TODAY, dt.time(21), dt.UTC))
    try:
        rows = Coinbase(client, None).history(Ref("i", "BTC", "crypto"), yesterday, TODAY)
    finally:
        clock.fix(None)
    assert rows == [(yesterday, D("99.5"))]
    assert f"end={yesterday.isoformat()}T23:59:59Z" in client.calls[0][0]


@register
class Broken(TickerSource):
    name = "broken-test"
    label = "Broken"
    classes = frozenset({"etf"})

    def history(self, ref, start, end):
        raise SourceError("Broken answered HTTP 500")


@register
class Garbled(TickerSource):
    name = "garbled-test"
    label = "Garbled"
    classes = frozenset({"etf"})

    def history(self, ref, start, end):
        raise ValueError("unexpected token at line 1")


def _book(server, user):
    with server.db.tx(unscoped="test") as s:
        a = Account(id=ids.new_id("Acct"), ownerId=user.id, name="B", type="brokerage")
        s.add(a)
        s.flush()
        inst = repo.instrument(s, "VTI", "Total market", "etf")
        from moolakata.store.entities.accounts import Lot, Transaction

        t = Transaction(
            id=ids.new_id("Txn"),
            accountId=a.id,
            date=TODAY - dt.timedelta(days=20),
            kind="buy",
            amount=D("-1000.00"),
            instrumentId=inst.id,
            quantity=D(4),
            price=D(250),
        )
        s.add(t)
        s.flush()
        s.add(
            Lot(
                id=ids.new_id("Lot"),
                accountId=a.id,
                instrumentId=inst.id,
                transactionId=t.id,
                acquiredOn=t.date,
                quantity=D(4),
                costBasis=D(1000),
            )
        )
        return a.id, inst.id


def _source(server, name, pref):
    with server.db.tx(unscoped="test") as s:
        s.add(
            PriceSource(
                id=ids.new_id("Src"), name=name, enabled=True, preference=json.dumps({"etf": pref})
            )
        )


def test_refresh_falls_back_records_errors_and_stores_once(server):
    pricing.install()
    server.config = server.config.__class__(**{**server.config.__dict__, "dev": True})
    user = make_user(server, "alice")
    account_id, inst_id = _book(server, user)
    _source(server, "broken-test", 1)
    _source(server, "stub", 2)
    result = pricing.refresh(server)
    assert result["stored"] > 10
    with server.db.read(unscoped="test") as s:
        rows = {r.name: r for r in s.scalars(select(PriceSource))}
        assert rows["broken-test"].lastError == "Broken answered HTTP 500"
        assert rows["stub"].lastOkAt is not None and rows["stub"].lastError is None
        n = s.scalar(select(func.count()).select_from(Price))
        p = pricing.stored_closes(s, [inst_id], TODAY)[inst_id]
        assert p.source == "close" and not p.stale
    assert pricing.refresh(server)["stored"] == 0  # nothing new: nothing stored twice
    with server.db.read(unscoped="test") as s:
        assert s.scalar(select(func.count()).select_from(Price)) == n
        a = s.get(Account, account_id)
        led = repo.load(s, a)
        value = valuation.account_value(s, led, investing(a.type))
        ser = valuation.series(s, led, True, TODAY - dt.timedelta(days=60), TODAY, 3)
        assert ser[-1] == (TODAY, value)  # the chart ends where the balance is


def test_refresh_fails_when_every_source_does(server):
    user = make_user(server, "alice")
    _book(server, user)
    _source(server, "broken-test", 1)
    with pytest.raises(SourceError, match=r"^Broken answered HTTP 500$"):
        pricing.refresh(server)


def test_an_unreadable_answer_falls_back_like_a_failure(server):
    pricing.install()
    server.config = server.config.__class__(**{**server.config.__dict__, "dev": True})
    _book(server, make_user(server, "alice"))
    _source(server, "garbled-test", 1)
    _source(server, "stub", 2)
    assert pricing.refresh(server)["stored"] > 10
    with server.db.read(unscoped="test") as s:
        rows = {r.name: r for r in s.scalars(select(PriceSource))}
        assert rows["garbled-test"].lastError == "an answer it couldn't read"


def test_only_what_is_held_is_priced(server):
    from moolakata.store.entities.accounts import Transaction

    account_id, inst_id = _book(server, make_user(server, "alice"))
    with server.db.read(unscoped="test") as s:
        assert inst_id in {i.id for i, _ in pricing.priced(s)}
    with server.db.tx(unscoped="test") as s:
        s.add(
            Transaction(
                id=ids.new_id("Txn"),
                accountId=account_id,
                date=TODAY - dt.timedelta(days=2),
                kind="sell",
                amount=D("1100.00"),
                instrumentId=inst_id,
                quantity=D(4),
                price=D(275),
            )
        )
    with server.db.read(unscoped="test") as s:
        assert pricing.priced(s) == []  # sold: no longer fetched


def test_staleness():
    """S4.5, S4.7, each on its bound: an option's close after one trading day, a stock's after
    two, a coin's after two days, a typed price after 90 days."""
    friday = dt.date(2026, 10, 9)
    assert not pricing.is_stale("option", friday, dt.date(2026, 10, 12))
    assert pricing.is_stale("option", friday, dt.date(2026, 10, 13))
    assert not pricing.is_stale("etf", friday, dt.date(2026, 10, 13))
    assert pricing.is_stale("etf", friday, dt.date(2026, 10, 14))  # three days
    assert not pricing.is_stale("crypto", friday, dt.date(2026, 10, 11))  # two days
    assert pricing.is_stale("crypto", friday, dt.date(2026, 10, 12))
    assert not pricing.typed_stale(friday, friday + dt.timedelta(days=90))
    assert pricing.typed_stale(friday, friday + dt.timedelta(days=91))


def test_price_sources_in_settings(admin_client, server):
    view = admin_client.get("/ui/api/price-sources").json()
    names = {s["name"] for s in view["available"]}
    assert {"tiingo", "coinbase", "manual"} <= names and "stub" not in names
    assert view["refreshTime"] == "18:00"
    r = make(admin_client, "Src", name="tiingo")
    assert r.status_code == 200
    src = r.json()
    assert src["enabled"] is False and src["needsKey"] and src["key"] is None
    r = change(admin_client, "Src", src, enabled=True)
    assert r.json()["errors"][0]["code"] == "key-needed"
    r = change(admin_client, "Src", src, apiKey="abcdef0123456789", enabled=True)
    row = saved(r)
    assert row["enabled"] and row["key"]["setBy"] == "Ada Admin"
    assert "abcdef0123456789" not in r.text
    with pytest.raises(Exception, match="not a host"):
        server.guard.check("api.exchange.coinbase.com", 443)
    assert make(admin_client, "Src", name="tiingo").status_code == 409
    assert make(admin_client, "Src", name="stub").status_code == 422
    assert remove(admin_client, "Src", row).status_code == 200
    from moolakata.store.repos import secrets as secret_repo

    with server.db.read(unscoped="test") as s:
        assert secret_repo.info(s, "PriceSource", src["id"], "apiKey") is None


def test_typed_prices_win_and_only_for_holders(server):
    pricing.install()
    user = make_user(server, "alice")
    make_user(server, "bob")
    _account_id, inst_id = _book(server, user)
    alice, bob = sign_in(server, "alice"), sign_in(server, "bob")
    day = (TODAY - dt.timedelta(days=1)).isoformat()
    assert create(bob, "TyPrc", instrumentId=inst_id, date=day, close="300").status_code == 404
    typed = saved(create(alice, "TyPrc", instrumentId=inst_id, date=day, close="300"))
    closes = alice.get(f"/ui/api/instruments/{inst_id}/prices").json()["items"]
    assert closes[-1] == {"date": day, "close": "300.0", "source": "manual", "id": typed["id"],
                          "version": typed["version"]}  # fmt: skip
    again = create(alice, "TyPrc", instrumentId=inst_id, date=day, close="301")
    assert again.json()["errors"][0]["code"] == "price-typed"
    assert saved(change(alice, "TyPrc", typed, close="301"))["close"] == "301.0"
    status = alice.get("/ui/api/prices/status").json()
    assert status["stale"] is False and status["running"] is False
    assert alice.post("/ui/api/prices/refresh").status_code in (202, 503)


def test_a_typed_price_values_only_its_typers_accounts(server):
    """S4.10: Bob holds what Alice holds; her typed price values her account alone, and his
    holding has no price from her trade either."""
    pricing.install()
    alice_user, bob_user = make_user(server, "alice"), make_user(server, "bob")
    a_id, inst_id = _book(server, alice_user)
    b_id, same = _book(server, bob_user)
    assert same == inst_id
    alice, bob = sign_in(server, "alice"), sign_in(server, "bob")
    day = (TODAY - dt.timedelta(days=1)).isoformat()
    saved(create(alice, "TyPrc", instrumentId=inst_id, date=day, close="300"))
    mine = alice.get(f"/ui/api/accounts/{a_id}/holdings").json()["holdings"][0]
    assert mine["value"] == "1200.00" and mine["priceSource"] == "manual"
    theirs = bob.get(f"/ui/api/accounts/{b_id}/holdings").json()["holdings"][0]
    assert theirs["priceSource"] == "trade" and theirs["value"] == "1000.00", "his own trade"
    assert [
        p["close"] for p in bob.get(f"/ui/api/instruments/{inst_id}/prices").json()["items"]
    ] == []


def test_sources_registered():
    assert {"tiingo", "coinbase", "manual", "stub", "cboe", "massive"} <= set(SOURCES)


def test_a_server_that_holds_nothing_has_no_stale_prices(admin_client, server):
    with server.db.tx(unscoped="test") as s:
        figures.ensure_benchmarks(s)  # as a real start does
    with server.db.read(unscoped="test") as s:
        assert pricing.priced(s), "the benchmarks are watched from the start"
    assert admin_client.get("/ui/api/prices/status").json()["stale"] is False
    attention = admin_client.get("/ui/api/dashboard").json()["attention"]
    assert all(a["kind"] != "stale-prices" for a in attention)


def test_cboe_marks_options_from_one_chain_per_underlying():
    """CBOE's delayed quotes (S4.5): a chain fetched once marks every contract on it, at the
    middle of the bid and the ask; SPX contracts are found under SPXW too."""
    from pathlib import Path

    from moolakata.prices.cboe import Cboe

    chains = json.loads((Path(__file__).parent / "fixtures" / "cboe-chains.json").read_text())
    client = FakeClient(lambda u: (200, chains[u.rsplit("/", 1)[-1].removesuffix(".json")]))
    src = Cboe(client, None)
    day = dt.date(2026, 10, 14)
    start, end = day - dt.timedelta(days=5), day
    leap = src.history(Ref("a", "O:AAPL270115C00230000", "option"), start, end)
    assert leap == [(day, D("115.55"))]  # bid 114.30, ask 116.80
    assert src.history(Ref("b", "O:AAPL261014C00245000", "option"), start, end) == [
        (day, D("97.88"))  # (96.10 + 99.65) / 2 = 97.875, to the even cent
    ]
    weekly = src.history(Ref("c", "O:SPX261027C07570000", "option"), start, end)
    assert weekly == [(day, D("183.05"))]
    assert src.history(Ref("w", "O:SPXW261027C07570000", "option"), start, end) == weekly
    assert src.history(Ref("d", "O:AAPL270115C00999000", "option"), start, end) == []
    assert [u for u, _ in client.calls] == [
        "https://cdn-api.cboe.com/api/global/delayed_quotes/options/AAPL.json",
        "https://cdn-api.cboe.com/api/global/delayed_quotes/options/_SPX.json",
    ]
    # A chain older than the range asked for gives nothing.
    assert (
        src.history(Ref("a", "O:AAPL270115C00230000", "option"), end + dt.timedelta(1), end) == []
    )


def test_cboe_prices_listed_stocks_and_waits_for_the_close():
    """Stocks and ETFs from CBOE (S4.3): daily closes for a backfill, and the day's close from
    the quote only once the market has closed; a symbol it doesn't list goes to the next
    source."""
    from pathlib import Path

    from moolakata.prices.cboe import Cboe

    answers = json.loads((Path(__file__).parent / "fixtures" / "cboe-listed.json").read_text())

    def answer(url):
        key = url.split("/delayed_quotes/", 1)[1].removesuffix(".json")
        return (200, answers[key]) if key in answers else (403, {})

    tsla = Ref("t", "TSLA", "equity")
    start, day = dt.date(2026, 10, 1), dt.date(2026, 10, 14)
    try:
        # 2:00 PM Eastern: the history only, up to yesterday's close.
        clock.fix(dt.datetime(2026, 10, 14, 18, 0, tzinfo=dt.UTC))
        rows = Cboe(FakeClient(answer), None).history(tsla, start, day)
        assert rows[-1] == (dt.date(2026, 10, 13), D("375.23")) and len(rows) == 7
        # 8:00 PM Eastern: today's close from the quote.
        clock.fix(dt.datetime(2026, 10, 15, 0, 0, tzinfo=dt.UTC))
        rows = Cboe(FakeClient(answer), None).history(tsla, start, day)
        assert rows[-1] == (day, D("367.16")) and len(rows) == 8
    finally:
        clock.fix(None)
    with pytest.raises(SourceError, match="doesn't list VFIAX"):
        Cboe(FakeClient(answer), None).history(Ref("f", "VFIAX", "etf"), start, day)
    assert "mutual-fund" not in Cboe.classes


def test_an_options_underlying_is_priced_held_or_not(server):
    """CR3-23: a short put on a stock the account doesn't hold has the stock priced, from the
    option's first trade, so its expiry has a close to decide it."""
    from edits import option_trade
    from test_accounts import new_account

    from moolakata.store.entities.accounts import Instrument

    make_user(server, "alice")
    c = sign_in(server, "alice")
    brk = new_account(c, name="Brokerage", type="brokerage")
    r = option_trade(c, brk["id"], "2026-09-02", "sell-to-open", "XYZ", "put", "50",
                     "2026-11-20", 1, "2.00")  # fmt: skip
    assert r.status_code == 200, r.text
    with server.db.read(unscoped="test") as s:
        got = {i.symbol: day for i, day in pricing.priced(s)}
        assert s.query(Instrument).filter_by(symbol="XYZ").one()
    assert got["XYZ"] == dt.date(2026, 9, 2) and "XYZ 20NOV26 50 P" in got


def test_a_days_price_is_its_ranges_last_point_and_never_another_users(server):
    """13.1, CR3-24: for every instrument and day, the day's price is the last point of the
    range ending that day, by one order of sources; a second user's trades, statement values
    and typed prices, on the same instruments and days, never price the first's."""
    import inspect

    from moolakata.store.entities.accounts import Holding, Instrument, Transaction
    from moolakata.store.entities.prices import Price, TypedPrice

    assert (
        inspect.signature(valuation.prices).parameters["owner"].default is inspect.Parameter.empty
    )
    clock.fix(dt.datetime(2026, 10, 13, 15, tzinfo=dt.UTC))
    try:
        pricing.install()
        for u in ("alice", "mallory"):
            make_user(server, u)
        ids_ = {}
        with server.db.tx(unscoped="test") as s:
            from moolakata.store.entities.users import User

            users = {u: s.query(User).filter_by(username=u).one().id for u in ("alice", "mallory")}
            accts = {}
            for u, uid in users.items():
                a = Account(id=ids.new_id("Acct"), ownerId=uid, name=f"{u} brokerage",
                            type="brokerage")  # fmt: skip
                s.add(a)
                accts[u] = a.id
            s.flush()
            shapes = ("closes", "typed", "statement", "trades", "late-closes", "fund")
            first = dt.date(2026, 6, 1)
            for k, shape in enumerate(shapes):
                cls = "money-market" if shape == "fund" else "equity"
                inst = Instrument(id=ids.new_id("Instr"), symbol=f"Z{k}", instrumentClass=cls)
                s.add(inst)
                s.flush()
                ids_[shape] = inst.id
                for who, base in (("alice", 100), ("mallory", 7)):
                    day0 = first - dt.timedelta(days=20)
                    s.add(Transaction(id=ids.new_id("Txn"), accountId=accts[who], date=day0,
                                      kind="buy", amount=-D(base), instrumentId=inst.id,
                                      quantity=D(1), price=D(base)))  # fmt: skip
                    s.flush()
                    if shape in ("statement",) or who == "mallory":
                        s.add(Holding(id=ids.new_id("Hold"), accountId=accts[who],
                                      instrumentId=inst.id, asOf=first + dt.timedelta(days=10),
                                      quantity=D(1), marketValue=D(base + 3)))  # fmt: skip
                    if shape == "typed" or who == "mallory":
                        s.add(TypedPrice(id=ids.new_id("TyPrc"), userId=users[who],
                                         instrumentId=inst.id, date=first + dt.timedelta(days=30),
                                         close=D(base + 5)))  # fmt: skip
                if shape in ("closes", "typed"):
                    for d in range(0, 120, 7):
                        when = first - dt.timedelta(days=3) + dt.timedelta(days=d)
                        s.add(Price(id=ids.new_id("Price"), instrumentId=inst.id, date=when,
                                    close=D(200 + d), source="test",
                                    fetchedAt=clock.now()))  # fmt: skip
                if shape == "late-closes":
                    s.add(Price(id=ids.new_id("Price"), instrumentId=inst.id,
                                date=first + dt.timedelta(days=45), close=D(300), source="test",
                                fetchedAt=clock.now()))  # fmt: skip
        last = dt.date(2026, 10, 1)
        mallory = {D(7), D(10), D(12)}  # her trade, statement and typed prices
        with server.db.read(unscoped="test") as s:
            points = valuation.price_points(s, list(ids_.values()), first, last,
                                            owner=users["alice"])  # fmt: skip
            day = first
            while day <= last:
                found = valuation.prices(s, list(ids_.values()), day, owner=users["alice"])
                for shape, iid in ids_.items():
                    pts = [p for d, p in points[iid] if d <= day]
                    want = pts[-1] if pts else None
                    got = found.get(iid)
                    assert (got.price if got else None) == want, (shape, day, got, want)
                    assert want not in mallory, (shape, day)
                day += dt.timedelta(days=1)
        # And the shapes mean what they say: alice's typed price wins on its day, her statement
        # stands before any close, her trade where nothing else is, a close once one comes.
        with server.db.read(unscoped="test") as s:
            on = valuation.prices(s, list(ids_.values()), last, owner=users["alice"])
        assert on[ids_["typed"]].source in ("close", "manual")
        assert on[ids_["statement"]].price == D(103) and on[ids_["trades"]].price == D(100)
        assert on[ids_["late-closes"]].price == D(300) and on[ids_["fund"]].price == D(1)
    finally:
        clock.fix(None)


# ---------- the refresh's parts, called plainly over rows written straight ----------

MONDAY = dt.datetime(2026, 10, 12, 22, tzinfo=dt.UTC)  # the clock held below; after the close
D0 = MONDAY.date()


def _d(month, day, year=2026):
    return dt.date(year, month, day)


CALLS: list = []  # each history asked of a recording source: (source, ref, start, end)
ANSWERS: dict = {}  # what a recording source answers for a symbol: closes, or an exception


@register
class Recorder(TickerSource):
    name = "recorder-test"
    label = "Recorder"
    classes = frozenset({"equity", "etf", "crypto", "option"})

    def history(self, ref, start, end):
        self.wait()
        CALLS.append((self.name, ref, start, end))
        answer = ANSWERS.get(ref.symbol, [])
        if isinstance(answer, BaseException):
            raise answer
        return answer


@register
class Keyed(Recorder):
    name = "keyed-test"
    label = "Keyed"
    classes = frozenset({"etf"})
    needs_key = True
    hosts = ("keyed.test",)
    limits = ((2, 3600.0),)


@register
class Idle(Recorder):
    name = "idle-test"
    label = "Idle"
    classes = frozenset({"mutual-fund"})


@register
class DevHosted(Recorder):
    name = "dev-hosted-test"
    label = "Dev hosted"
    classes = frozenset({"bond"})
    hosts = ("dev.test",)
    dev_only = True


class Published(list):
    def publish(self, kind, data=None, **_):
        self.append((kind, data))


@pytest.fixture
def monday():
    clock.fix(MONDAY)
    CALLS.clear()
    ANSWERS.clear()
    yield
    clock.fix(None)
    CALLS.clear()
    ANSWERS.clear()


class Rows:
    """Records written straight to the database, owned by the first admin."""

    def __init__(self, s):
        from moolakata.store.entities.users import User

        self.s = s
        self.owner = s.scalars(select(User).where(User.username == "admin")).one().id

    def add(self, row):
        self.s.add(row)
        self.s.flush()
        return row

    def account(self, deleted=False):
        gone = MONDAY if deleted else None
        return self.add(Account(id=ids.new_id("Acct"), ownerId=self.owner, name="B",
                                type="brokerage", deletedAt=gone))  # fmt: skip

    def inst(self, symbol, cls="equity", deleted=False):
        from moolakata.store.entities.accounts import Instrument

        return self.add(Instrument(id=ids.new_id("Instr"), symbol=symbol, instrumentClass=cls,
                                   deletedAt=MONDAY if deleted else None))  # fmt: skip

    def txn(self, acct, inst, day, kind="buy", deleted=False):
        from moolakata.store.entities.accounts import Lot, Transaction

        buy = kind == "buy"
        t = self.add(Transaction(id=ids.new_id("Txn"), accountId=acct.id, date=day, kind=kind,
                                 amount=D("-10.00") if buy else D("1.00"), instrumentId=inst.id,
                                 quantity=D(1) if buy else None, price=D(10) if buy else None,
                                 deletedAt=MONDAY if deleted else None))  # fmt: skip
        if buy:
            self.add(Lot(id=ids.new_id("Lot"), accountId=acct.id, instrumentId=inst.id,
                         transactionId=t.id, acquiredOn=day, quantity=D(1),
                         costBasis=D(10)))  # fmt: skip
        return t

    def holding(self, acct, inst, day, deleted=False):
        from moolakata.store.entities.accounts import Holding

        return self.add(Holding(id=ids.new_id("Hold"), accountId=acct.id, instrumentId=inst.id,
                                asOf=day, quantity=D(1), marketValue=D(10),
                                deletedAt=MONDAY if deleted else None))  # fmt: skip

    def price(self, inst, day, close=10, source="recorder-test", deleted=False):
        return self.add(Price(id=ids.new_id("Price"), instrumentId=inst.id, date=day,
                              close=D(close), source=source, fetchedAt=MONDAY,
                              deletedAt=MONDAY if deleted else None))  # fmt: skip

    def typed(self, inst, day, close=10):
        from moolakata.store.entities.prices import TypedPrice

        return self.add(TypedPrice(id=ids.new_id("TyPrc"), userId=self.owner,
                                   instrumentId=inst.id, date=day, close=D(close)))  # fmt: skip

    def contract(self, option, under, expiry, root=None, parts=None, deleted=False):
        from moolakata.store.entities.accounts import OptionContract

        deliverable = json.dumps([{"instrumentId": p.id, "shares": 50} for p in parts or []])
        return self.add(OptionContract(id=ids.new_id("OptCt"), instrumentId=option.id,
                                       underlyingId=under.id, right="put", strike=D(50),
                                       expiry=expiry, root=root,
                                       deliverable=deliverable if parts else None,
                                       deletedAt=MONDAY if deleted else None))  # fmt: skip

    def item(self, acct, metal, day, valuation="spot", deleted=False):
        from moolakata.store.entities.assets import Item

        return self.add(Item(id=ids.new_id("Item"), accountId=acct.id, name=metal,
                             acquiredOn=day, costBasis=D(100), valuation=valuation, metal=metal,
                             unitWeight=D(1), weightUnit="ozt", purity=D("0.9999"),
                             deletedAt=MONDAY if deleted else None))  # fmt: skip

    def source(self, name, preference=None, enabled=True, deleted=False, **kw):
        return self.add(PriceSource(id=ids.new_id("Src"), name=name, enabled=enabled,
                                    preference=json.dumps(preference or {}),
                                    deletedAt=MONDAY if deleted else None, **kw))  # fmt: skip


def test_a_days_close_is_the_latest_live_one_and_says_how_old_it_is(server, monday):
    """S4.6, S4.7: the latest close on or before the day for each instrument, never a deleted
    one nor another instrument's day; a coin's close from Friday is stale on Monday, a stock's
    isn't."""
    with server.db.tx(unscoped="test") as s:
        r = Rows(s)
        coin, stock, fixed = r.inst("C1", "crypto"), r.inst("S1"), r.inst("X1")
        r.price(coin, _d(10, 9))
        r.price(stock, _d(10, 9))
        r.price(fixed, _d(10, 8), 100)
        r.price(fixed, _d(10, 9), 999, deleted=True)
        # Pairs where one's latest day is a day the other has an older close on: the latest
        # of each is its own, whichever is read first.
        pairs = []
        for first_late in (True, False):
            a, b = r.inst(f"P{first_late:d}"), r.inst(f"Q{first_late:d}")
            for day in (_d(10, 2), _d(10, 1)) if first_late else (_d(10, 1), _d(10, 2)):
                r.price(a, day, day.day)
            r.price(b, _d(10, 1))
            pairs.append(a)
        ids_ = [coin.id, stock.id, fixed.id, *(p.id for p in pairs)]
    with server.db.read(unscoped="test") as s:
        got = pricing.stored_closes(s, ids_, D0)
    assert got[coin.id] == valuation.Price(D(10), _d(10, 9), "close", True)
    assert got[stock.id] == valuation.Price(D(10), _d(10, 9), "close", False)
    assert got[fixed.id] == valuation.Price(D(100), _d(10, 8), "close", False)
    assert [got[p.id].asOf for p in pairs] == [_d(10, 2), _d(10, 2)]
    assert len(got) == len(ids_)


def test_a_close_history_is_one_instruments_live_closes_after_first_up_to_last_by_day(
    server, monday
):
    with server.db.tx(unscoped="test") as s:
        r = Rows(s)
        a, b = r.inst("A1"), r.inst("B1")
        for day in (_d(10, 9), _d(10, 10), _d(10, 5), _d(10, 1), _d(10, 2)):
            r.price(a, day, day.day)
        r.price(a, _d(10, 6), 6, deleted=True)
        r.price(b, _d(10, 3), 3)
    with server.db.read(unscoped="test") as s:
        got = pricing.close_history(s, [a.id], _d(10, 1), _d(10, 9))
    assert got == {a.id: [(_d(10, 2), D(2)), (_d(10, 5), D(5)), (_d(10, 9), D(9))]}


def test_the_last_stored_close_is_the_latest_fetched_live_one(server, monday):
    """A deleted close is never where a refresh resumes."""
    with server.db.tx(unscoped="test") as s:
        r = Rows(s)
        a, b = r.inst("A1"), r.inst("B1")
        r.price(a, _d(10, 5))
        r.price(a, _d(10, 9), deleted=True)
        r.price(b, _d(10, 2))
    with server.db.read(unscoped="test") as s:
        assert pricing.last_stored(s) == {a.id: _d(10, 5), b.id: _d(10, 2)}


def test_storing_adds_new_closes_replaces_changed_fetched_ones_and_counts_both(server, monday):
    """S4.6: a close fetched again unchanged is left be and not counted; a changed one is
    replaced and counted; another instrument's close on the same day is no reason to skip
    one."""
    with server.db.tx(unscoped="test") as s:
        r = Rows(s)
        a, b = r.inst("A1"), r.inst("B1")
        r.price(a, _d(10, 1), 10, source="old-test")
        r.price(a, _d(10, 2), 20, source="old-test")
        r.price(b, _d(10, 4), 40, source="old-test")
    with server.db.tx(unscoped="test") as s:
        assert pricing.store(s, a.id, [], "new-test") == 0
        closes = [(_d(10, 1), D(10)), (_d(10, 2), D(21)), (_d(10, 3), D(31)),
                  (_d(10, 4), D(44)), (_d(10, 5), D(50))]  # fmt: skip
        assert pricing.store(s, a.id, closes, "new-test") == 4
    with server.db.read(unscoped="test") as s:
        rows = {(p.instrumentId, p.date): (p.close, p.source) for p in s.scalars(select(Price))}
    assert rows == {
        (a.id, _d(10, 1)): (D(10), "old-test"),
        (a.id, _d(10, 2)): (D(21), "new-test"),
        (a.id, _d(10, 3)): (D(31), "new-test"),
        (a.id, _d(10, 4)): (D(44), "new-test"),
        (a.id, _d(10, 5)): (D(50), "new-test"),
        (b.id, _d(10, 4)): (D(40), "old-test"),
    }


def test_the_sources_in_use_and_their_order_for_a_class(server, monday):
    """S4.2: only live, enabled sources this server knows, the dev stub only in dev mode; for a
    class, by its rank, those not ranked for it after every ranked one, oldest first."""
    with server.db.tx(unscoped="test") as s:
        r = Rows(s)
        t = MONDAY - dt.timedelta(days=10)
        unranked = r.source("recorder-test", {"equity": 1}, createdAt=t)
        second = r.source("keyed-test", {"etf": 2}, createdAt=t + dt.timedelta(days=1))
        first = r.source("stub", {"etf": 1}, createdAt=t + dt.timedelta(days=2))
        hosted = r.source("dev-hosted-test")
        r.source("broken-test", enabled=False)
        r.source("garbled-test", deleted=True)
        r.source("gone-test")  # a source this server no longer has
    with server.db.read(unscoped="test") as s:
        dev = pricing.enabled(s, True)
        assert {x.id for x in dev} == {unranked.id, second.id, first.id, hosted.id}
        assert {x.id for x in pricing.enabled(s, False)} == {unranked.id, second.id}
        assert [x.id for x in pricing.for_class(dev, "etf")] == [first.id, second.id, unranked.id]
        assert pricing.hosts(s, True) == ["dev.test", "keyed.test"]
        assert pricing.hosts(s, False) == ["keyed.test"]


def test_what_is_priced_and_from_when(server, monday):
    """S4.4: what an open lot in a live account holds, from its first live trade or statement
    in a live account; an open option's underlying, or an adjusted contract's parts instead,
    from the option's first trade; a metal held at spot from its first live item; the
    benchmarks for five years; never cash or a money-market fund."""
    with server.db.tx(unscoped="test") as s:
        r = Rows(s)
        trades, gone, statements = r.account(), r.account(deleted=True), r.account()
        e1 = r.inst("E1")
        r.txn(trades, e1, _d(1, 10))
        r.txn(trades, e1, _d(1, 1), kind="dividend", deleted=True)
        r.txn(gone, e1, _d(1, 5))
        r.txn(gone, r.inst("E2"), _d(2, 1))  # held only where deleted
        e3, e4 = r.inst("E3"), r.inst("E4")
        r.txn(trades, e3, _d(2, 10))
        r.holding(statements, e3, _d(2, 1))  # a statement before the trade
        r.txn(trades, e4, _d(3, 1))
        r.holding(statements, e4, _d(3, 20))  # and after
        h1 = r.inst("H1")
        r.holding(statements, h1, _d(3, 1))
        r.holding(r.account(), h1, _d(2, 1), deleted=True)  # its account holds nothing else
        r.holding(gone, h1, _d(1, 20))
        r.holding(trades, r.inst("N1"), _d(1, 2))  # an account kept by trades: not held
        mm, cash = r.inst("MM1", "money-market"), r.inst("CASH1", "cash")
        r.txn(trades, mm, _d(1, 10))
        r.txn(trades, cash, _d(1, 10))
        u1, opt1 = r.inst("U1"), r.inst("OPT1", "option")
        r.contract(opt1, u1, _d(12, 18))
        r.txn(trades, opt1, _d(4, 1))
        u2, z, opt2 = r.inst("U2"), r.inst("Z"), r.inst("OPT2", "option")
        r.txn(trades, u2, _d(1, 15))
        r.contract(opt2, z, _d(12, 18), deleted=True)
        r.contract(opt2, u2, _d(12, 18))
        r.txn(trades, opt2, _d(5, 1))
        u3, p1, p2, opt3 = r.inst("U3"), r.inst("PT1"), r.inst("PT2"), r.inst("OPT3", "option")
        r.contract(opt3, u3, _d(12, 18), root="U31", parts=[p1, p2])
        r.txn(trades, opt3, _d(6, 1))
        r.contract(r.inst("OPT4", "option"), r.inst("U4"), _d(12, 18))  # never traded
        r.inst("XAU", "metal", deleted=True)
        xau, xpt = r.inst("XAU", "metal"), r.inst("XPT", "metal")
        r.item(trades, "gold", _d(2, 5))
        r.item(trades, "gold", _d(1, 1), valuation="valuations")
        r.item(trades, "gold", _d(1, 2), deleted=True)
        r.item(gone, "gold", _d(1, 3))
        r.item(trades, "silver", _d(2, 1))  # no silver instrument: nothing to price
        r.txn(trades, xpt, _d(1, 20))
        r.item(trades, "platinum", _d(2, 5))
        spy = r.inst("SPY", "etf")
        r.inst("VT", "etf", deleted=True)
    want = {
        e1.id: _d(1, 10), e3.id: _d(2, 1), e4.id: _d(3, 1), h1.id: _d(3, 1),
        u1.id: _d(4, 1), opt1.id: _d(4, 1), u2.id: _d(1, 15), opt2.id: _d(5, 1),
        p1.id: _d(6, 1), p2.id: _d(6, 1), opt3.id: _d(6, 1), xau.id: _d(2, 5),
        xpt.id: _d(1, 20), spy.id: D0 - dt.timedelta(days=pricing.BACKFILL_DAYS),
    }  # fmt: skip
    held = {e1.id, e3.id, e4.id, h1.id, mm.id, cash.id, opt1.id, u2.id, opt2.id, opt3.id, xpt.id}
    with server.db.read(unscoped="test") as s:
        got = pricing.priced(s)
        assert {i.id: day for i, day in got} == want and len(got) == len(want)
        assert pricing.held(s) == held
        by = pricing._held_by(s, r.owner)
        assert sorted(by) == sorted(held - {mm.id, cash.id})


def test_the_headers_prices_are_stale_when_one_the_viewer_holds_is(server, monday):
    """S12.5, S4.10: the viewer's held instruments, by their latest close or a price the viewer
    typed on its day or after it; one with no price at all is stale too."""
    with server.db.tx(unscoped="test") as s:
        r = Rows(s)
        owner, acct = r.owner, r.account()
        r.source("stub", lastOkAt=MONDAY - dt.timedelta(hours=2))
        r.source("recorder-test", lastOkAt=MONDAY - dt.timedelta(hours=1))
        r.source("idle-test")

    def status(dev=True):
        with server.db.read(unscoped="test") as s:
            return pricing.status(s, dev, owner)

    def write(*steps):
        with server.db.tx(unscoped="test") as s:
            r = Rows(s)
            return [step(r) for step in steps]

    last = MONDAY - dt.timedelta(hours=1)
    assert status() == {"lastRefresh": last, "stale": False, "sources": 3}
    assert status(dev=False) == {"lastRefresh": last, "stale": False, "sources": 2}
    [e] = write(lambda r: r.inst("E"))
    write(lambda r: r.txn(acct, e, _d(9, 1)), lambda r: r.price(e, _d(10, 9)))
    assert status()["stale"] is False
    [f] = write(lambda r: r.inst("F"))
    write(lambda r: r.txn(acct, f, _d(9, 1)))
    assert status()["stale"] is True  # no price at all
    write(lambda r: r.typed(f, D0))
    assert status()["stale"] is False
    [g] = write(lambda r: r.inst("G"))
    write(lambda r: r.txn(acct, g, _d(9, 1)), lambda r: r.price(g, _d(9, 30)),
          lambda r: r.typed(g, _d(9, 29)))  # fmt: skip
    assert status()["stale"] is True  # the close is the latest, and old
    write(lambda r: r.typed(g, _d(9, 30)))
    assert status()["stale"] is False  # typed on the close's day: the typed price
    [h] = write(lambda r: r.inst("H"))
    write(lambda r: r.txn(acct, h, _d(7, 1)), lambda r: r.typed(h, _d(7, 3)))
    assert status()["stale"] is True  # typed over 90 days ago


def test_a_source_is_built_with_its_key_its_client_and_its_tasks_limits(server, monday):
    """S4.2.2: a source that needs a key gets it, one that calls out gets a client, and in a
    task its calls wait on the task's limits for it; outside one, nothing waits."""
    import threading

    from moolakata import net
    from moolakata.store.repos import secrets as secret_repo
    from moolakata.tasks import ProviderLimits, TaskContext

    with server.db.tx(unscoped="test") as s:
        r = Rows(s)
        keyed, plain = r.source("keyed-test"), r.source("recorder-test")
        secret_repo.put(s, server.keys.secrets, "PriceSource", keyed.id, "apiKey", "k-123", None)
    built = pricing.build(server, plain, None)
    assert built.key is None and built.client is None
    built.wait()
    built = pricing.build(server, keyed, None)
    assert built.key == "k-123" and isinstance(built.client, net.Client)
    built.wait()
    built.wait()
    built.wait()  # past its limits: outside a task nothing waits
    ctx = TaskContext("prices", threading.Event(), ProviderLimits())
    built = pricing.build(server, keyed, ctx)
    assert built.key == "k-123" and isinstance(built.client, net.Client)
    built.wait()
    built.wait()
    assert ctx.limits.delay("keyed-test") > 0  # its two calls an hour, taken


def test_a_refresh_asks_each_source_for_what_is_missing_and_stores_it(server, monday):
    """S4.4: from the day after the last stored close, or a week before the first trade and
    never past five years; an option by its OCC ticker until it expires; a metal's spot from
    its proxy, per ounce, to the cent (S4.3); what no source serves is counted unpriced."""
    import threading

    from moolakata.projections import taxtables
    from moolakata.store.repos import secrets as secret_repo
    from moolakata.tasks import ProviderLimits, TaskContext

    server.events = Published()
    with server.db.tx(unscoped="test") as s:
        r = Rows(s)
        idle = r.source("idle-test")  # serves nothing held: never run
        keyed = r.source("keyed-test", {"etf": 1})
        rec = r.source("recorder-test")
        secret_repo.put(s, server.keys.secrets, "PriceSource", keyed.id, "apiKey", "k", None)
        acct = r.account()
        e0, e1, e2, e3, e4 = (r.inst(f"E{k}") for k in range(5))
        for e in (e0, e1, e2, e3):
            r.txn(acct, e, _d(9, 1))
        r.txn(acct, e4, _d(1, 2, 2015))
        r.price(e0, D0)  # up to date
        r.price(e2, _d(10, 9))
        r.price(e3, _d(10, 11))
        und = r.inst("UND")
        opts = {k: r.inst(f"O{k}", "option") for k in ("open", "root", "old", "today", "bare")}
        r.contract(opts["open"], und, _d(12, 18))
        r.contract(opts["root"], und, _d(11, 20), root="UND1")
        r.contract(opts["old"], und, _d(10, 1))
        r.contract(opts["today"], und, D0)
        for o in opts.values():  # "bare" has no contract: a file's option MoolaKata couldn't read
            r.txn(acct, o, _d(9, 15))
        r.price(opts["old"], _d(10, 5))
        r.price(opts["today"], _d(10, 11))
        xau, xag = r.inst("XAU", "metal"), r.inst("XAG", "metal")
        r.txn(acct, xau, _d(9, 1))
        r.txn(acct, xag, _d(9, 1))
        for k in (1, 2):
            r.txn(acct, r.inst(f"BOND{k}", "bond"), _d(9, 1))
        r.txn(acct, r.inst("MM1", "money-market"), _d(9, 1))
        spy = r.inst("SPY", "etf")
        silver = D(str(taxtables.figures(s)["slvOzPerShare"]))
    ANSWERS.update({
        "E1": [(_d(10, 8), D("10.50")), (_d(10, 9), D("10.75"))],
        "E2": [(D0, D(20))],
        "PAXG": [(_d(10, 9), D("2650.125"))],
        "SLV": [(_d(10, 9), D("27.50"))],
        "SPY": [(_d(10, 9), D(580))],
    })  # fmt: skip
    ctx = TaskContext("prices", threading.Event(), ProviderLimits())
    assert pricing.refresh(server, ctx) == {"stored": 6, "unpriced": 2}
    week = dt.timedelta(days=7)
    backfill = D0 - dt.timedelta(days=pricing.BACKFILL_DAYS)
    assert sorted(CALLS, key=repr) == sorted([
        ("recorder-test", Ref(e1.id, "E1", "equity"), _d(9, 1) - week, D0),
        ("recorder-test", Ref(e2.id, "E2", "equity"), _d(10, 10), D0),
        ("recorder-test", Ref(e3.id, "E3", "equity"), D0, D0),
        ("recorder-test", Ref(e4.id, "E4", "equity"), backfill, D0),
        ("recorder-test", Ref(und.id, "UND", "equity"), _d(9, 8), D0),
        ("recorder-test", Ref(opts["open"].id, "O:UND261218P00050000", "option"), _d(9, 8), D0),
        ("recorder-test", Ref(opts["root"].id, "O:UND1261120P00050000", "option"), _d(9, 8), D0),
        ("recorder-test", Ref(opts["today"].id, "O:UND261012P00050000", "option"), D0, D0),
        ("recorder-test", Ref(xau.id, "PAXG", "crypto"), _d(9, 1) - week, D0),
        ("keyed-test", Ref(xag.id, "SLV", "etf"), _d(9, 1) - week, D0),
        ("keyed-test", Ref(spy.id, "SPY", "etf"), backfill, D0),
    ], key=repr)  # fmt: skip
    assert ctx.limits.delay("keyed-test") > 0  # the task's limits, used
    assert server.events == [("prices", {"asOf": MONDAY.isoformat(), "stored": 6})]
    with server.db.read(unscoped="test") as s:
        closes = pricing.stored_closes(s, [xau.id, xag.id], D0)
        rows = {x.id: x for x in s.scalars(select(PriceSource))}
    assert closes[xau.id].price == D("2650.12")
    assert closes[xag.id].price == (D("27.50") / silver).quantize(D("0.01"))
    assert (rows[idle.id].lastRunAt, rows[idle.id].lastOkAt) == (None, None)
    for x in (keyed, rec):
        assert (rows[x.id].lastRunAt, rows[x.id].lastOkAt, rows[x.id].lastError) == (
            MONDAY, MONDAY, None)  # fmt: skip


def test_a_source_that_fails_for_one_instrument_is_still_ok(server, monday, caplog):
    """S4.4: each failure falls back to the next source; one that answers once is ok, with no
    error kept; an answer a source couldn't read is logged, a source's own failure isn't; a
    task stopping stops the refresh."""
    import threading

    from moolakata.tasks import ProviderLimits, Stopping, TaskContext

    with server.db.tx(unscoped="test") as s:
        r = Rows(s)
        broken, garbled = r.source("broken-test", {"etf": 1}), r.source("garbled-test", {"etf": 2})
        rec = r.source("recorder-test", {"etf": 3})
        acct = r.account()
        for symbol in ("VTI", "VTX"):
            r.txn(acct, r.inst(symbol, "etf"), _d(10, 1))
    ANSWERS.update({"VTI": [(_d(10, 9), D(250))], "VTX": SourceError("Recorder answered 500")})
    with caplog.at_level("WARNING", logger="moolakata.prices"):
        assert pricing.refresh(server) == {"stored": 1, "unpriced": 0}
    assert sorted(x.getMessage() for x in caplog.records if x.name == "moolakata.prices") == [
        f"garbled-test failed for {symbol}: ValueError('unexpected token at line 1')"
        for symbol in ("VTI", "VTX")
    ]
    with server.db.read(unscoped="test") as s:
        rows = {x.id: x for x in s.scalars(select(PriceSource))}
    assert rows[broken.id].lastError == "Broken answered HTTP 500"
    assert rows[garbled.id].lastError == "an answer it couldn't read"
    assert rows[rec.id].lastError is None and rows[rec.id].lastOkAt == MONDAY
    ANSWERS["VTX"] = Stopping()
    with pytest.raises(Stopping):
        pricing.refresh(server)
    ctx = TaskContext("prices", threading.Event(), ProviderLimits())
    ctx.stop.set()
    with pytest.raises(Stopping):
        pricing.refresh(server, ctx)
