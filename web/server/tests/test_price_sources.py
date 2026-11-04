"""The price sources' contract with the outside world (S4.2): every answer a source can get, a
price, nothing, a refusal, a limit, an error, a body that isn't JSON, no network at all, each
becoming a figure or a failure worded for Settings. No server, no network: a client answers
what each test says."""

import datetime as dt
import json
import time
from decimal import Decimal as D

import pytest

from moolakata import clock
from moolakata.prices.base import SOURCES, Quote, Ref, SourceError, TickerSource, register
from moolakata.prices.cboe import Cboe, mark, split_occ
from moolakata.prices.coinbase import Coinbase
from moolakata.prices.massive import Massive
from moolakata.prices.stub import Stub, _seed, walk
from moolakata.prices.tiingo import Tiingo

d = dt.date


class Answer:
    def __init__(self, status):
        self.status_code = status


class Client:
    """Answers each call with (status, body): a body is JSON unless it is bytes; an exception
    is raised instead."""

    def __init__(self, *answers):
        self.answers, self.urls, self.kws = list(answers), [], []

    def get_bytes(self, url, **kw):
        self.urls.append(url)
        self.kws.append(kw)
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(a, Exception):
            raise a
        status, body = a
        return Answer(status), body if isinstance(body, bytes) else json.dumps(body).encode()


class Plain(TickerSource):
    name, label, classes = "plain", "The plain source", frozenset({"equity"})

    def history(self, ref, start, end):
        return self.get_json("https://x.invalid/h") or []


@pytest.mark.parametrize(
    ("answer", "outcome"),
    [
        ((200, {"a": 1.5}), {"a": D("1.5")}),  # prices as written, never through a float
        ((404, {}), None),
        ((401, {}), "The plain source refused the key (HTTP 401)"),
        ((403, {}), "The plain source refused the key (HTTP 403)"),
        ((429, {}), "The plain source says the limit is reached (HTTP 429)"),
        ((502, {}), "The plain source answered HTTP 502"),
        ((200, b"<html>"), "The plain source answered with something that is not JSON"),
        (TimeoutError(), "The plain source could not be reached (TimeoutError)"),
    ],
)
def test_an_answer_is_a_figure_or_a_failure_worded_for_settings(answer, outcome):
    src = Plain(Client(answer), None)
    if isinstance(outcome, str):
        with pytest.raises(SourceError) as e:
            src.get_json("https://x.invalid/q")
        assert str(e.value) == outcome
    else:
        assert src.get_json("https://x.invalid/q") == outcome


def test_without_a_network_client_a_source_says_so():
    with pytest.raises(SourceError, match="The plain source has no network client"):
        Plain(None, None).get_json("https://x.invalid/q")
    with pytest.raises(SourceError, match="CBOE delayed quotes has no network client"):
        Cboe(None, None).listed("quotes", "VTI")


def test_quotes_are_each_instruments_latest_close_in_ten_days():
    class Recent(Plain):
        def history(self, ref, start, end):
            assert (start, end) == (d(2026, 10, 3), d(2026, 10, 13))
            return {"A": [(d(2026, 10, 9), D(10)), (d(2026, 10, 12), D(11))], "B": []}[ref.id]

    clock.fix(dt.datetime(2026, 10, 13, 15, tzinfo=dt.UTC))
    try:
        got = Recent(None, None).quotes([Ref("A", "AAA", "equity"), Ref("B", "BBB", "equity")])
    finally:
        clock.fix(None)
    assert got == {"A": Quote(D(11), d(2026, 10, 12))}
    assert Plain(None, None).lookup("VTI") is None  # a source that can't check a symbol


def test_massive_reads_its_daily_bars_and_needs_its_key():
    bars = {"results": [{"t": 1760486400000, "c": 6.25}, {"t": 1760400000000, "c": 6.1}]}
    src = Massive(Client((200, bars)), "k")
    got = src.history(Ref("i", "O:MSFT261120P00480000", "option"), d(2026, 10, 14), d(2026, 10, 15))
    assert got == [(d(2025, 10, 14), D("6.1")), (d(2025, 10, 15), D("6.25"))]
    assert "/ticker/O%3AMSFT261120P00480000/range/1/day/2026-10-14/2026-10-15" in src.client.urls[0]
    assert src.client.urls[0].endswith("&apiKey=k")
    assert Massive(Client((200, {})), "k").history(Ref("i", "O:X", "option"), d(2026, 1, 1),
                                                    d(2026, 1, 2)) == []  # fmt: skip
    with pytest.raises(SourceError, match="Massive needs its API key"):
        Massive(Client((200, bars)), None).history(Ref("i", "O:X", "option"), d(2026, 1, 1),
                                                   d(2026, 1, 2))  # fmt: skip


