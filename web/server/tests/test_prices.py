import datetime as dt
import json
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import change, create, remove, saved
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
    rows = Stub(None, None).history(Ref("i", "VTI", "etf"), TODAY - dt.timedelta(days=10), TODAY)
    assert rows and rows[-1][0] < TODAY
    assert all(d.weekday() < 5 for d, _ in rows)
    crypto = Stub(None, None).history(
        Ref("i", "BTC", "crypto"), TODAY - dt.timedelta(days=3), TODAY
    )
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
    with server.db.tx() as s:
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
    with server.db.tx() as s:
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
    with server.db.read() as s:
        rows = {r.name: r for r in s.scalars(select(PriceSource))}
        assert rows["broken-test"].lastError == "Broken answered HTTP 500"
        assert rows["stub"].lastOkAt is not None and rows["stub"].lastError is None
        n = s.scalar(select(func.count()).select_from(Price))
        p = pricing.stored_closes(s, [inst_id], TODAY)[inst_id]
        assert p.source == "close" and not p.stale
    assert pricing.refresh(server)["stored"] == 0  # nothing new: nothing stored twice
    with server.db.read() as s:
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
    with pytest.raises(SourceError):
        pricing.refresh(server)


def test_an_unreadable_answer_falls_back_like_a_failure(server):
    pricing.install()
    server.config = server.config.__class__(**{**server.config.__dict__, "dev": True})
    _book(server, make_user(server, "alice"))
    _source(server, "garbled-test", 1)
    _source(server, "stub", 2)
    assert pricing.refresh(server)["stored"] > 10
    with server.db.read() as s:
        rows = {r.name: r for r in s.scalars(select(PriceSource))}
        assert rows["garbled-test"].lastError == "an answer it couldn't read"


def test_only_what_is_held_is_priced(server):
    from moolakata.store.entities.accounts import Transaction

    account_id, inst_id = _book(server, make_user(server, "alice"))
    with server.db.read() as s:
        assert inst_id in {i.id for i, _ in pricing.priced(s, benchmarks=False)}
    with server.db.tx() as s:
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
    with server.db.read() as s:
        assert pricing.priced(s, benchmarks=False) == []  # sold: no longer fetched


def test_staleness():
    friday = dt.date(2026, 10, 9)
    assert not pricing.is_stale("option", "close", friday, dt.date(2026, 10, 12))
    assert pricing.is_stale("option", "close", friday, dt.date(2026, 10, 13))
    friday = dt.date(2026, 10, 9)
    assert not pricing.is_stale("etf", "close", friday, dt.date(2026, 10, 13))
    assert pricing.is_stale("etf", "close", friday, dt.date(2026, 10, 15))
    assert pricing.is_stale("crypto", "close", friday, dt.date(2026, 10, 12))
    assert not pricing.is_stale("other", "manual", friday, dt.date(2026, 12, 31))
    assert pricing.is_stale("other", "manual", friday, dt.date(2027, 2, 1))


def test_price_sources_in_settings(admin_client, server):
    view = admin_client.get("/ui/api/price-sources").json()
    names = {s["name"] for s in view["available"]}
    assert {"tiingo", "coinbase", "manual"} <= names and "stub" not in names
    assert view["refreshTime"] == "18:00"
    r = admin_client.post("/ui/api/price-sources", json={"name": "tiingo"})
    assert r.status_code == 201
    src = r.json()["sources"][0]
    assert src["enabled"] is False and src["needsKey"] and src["key"] is None
    r = change(admin_client, "Src", src, enabled=True)
    assert r.json()["errors"][0]["code"] == "key-needed"
    r = change(admin_client, "Src", src, apiKey="abcdef0123456789", enabled=True)
    row = saved(r)
    assert row["enabled"] and row["key"]["setBy"] == "Ada Admin"
    assert "abcdef0123456789" not in r.text
    with pytest.raises(Exception, match="not a host"):
        server.guard.check("api.exchange.coinbase.com", 443)
    assert admin_client.post("/ui/api/price-sources", json={"name": "tiingo"}).status_code == 409
    assert admin_client.post("/ui/api/price-sources", json={"name": "stub"}).status_code == 422
    assert remove(admin_client, "Src", row).status_code == 200
    from moolakata.store.repos import secrets as secret_repo

    with server.db.read() as s:
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
    with server.db.tx() as s:
        figures.ensure_benchmarks(s)  # as a real start does
    with server.db.read() as s:
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
