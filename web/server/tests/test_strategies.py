"""Strategies (requirements S3.5): shapes, figures at expiry and capital at risk, on the
mockup's worked numbers; then grouping, proposals, rolls and undo through the API."""

import datetime as dt
from decimal import Decimal as D

from edits import change, create, remove, saved

from moolakata.options.strategies import Leg, capital_at_risk, figures, shape

EXP = dt.date(2026, 11, 20)


def opt(kind, qty, strike, cost, expiry=EXP):
    return Leg("i" + kind + str(strike), "", kind, D(qty), D(cost), None, D(strike), expiry, 100)


def shares(qty, cost):
    return Leg("stk", "", "stock", D(qty), D(cost), None)


def test_a_covered_call_counts_its_shares_at_their_value_on_the_day_it_opened():
    legs = [shares(100, "23100"), opt("call", -1, 250, "-412")]
    assert shape(legs) == "Covered call"
    f = figures(legs)
    assert (f.maxProfit, f.maxLoss, f.breakevens) == (D("2312.00"), D("22688.00"), [D("226.88")])
    assert capital_at_risk(legs, None) == D("22688.00")


def test_an_iron_condor_risks_its_widest_wing_less_the_credit():
    legs = [
        opt("put", 1, 530, "120"),
        opt("put", -1, 540, "-200"),
        opt("call", -1, 600, "-190"),
        opt("call", 1, 610, "60"),
    ]
    assert shape(legs) == "Iron condor"
    f = figures(legs)
    assert (f.maxProfit, f.maxLoss) == (D("210.00"), D("790.00"))
    assert f.breakevens == [D("537.90"), D("602.10")]
    assert capital_at_risk(legs, None) == D("790.00")


def test_single_legs_and_spreads():
    put = [opt("put", -1, 480, "-365")]
    assert shape(put) == "Short put" and shape(put, cash_secured=True) == "Cash-secured put"
    f = figures(put)
    assert (f.maxProfit, f.maxLoss, f.breakevens) == (D("365.00"), D("47635.00"), [D("476.35")])
    long_put = [opt("put", 2, 560, "1180")]
    f = figures(long_put)
    assert shape(long_put) == "Long put"
    assert (f.maxProfit, f.maxLoss, f.breakevens) == (D("110820.00"), D("1180.00"), [D("554.10")])
    naked = [opt("call", -1, 250, "-412")]
    assert shape(naked) == "Short call"
    assert figures(naked).maxLoss is None, "unlimited"
    assert capital_at_risk(naked, None) is None
    assert capital_at_risk(naked, D("5000")) == D("5000")
    long_call = [opt("call", 1, 100, "300")]
    assert figures(long_call).maxProfit is None
    bps = [opt("put", -1, 440, "-250"), opt("put", 1, 430, "100")]
    assert shape(bps) == "Bull put spread"
    assert figures(bps).maxLoss == D("850.00")
    assert shape([opt("call", 1, 100, "500"), opt("call", -1, 110, "-200")]) == "Bull call spread"
    assert shape([opt("call", 1, 100, "500"), opt("put", 1, 100, "450")]) == "Long straddle"
    assert shape([opt("call", -1, 110, "-5"), opt("put", -1, 90, "-5")]) == "Short strangle"
    fly = [opt("call", 1, 90, "1200"), opt("call", -2, 100, "-1400"), opt("call", 1, 110, "300")]
    assert shape(fly) == "Butterfly"
    assert figures(fly).maxLoss == D("100.00")


def test_a_calendar_shows_its_pl_only_and_risks_its_debit():
    later = dt.date(2027, 1, 15)
    cal = [opt("call", -1, 100, "-300"), opt("call", 1, 100, "500", later)]
    assert shape(cal) == "Calendar"
    assert not figures(cal).expiryKnown
    assert capital_at_risk(cal, None) == D("200.00")
    assert shape([opt("call", -1, 100, "-300"), opt("call", 1, 110, "250", later)]) == "Diagonal"


def test_anything_else_is_custom():
    assert shape([opt("call", 1, 100, "1"), opt("call", -2, 110, "-1")]) == "Custom"


# ---- through the API ----

import pytest  # noqa: E402
from conftest import make_user, sign_in  # noqa: E402
from test_accounts import new_account  # noqa: E402
from test_options import opt as option  # noqa: E402

from moolakata import clock  # noqa: E402

T0 = dt.datetime(2026, 10, 13, 12, tzinfo=dt.UTC)


@pytest.fixture
def alice(server):
    clock.fix(T0)
    make_user(server, "alice")
    yield sign_in(server, "alice")
    clock.fix(None)