def test_tiingo_skips_a_day_without_a_close_and_checks_a_symbol():
    rows = [{"date": "2026-10-13T00:00:00.000Z", "close": 101.5},
            {"date": "2026-10-12T00:00:00.000Z", "close": None}]  # fmt: skip
    src = Tiingo(Client((200, rows)), "k")
    assert src.history(Ref("i", "VTI", "etf"), d(2026, 10, 12), d(2026, 10, 13)) == [
        (d(2026, 10, 13), D("101.5"))
    ]
    assert Tiingo(Client((200, [])), "k").history(Ref("i", "VTI", "etf"), d(2026, 10, 12),
                                                   d(2026, 10, 13)) == []  # fmt: skip
    found = Tiingo(Client((200, {"ticker": "vti", "name": "Vanguard Total"})), "k")
    assert found.lookup("vti") == {"symbol": "VTI", "name": "Vanguard Total"}
    assert Tiingo(Client((404, {})), "k").lookup("NOPE") is None


def test_cboe_names_what_it_cant_read():
    with pytest.raises(SourceError, match="MSFT is not an OCC option ticker"):
        split_occ("MSFT")
    assert split_occ("O:MSFT261120P00480000") == ("MSFT", "261120P00480000")
    # The last trade when there is no two-sided quote; nothing when it never traded.
    assert mark({"bid": 0, "ask": 1.2, "last_trade_price": 1.005}) == D("1.00")
    assert mark({"bid": 0, "ask": 0, "last_trade_price": 0}) is None
    with pytest.raises(SourceError, match="answered without a date for _SPX"):
        Cboe(Client((200, {"data": {"options": []}})), None).chain("_SPX")
    cases = [
        (TimeoutError(), "CBOE delayed quotes could not be reached (TimeoutError)"),
        ((404, {}), "CBOE delayed quotes doesn't list VTI"),
        ((500, {}), "CBOE delayed quotes answered HTTP 500"),
        ((200, b"nope"), "CBOE delayed quotes answered with something that is not JSON"),
        ((200, [1, 2]), "CBOE delayed quotes answered with something that is not JSON"),
    ]
    for answer, want in cases:
        with pytest.raises(SourceError) as e:
            Cboe(Client(answer), None).listed("quotes", "VTI")
        assert str(e.value) == want


@pytest.fixture
def at():
    """The clock fixed where the test says, and freed after it."""
    yield clock.fix
    clock.fix(None)


@pytest.fixture
def chicago(monkeypatch):
    """Local time hours behind UTC, so a day read in local time rather than UTC shows."""
    monkeypatch.setenv("TZ", "America/Chicago")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def utc_midnight(day: dt.date) -> int:
    return int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp())


def test_every_source_is_registered_by_its_name():
    assert SOURCES["cboe"] is Cboe and SOURCES["tiingo"] is Tiingo and SOURCES["stub"] is Stub
    try:
        assert register(Plain) is Plain and SOURCES["plain"] is Plain
    finally:
        SOURCES.pop("plain", None)


@pytest.mark.parametrize(
    ("status", "outcome"), [(400, "The plain source answered HTTP 400"), (399, {"a": D(1)})]
)
def test_any_answer_from_400_up_is_a_failure(status, outcome):
    src = Plain(Client((status, {"a": 1})), None)
    if isinstance(outcome, str):
        with pytest.raises(SourceError) as e:
            src.get_json("https://x.invalid/q")
        assert str(e.value) == outcome
    else:
        assert src.get_json("https://x.invalid/q") == outcome


def test_a_price_is_read_as_its_digits_never_through_a_float():
    got = Plain(Client((200, {"a": 0.1})), None).get_json("https://x.invalid/q")
    assert type(got["a"]) is D and got["a"] == D("0.1")
    listed = Cboe(Client((200, {"data": {"close": 0.1}})), None).listed("quotes", "VTI")
    assert type(listed["close"]) is D and listed["close"] == D("0.1")


