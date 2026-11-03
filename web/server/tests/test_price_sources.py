"""The price sources' contract with the outside world (S4.2): every answer a source can get, a
price, nothing, a refusal, a limit, an error, a body that isn't JSON, no network at all, each
becoming a figure or a failure worded for Settings. No server, no network: a client answers
what each test says."""

import datetime as dt
import json
from decimal import Decimal as D

import pytest

from moolakata import clock
from moolakata.prices.base import Quote, Ref, SourceError, TickerSource
from moolakata.prices.cboe import Cboe, mark, split_occ
from moolakata.prices.massive import Massive
from moolakata.prices.tiingo import Tiingo

d = dt.date


class Answer:
    def __init__(self, status):
        self.status_code = status


class Client:
    """Answers each call with (status, body): a body is JSON unless it is bytes; an exception
    is raised instead."""

    def __init__(self, *answers):
        self.answers, self.urls = list(answers), []

    def get_bytes(self, url, **kw):
        self.urls.append(url)
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