def test_legs_opened_together_are_proposed_grouped_rolled_and_undone(alice):
    a = new_account(alice, type="brokerage")["id"]
    for action, strike, premium in (
        ("sell-to-open", "540", "2.00"),
        ("buy-to-open", "530", "1.20"),
    ):
        r = option(alice, a, action, "2026-10-02", premium, strike=strike, fees="0")
        assert r.status_code == 200, r.text
    v = alice.get("/ui/api/positions/strategies").json()
    [p] = v["proposals"]
    assert (p["kind"], p["shape"], len(p["legs"])) == ("group", "Bull put spread", 2)
    # Turned down, it isn't proposed again.
    legs = [{"instrumentId": x["instrumentId"]} for x in p["legs"]]
    saved(create(alice, "Strat", accountId=a, legs=legs, dismissed=True))
    v = alice.get("/ui/api/positions/strategies").json()
    assert v["proposals"] == [] and v["strategies"] == []
    # Grouped by hand.
    st = saved(create(alice, "Strat", accountId=a, legs=legs))
    assert (st["shape"], st["credit"], st["maxProfit"], st["maxLoss"]) == (
        "Bull put spread",
        80,
        80,
        920,
    )
    assert st["capitalAtRiskAtOpen"] == 920 and st["breakevens"] == [539.2]
    again = create(alice, "Strat", accountId=a, legs=legs[:1])
    assert again.json()["errors"][0]["code"] == "leg-grouped"
    # A roll: the short leg closed and a new one opened the same day.
    option(alice, a, "buy-to-close", "2026-10-10", "1.00", strike="540", fees="0")
    option(alice, a, "sell-to-open", "2026-10-10", "1.50", strike="535", fees="0")
    v = alice.get("/ui/api/positions/strategies").json()
    [roll] = v["proposals"]
    assert (roll["kind"], roll["strategyId"]) == ("roll", st["id"])
    r = alice.post(
        f"/ui/api/strategies/{st['id']}/roll",
        json={"roll": [{"instrumentId": roll["legs"][0]["instrumentId"]}]},
    )
    assert r.status_code == 200, r.text
    st = r.json()
    assert len(st["legs"]) == 3 and st["realized"] == 100, "the closed leg's P/L stays with it"
    # Each leg's trade takes the strategy's capital at risk at open, as it was at open (the
    # 540/530 spread, not the rolled one: B12), its return exact.
    assert st["capitalAtRiskAtOpen"] == 920
    r = alice.get("/ui/api/positions/option-trades")
    assert r.status_code == 200, r.text
    [closed] = [x for x in r.json()["items"] if x["closed"]]
    assert (closed["capitalAtRisk"], closed["returnPct"]) == (920, 10.87)
    assert alice.get("/ui/api/positions/strategies").json()["proposals"] == []
    # Undone: the legs stand alone again.
    r = change(alice, "Strat", st, marginRequirement="1000.00", name="Rolled spread")
    assert (saved(r)["name"], saved(r)["marginRequirement"]) == ("Rolled spread", "1000.00")
    r = change(alice, "Strat", saved(r), marginRequirement="-1")
    assert r.json()["errors"][0]["code"] == "margin-invalid"
    r = remove(alice, "Strat", alice.get("/ui/api/positions/strategies").json()["strategies"][0])
    assert r.status_code == 200, r.text
    assert alice.get("/ui/api/positions/strategies").json()["strategies"] == []


def test_a_short_call_against_shares_is_proposed_as_a_covered_call(alice):
    a = new_account(alice, type="brokerage")["id"]
    r = alice.post(
        "/ui/api/transactions",
        json={
            "accountId": a,
            "date": "2026-01-05",
            "kind": "buy",
            "symbol": "MSFT",
            "quantity": "100",
            "price": "400",
            "amount": "-40000.00",
        },
    )
    assert r.status_code == 201, r.text
    option(alice, a, "sell-to-open", "2026-09-15", "4.12", right="call", strike="500", fees="0")
    [p] = alice.get("/ui/api/positions/strategies").json()["proposals"]
    assert (p["kind"], p["shape"]) == ("covered-call", "Covered call")
    legs = [
        {
            "instrumentId": x["instrumentId"],
            **({"quantity": x["quantity"]} if x["quantity"] else {}),
        }
        for x in p["legs"]
    ]
    st = saved(create(alice, "Strat", accountId=a, legs=legs))
    assert st["shape"] == "Covered call" and st["credit"] == 412


def test_a_strategy_closes_by_any_outcome_and_unlimited_risk_is_said_so(alice):
    # B12: a short straddle with no margin typed risks an unlimited amount, and the account
    # says so; assigned, its last leg closes it.
    a = new_account(alice, type="brokerage")["id"]
    for right, premium in (("call", "3.00"), ("put", "2.50")):
        r = option(alice, a, "sell-to-open", "2026-10-02", premium, right=right, fees="0")
        assert r.status_code == 200, r.text
    [p] = alice.get("/ui/api/positions/strategies").json()["proposals"]
    assert p["shape"] == "Short straddle"
    legs = [{"instrumentId": x["instrumentId"]} for x in p["legs"]]
    st = saved(create(alice, "Strat", accountId=a, legs=legs))
    assert st["capitalAtRiskNow"] is None and st["capitalAtRiskAtOpen"] is None
    acct = alice.get(f"/ui/api/accounts/{a}").json()
    assert acct["capitalAtRiskUnlimited"] and acct["capitalAtRisk"] is None
    _, put = sorted(p["legs"], key=lambda x: x["symbol"])
    r = option(alice, a, "buy-to-close", "2026-10-09", "1.00", right="call", fees="0")
    assert r.status_code == 200, r.text
    r = alice.post(
        f"/ui/api/accounts/{a}/options/{put['instrumentId']}/settle",
        json={"how": "assign", "date": "2026-10-12"},
    )
    assert r.status_code == 201, r.text
    [st] = alice.get("/ui/api/positions/strategies").json()["strategies"]
    assert st["closedOn"] == "2026-10-12"
    assert alice.get(f"/ui/api/accounts/{a}").json()["capitalAtRiskUnlimited"] is False