def test_a_quote_is_the_last_of_several_closes(at):
    class Three(Plain):
        def history(self, ref, start, end):
            return [(d(2026, 10, 8), D(9)), (d(2026, 10, 9), D(10)), (d(2026, 10, 12), D(11))]

    at(dt.datetime(2026, 10, 13, 15, tzinfo=dt.UTC))
    got = Three(None, None).quotes([Ref("A", "AAA", "equity")])
    assert got == {"A": Quote(D(11), d(2026, 10, 12))}


def test_massive_and_tiingo_say_which_key_is_missing():
    ref = Ref("i", "O:X", "option")
    with pytest.raises(SourceError) as e:
        Massive(Client((200, {})), None).history(ref, d(2026, 1, 1), d(2026, 1, 2))
    assert str(e.value) == "Massive needs its API key"
    with pytest.raises(SourceError) as e:
        Tiingo(Client((200, [])), "").history(Ref("i", "VTI", "etf"), d(2026, 1, 1), d(2026, 1, 2))
    assert str(e.value) == "Tiingo needs its API key"


def test_a_bars_day_is_its_utc_day_wherever_the_server_is(chicago, at):
    """Massive and Coinbase stamp a daily bar at midnight UTC: read in Chicago's time, it would
    land on the day before."""
    bars = {"results": [{"t": utc_midnight(d(2026, 10, 12)) * 1000, "c": 6.25}]}
    got = Massive(Client((200, bars)), "k").history(
        Ref("i", "O:X", "option"), d(2026, 10, 12), d(2026, 10, 12)
    )
    assert got == [(d(2026, 10, 12), D("6.25"))]
    at(dt.datetime(2026, 10, 13, 15, tzinfo=dt.UTC))
    candles = [[utc_midnight(d(2026, 10, 12)), 1, 2, 1, 1.5, 9]]
    got = Coinbase(Client((200, candles)), None).history(
        Ref("i", "BTC", "crypto"), d(2026, 10, 12), d(2026, 10, 12)
    )
    assert got == [(d(2026, 10, 12), D("1.5"))]


def test_coinbase_asks_300_days_a_call_and_leaves_out_todays_open_candle(at):
    at(dt.datetime(2026, 10, 13, 15, tzinfo=dt.UTC))
    first = [[utc_midnight(d(2025, 12, 1)), 1, 2, 1, 90000.5, 9]]
    # Newest first, as Coinbase answers; today's candle is still open and isn't kept.
    second = [
        [utc_midnight(d(2026, 10, 13)), 1, 2, 1, 99999, 9],
        [utc_midnight(d(2026, 10, 12)), 1, 2, 1, 98000, 9],
        [utc_midnight(d(2026, 9, 27)), 1, 2, 1, 97000, 9],
    ]
    src = Coinbase(Client((200, first), (200, second)), None)
    got = src.history(Ref("i", "btc", "crypto"), d(2025, 12, 1), d(2026, 10, 13))
    assert got == [
        (d(2025, 12, 1), D("90000.5")),
        (d(2026, 9, 27), D(97000)),
        (d(2026, 10, 12), D(98000)),
    ]
    base = "https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400"
    assert src.client.urls == [
        f"{base}&start=2025-12-01T00:00:00Z&end=2026-09-26T23:59:59Z",
        f"{base}&start=2026-09-27T00:00:00Z&end=2026-10-12T23:59:59Z",
    ]


def test_tiingo_asks_by_lowercase_symbol_with_its_key_and_reads_past_a_missing_close():
    rows = [{"date": "2026-10-12T00:00:00.000Z", "close": None},
            {"date": "2026-10-13T00:00:00.000Z", "close": 101.5}]  # fmt: skip
    src = Tiingo(Client((200, rows)), "k1")
    got = src.history(Ref("i", "VTI", "etf"), d(2026, 10, 12), d(2026, 10, 13))
    assert got == [(d(2026, 10, 13), D("101.5"))]
    assert src.client.urls == [
        "https://api.tiingo.com/tiingo/daily/vti/prices?startDate=2026-10-12&endDate=2026-10-13"
    ]
    headers = {"Authorization": "Token k1", "Content-Type": "application/json"}
    assert src.client.kws == [{"headers": headers}]
    # A symbol is checked the same way; one the answer doesn't name keeps the one asked for.
    src = Tiingo(Client((200, {"name": "Vanguard Total"})), "k1")
    assert src.lookup("Vti") == {"symbol": "VTI", "name": "Vanguard Total"}
    assert src.client.urls == ["https://api.tiingo.com/tiingo/daily/vti"]
    assert src.client.kws == [{"headers": headers}]
    assert Tiingo(Client((200, {"ticker": "voo"})), "k").lookup("vti")["symbol"] == "VOO"


def test_cboe_reads_an_occ_ticker_of_one_letter():
    assert split_occ("X261120P00480000") == ("X", "261120P00480000")
    with pytest.raises(SourceError):
        split_occ("261120P00480000")


@pytest.mark.parametrize(
    ("row", "want"),
    [
        ({"bid": 0.5, "ask": 0.7}, D("0.60")),  # a quote under a dollar is still a quote
        ({"bid": 1.2, "ask": 1.2, "last_trade_price": 1.3}, D("1.20")),  # a locked market
        ({"bid": 0.5, "last_trade_price": 0.7}, D("0.70")),  # no ask: the last trade
        ({"bid": 1.2, "ask": 1.1, "last_trade_price": 1.3}, D("1.30")),  # a crossed quote
        ({"last_trade_price": 0.5}, D("0.50")),  # a last trade under a dollar
        ({"bid": 1.00, "ask": 1.01}, D("1.00")),  # half a cent, to the even cent
        ({"bid": 1.01, "ask": 1.02}, D("1.02")),
    ],
)
def test_a_contracts_mark_is_its_mid_or_its_last_trade(row, want):
    assert mark(row) == want


def test_cboe_dates_a_chain_by_its_last_trade_or_else_its_timestamp():
    both = {"timestamp": "2026-10-12 17:00:00", "data": {"last_trade_time": "2026-10-13T16:00"}}
    assert Cboe(Client((200, both)), None).chain("_SPX")[0] == d(2026, 10, 13)
    stamped = {"timestamp": "2026-10-12 17:00:00", "data": {"options": []}}
    assert Cboe(Client((200, stamped)), None).chain("_SPX") == (d(2026, 10, 12), {})
    with pytest.raises(SourceError, match="answered without a date for MSFT"):
        Cboe(Client((404, {})), None).chain("MSFT")


def test_cboe_waits_its_turn_before_each_call():
    turns = []
    src = Cboe(Client((200, {"timestamp": "2026-10-12"})), "k", wait=lambda: turns.append(1))
    src.chain("MSFT")
    src.chain("MSFT")  # one answer for every contract on the chain
    assert turns == [1] and src.key == "k"


def test_cboe_answers_400_and_up_as_failures():
    with pytest.raises(SourceError) as e:
        Cboe(Client((400, {})), None).listed("quotes", "VTI")
    assert str(e.value) == "CBOE delayed quotes answered HTTP 400"
    assert Cboe(Client((399, {"data": 1})), None).listed("quotes", "VTI") == 1


EASTERN_CLOSE = dt.datetime(2026, 10, 13, 20, 15, tzinfo=dt.UTC)  # 4:15 PM in New York


def test_cboe_keeps_closes_in_the_range_and_todays_from_the_quote_once_closed(at):
    at(EASTERN_CLOSE)
    rows = [
        {"date": "2026-10-08", "close": 1},  # before the range
        {"date": "2026-10-09", "close": 2},  # its first day
        {"date": "2026-10-12", "close": None},
        {"date": "2026-10-14", "close": 9},  # after it
    ]
    quote = {"last_trade_time": "2026-10-13T16:00:00", "close": 5}
    src = Cboe(Client((200, {"data": rows}), (200, {"data": quote})), None)
    got = src.history(Ref("i", "vti", "etf"), d(2026, 10, 9), d(2026, 10, 13))
    assert got == [(d(2026, 10, 9), D(2)), (d(2026, 10, 13), D(5))]
    assert src.client.urls[0].endswith("/charts/historical/VTI.json")
    # Its last day is in the range too.
    src = Cboe(Client((200, {"data": rows}), (200, {"data": {}})), None)
    got = src.history(Ref("i", "VTI", "etf"), d(2026, 10, 10), d(2026, 10, 14))
    assert got == [(d(2026, 10, 14), D(9))]


@pytest.mark.parametrize(
    ("now", "quote", "want"),
    [
        (EASTERN_CLOSE, {"last_trade_time": "2026-10-13T16:00:00", "close": 5}, [D(5)]),
        (
            EASTERN_CLOSE - dt.timedelta(seconds=1),
            {"last_trade_time": "2026-10-13", "close": 5},
            [],
        ),
        (EASTERN_CLOSE, {"last_trade_time": "2026-10-12T16:00:00", "close": 5}, []),  # yesterday's
        (EASTERN_CLOSE, {"close": 5}, []),
        (EASTERN_CLOSE, {"last_trade_time": "2026-10-13T16:00:00", "close": 0}, []),
    ],
)
def test_cboe_takes_todays_close_from_a_quote_of_today_after_the_close(at, now, quote, want):
    at(now)
    src = Cboe(Client((200, {"data": []}), (200, {"data": quote})), None)
    got = src.history(Ref("i", "VTI", "etf"), d(2026, 10, 13), d(2026, 10, 13))
    assert got == [(d(2026, 10, 13), p) for p in want]


def chain_of(day, rows):
    return {"data": {"last_trade_time": f"{day.isoformat()}T16:00:00", "options": rows}}


def test_cboe_marks_an_adjusted_contract_from_its_underlyings_chain():
    rows = [{"option": "FDX1261120C00050000", "bid": 1, "ask": 1.2}]
    src = Cboe(Client((200, chain_of(d(2026, 10, 13), rows))), None)
    ref = Ref("i", "O:FDX1261120C00050000", "option")
    assert src.history(ref, d(2026, 10, 13), d(2026, 10, 13)) == [(d(2026, 10, 13), D("1.10"))]
    assert src.client.urls == [
        "https://cdn-api.cboe.com/api/global/delayed_quotes/options/FDX.json"
    ]


def test_cboe_leaves_out_a_contract_with_no_price_or_a_chain_outside_the_range():
    rows = [{"option": "MSFT261120P00480000", "bid": 0, "ask": 0, "last_trade_price": 0}]
    src = Cboe(Client((200, chain_of(d(2026, 10, 13), rows))), None)
    ref = Ref("i", "O:MSFT261120P00480000", "option")
    assert src.history(ref, d(2026, 10, 13), d(2026, 10, 13)) == []
    assert src.history(ref, d(2026, 10, 14), d(2026, 10, 15)) == []
    assert src.history(ref, d(2026, 10, 10), d(2026, 10, 12)) == []


# The dev stub's walks, pinned: the same symbol and day give the same price in every release,
# so a dev database's history doesn't shift under it (S17.7). Every day of seven years, summed.
@pytest.mark.parametrize(
    ("symbol", "first", "total", "today"),
    [
        ("XAU", D("2599.9"), D("10150936.57"), D("5124.24")),  # gold near its real level
        ("VTI", D("158.25"), D("569328.37"), D("328.04")),
        ("BTC", D("476.86"), D("1784254.84"), D("979.33")),  # its seed apart mod 23 and 24
    ],
)
def test_the_stubs_walk_is_the_same_every_time(symbol, first, total, today):
    span = (d(2026, 12, 31) - d(2020, 1, 1)).days + 1
    days = [d(2020, 1, 1) + dt.timedelta(days=n) for n in range(span)]
    assert sum(walk(symbol, day) for day in days) == total
    assert walk(symbol, d(2020, 1, 1)) == first and walk(symbol, d(2026, 10, 13)) == today
    assert _seed("VTI") == 315277578


def test_the_stub_has_closes_for_market_days_before_today_and_every_day_for_coins(at):
    at(dt.datetime(2026, 10, 13, 15, tzinfo=dt.UTC))  # a Tuesday
    src = Stub(None, None)
    etf = src.history(Ref("i", "VTI", "etf"), d(2026, 10, 9), d(2026, 10, 13))
    assert [day for day, _ in etf] == [d(2026, 10, 9), d(2026, 10, 12)]
    coin = src.history(Ref("i", "BTC", "crypto"), d(2026, 10, 9), d(2026, 10, 13))
    assert [day for day, _ in coin] == [d(2026, 10, 9) + dt.timedelta(days=n) for n in range(5)]
    assert coin[0][1] == walk("BTC", d(2026, 10, 9))
    # An option's premium is a sixtieth of its walk, to the cent.
    occ = "O:VTI261120C00300000"
    opt = src.history(Ref("i", occ, "option"), d(2026, 10, 9), d(2026, 10, 9))
    assert opt == [(d(2026, 10, 9), (walk(occ, d(2026, 10, 9)) / 60).quantize(D("0.01")))]
