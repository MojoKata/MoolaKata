"""Strategies (requirements S3.5): shapes, figures at expiry and capital at risk, on the
mockup's worked numbers; then grouping, proposals, rolls and undo through the API."""

import datetime as dt
from decimal import Decimal as D
from types import SimpleNamespace as NS

from edits import change, create, make, option_trade, remove, saved

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
from sqlalchemy import select  # noqa: E402
from test_accounts import new_account  # noqa: E402
from test_options import _logged  # noqa: E402
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
    # An unnamed strategy is named in the roll as it is shown: by its shape (CR3-408).
    [shown] = [x for x in v["strategies"] if x["id"] == st["id"]]
    assert roll["shape"] == shown["name"] != ""
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
    assert (closed["capitalRequired"], closed["returnPct"]) == (920, 10.87)
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
    r = make(
        alice,
        "Txn",
        accountId=a,
        date="2026-01-05",
        kind="buy",
        symbol="MSFT",
        quantity="100",
        price="400",
        amount="-40000.00",
    )
    assert r.status_code == 200, r.text
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
        json={"how": "assign", "date": "2026-10-12", "contracts": "1"},
    )
    assert r.status_code == 201, r.text
    [st] = alice.get("/ui/api/positions/strategies").json()["strategies"]
    assert st["closedOn"] == "2026-10-12"
    assert alice.get(f"/ui/api/accounts/{a}").json()["capitalAtRiskUnlimited"] is False


def _risk(alice, a):
    acct = alice.get(f"/ui/api/accounts/{a}").json()
    return None if acct["capitalAtRiskUnlimited"] else acct["capitalAtRisk"]


def test_an_option_on_its_own_risks_what_its_shape_does(alice):
    """CR3-6: grouped or not, one leg counts the same capital at risk: a short put its strike
    less its premium, an uncovered short call no limit, one the account's shares cover a
    covered call's."""
    a = new_account(alice, type="brokerage")["id"]
    assert option(alice, a, "sell-to-open", "2026-10-02", "2.00", fees="0").status_code == 200
    alone = _risk(alice, a)
    assert alone == 48000 - 200
    [put] = [x for x in alice.get("/ui/api/positions").json()["open"] if x["accountId"] == a]
    st = saved(create(alice, "Strat", accountId=a, legs=[{"instrumentId": put["instrumentId"]}]))
    assert st["capitalAtRiskNow"] == alone, "grouped, the same leg risks the same"
    b = new_account(alice, type="brokerage", name="Calls", mask="5150")["id"]
    assert option(alice, b, "sell-to-open", "2026-10-02", "3.00", right="call", strike="520",
                  fees="0").status_code == 200  # fmt: skip
    assert _risk(alice, b) is None, "an uncovered call has no limit"
    r = create(alice, "Txn", accountId=b, date="2026-10-01", kind="buy", symbol="MSFT",
               quantity="100", price="500", amount="-50000.00")  # fmt: skip
    assert r.status_code == 200, r.text
    # Covered: the shares' value (their last trade, $500) less the call's premium.
    assert _risk(alice, b) == 50000 - 300


def _leg(kind, qty, strike=None, expiry=dt.date(2026, 12, 18), cost=0):
    if kind == "stock":
        return Leg("S", "S", "stock", D(qty), D(cost), None)
    return Leg(f"{kind}{strike}{expiry}", "O", kind, D(qty), D(cost), None,
               D(strike), expiry, 100)  # fmt: skip


JAN, FEB = dt.date(2027, 1, 15), dt.date(2027, 2, 19)


@pytest.mark.parametrize(
    ("legs", "name"),
    [
        ([], "Closed"),
        ([("stock", 100)], "Shares"),
        ([("stock", 100), ("call", -1, 110)], "Covered call"),
        ([("stock", 100), ("put", 1, 90)], "Protective put"),
        ([("stock", 100), ("call", -1, 110), ("put", 1, 90)], "Collar"),
        ([("stock", -100), ("call", -1, 110)], "Custom"),  # short shares
        ([("stock", 100), ("call", -1, 110), ("put", 2, 90)], "Custom"),  # sizes differ
        ([("stock", 100), ("call", 1, 110)], "Custom"),  # a long call on shares
        ([("put", 1, 90)], "Long put"),
        ([("put", -1, 90)], "Short put"),
        ([("call", -1, 110)], "Short call"),
        ([("call", 1, 100, JAN), ("call", -1, 100)], "Calendar"),
        ([("call", 1, 105, JAN), ("call", -1, 100)], "Diagonal"),
        ([("call", 1, 100, JAN), ("put", -1, 100)], "Custom"),  # two expiries, two kinds
        ([("call", 1, 100), ("call", -2, 110)], "Custom"),  # sizes differ
        ([("call", 1, 100), ("call", -1, 110)], "Bull call spread"),
        ([("call", -1, 100), ("call", 1, 110)], "Bear call spread"),
        ([("put", 1, 100), ("put", -1, 110)], "Bull put spread"),
        ([("put", -1, 100), ("put", 1, 110)], "Bear put spread"),
        ([("call", 1, 100), ("put", 1, 100)], "Long straddle"),
        ([("call", -1, 110), ("put", -1, 90)], "Short strangle"),
        ([("call", 1, 100), ("put", -1, 100)], "Custom"),  # a synthetic: not named
        ([("call", 1, 90), ("call", -2, 100), ("call", 1, 110)], "Butterfly"),
        ([("call", 1, 90), ("call", -2, 100), ("call", 1, 120)], "Custom"),  # wings uneven
        ([("call", 1, 90), ("call", -1, 100), ("call", 1, 110, JAN)], "Custom"),  # expiries
        ([("put", 1, 80), ("put", -1, 90), ("call", -1, 110), ("call", 1, 120)], "Iron condor"),
        ([("put", 1, 80), ("put", -1, 100), ("call", -1, 100), ("call", 1, 120)],
         "Iron butterfly"),
        ([("put", 1, 80), ("put", -1, 110), ("call", -1, 100), ("call", 1, 120)], "Custom"),
        ([("put", 1, 80), ("put", 1, 90), ("call", -1, 110), ("call", 1, 120)], "Custom"),
        ([("put", 1, 80), ("call", 1, 90), ("call", 1, 110), ("call", 1, 120)], "Custom"),
    ],
)  # fmt: skip
def test_every_shape_has_its_name(legs, name):
    """S3.5.4: each shape a strategy's legs make is named, and anything else is Custom."""
    assert shape([_leg(*x) for x in legs]) == name


def test_a_calendars_risk_is_its_debit_or_the_margin_typed():
    """S3.5.5: legs that expire apart have no one payoff; a calendar risks its net debit, and
    a credit one the margin typed, or nothing known (unlimited)."""
    debit = [_leg("call", 1, 100, JAN, cost=500), _leg("call", -1, 100, cost=-200)]
    assert figures(debit).expiryKnown is False
    assert capital_at_risk(debit, None) == D("300.00")
    credit = [_leg("call", 1, 100, JAN, cost=200), _leg("call", -1, 100, cost=-500)]
    assert capital_at_risk(credit, D(2500)) == 2500
    assert capital_at_risk(credit, None) is None
    # One expiry: the payoff's worst, whatever the margin.
    spread = [_leg("call", 1, 100, cost=500), _leg("call", -1, 110, cost=-200)]
    assert capital_at_risk(spread, D(9999)) == D("300.00")


# ---- figures at expiry: breakevens, wherever they fall ----


def test_a_breakeven_past_twice_the_highest_strike_is_found():
    """S3.5.4: past the highest strike the payoff is a line, and its breakeven is where the
    line crosses zero, however far out: a deep-in-the-money call (strike $10, premium $15)
    breaks even at $25, shares bought at $400 with a $150 put at $402, a call sold for more
    than its strike at the strike plus the premium, and shares alone at their cost."""
    deep = [_leg("call", 1, 10, cost=1500)]
    assert figures(deep).breakevens == [D("25.00")]
    protected = [_leg("stock", 100, cost=40000), _leg("put", 1, 150, cost=200)]
    assert figures(protected).breakevens == [D("402.00")]
    assert figures([_leg("call", -1, 100, cost=-15000)]).breakevens == [D("250.00")]
    assert figures([_leg("stock", 100, cost=23100)]).breakevens == [D("231.00")]


@pytest.mark.parametrize(
    ("legs", "evens"),
    [
        # Zero at the strike from below, flat after: the strike, once.
        ([("call", 1, 100, 500), ("call", -1, 105, 0)], ["105.00"]),
        # Zero at the strike from above (a put that cost nothing): the strike, once, even $1.
        ([("put", 1, 100, 0)], ["100.00"]),
        ([("put", 1, 1, 0)], ["1.00"]),
        # Zero at $0, below it after, or flat at zero (shares that cost nothing): none.
        ([("put", 1, 10, 1000)], []),
        ([("stock", 100, None, 0)], []),
        # Zero from $0 to $1, rising after: $1 is the breakeven, and $0 never is.
        ([("stock", 100, None, 100), ("put", 1, 1, 0), ("call", -1, 2, 0)], ["1.00"]),
        # Zero at $0 and above it after: $0 is no breakeven.
        ([("put", -1, 10, -1000)], []),
        # Above zero all along, under a dollar at $0: no breakeven.
        ([("put", -1, 1, "-100.50")], []),
        # Above zero, falling to 50 cents at a strike, and crossing only past the highest.
        ([("put", 1, 2, 0), ("call", -1, 10, "-0.50")], ["10.00"]),
    ],
)  # fmt: skip
def test_a_breakeven_is_where_the_payoff_reaches_zero_once_each_never_at_zero(legs, evens):
    legs = [_leg(kind, qty, strike, cost=D(str(cost))) for kind, qty, strike, cost in legs]
    assert figures(legs).breakevens == [D(x) for x in evens]


def test_nothing_open_has_no_profit_loss_or_breakevens():
    from moolakata.options.strategies import Figures

    assert figures([]) == Figures(D(0), D(0), [], True)
    assert figures([_leg("call", 0, 100, cost=300)]) == Figures(D(0), D(0), [], True)
    assert figures([_leg("call", 1, 100, JAN), _leg("call", -1, 100)]).breakevens == []


def test_part_of_a_share_still_rises_without_limit():
    """Fractional shares (a reinvested dividend): any rise past the strikes has no top."""
    f = figures([_leg("stock", "0.5", cost=50)])
    assert (f.maxProfit, f.maxLoss, f.breakevens) == (None, D("50.00"), [D("100.00")])


# ---- shapes: data that tells each rule apart ----


@pytest.mark.parametrize(
    ("legs", "name"),
    [
        # Two lots a wing: the body sells twice the wing, whatever the lot.
        ([("call", 2, 90), ("call", -4, 100), ("call", 2, 110)], "Butterfly"),
        ([("call", 2, 90), ("call", -1, 100), ("call", 2, 110)], "Custom"),
        # Three legs of two kinds, even if they would make a butterfly's payoff.
        ([("put", 1, 90), ("call", -2, 100), ("call", 1, 110)], "Custom"),
        # An iron condor's legs in two sizes.
        ([("put", 1, 80), ("put", -2, 90), ("call", -2, 110), ("call", 1, 120)], "Custom"),
        # Shares with two short calls and a put: no collar.
        ([("stock", 100), ("call", -1, 110), ("call", -1, 120), ("put", 1, 90)], "Custom"),
        # One share is long, as 100 are.
        ([("stock", 1), ("call", -1, 110), ("put", 1, 90)], "Collar"),
        ([("stock", 1), ("call", -1, 110)], "Covered call"),
        ([("stock", 1), ("put", 1, 90)], "Protective put"),
    ],
)  # fmt: skip
def test_each_shape_rule_tells_its_near_misses_apart(legs, name):
    assert shape([_leg(*x) for x in legs]) == name


# ---- capital at risk at its bounds ----


def test_a_calendar_at_no_net_cost_risks_the_margin_and_a_small_debit_itself():
    even = [_leg("call", 1, 100, JAN, cost=300), _leg("call", -1, 100, cost=-300)]
    assert capital_at_risk(even, D(2500)) == 2500
    small = [_leg("call", 1, 100, JAN, cost="300.50"), _leg("call", -1, 100, cost=-300)]
    assert capital_at_risk(small, None) == D("0.50")


def test_a_contract_delivers_its_underlyings_shares_and_cash():
    """S3.10.2: shares of the underlying and cash a contract delivers, and each other
    company's shares; the shares the underlying became are its own."""
    from moolakata.options.strategies import delivers

    plain = NS(deliverable=None, deliverableCash=None, underlyingId="U")
    assert delivers(plain) == (None, D(0), ())
    rows = '[{"instrumentId": "U", "shares": 150}, {"instrumentId": "U", "shares": 5}]'
    assert delivers(NS(deliverable=rows, deliverableCash=D(50), underlyingId="U")) == (
        D(155), D(50), ())  # fmt: skip
    spun = '[{"instrumentId": "U", "shares": 100}, {"instrumentId": "V", "shares": 20}]'
    oc = NS(deliverable=spun, deliverableCash=None, underlyingId="U")
    assert delivers(oc) == (D(100), D(0), (("V", D(20)),))
    assert delivers(oc, {"U", "V"}) == (D(120), D(0), ()), "U merged into V"


# ---- a strategy read from a book of positions, as plain values ----

from moolakata.options import strategies as strat  # noqa: E402
from moolakata.options.strategies import (  # noqa: E402
    LegRow,
    Proposal,
    at_prices,
    leg,
    proposal_key,
    proposals,
    risk_of_account,
    view,
)

D0, D1, D2, D3 = (
    dt.date(2026, 9, 1),
    dt.date(2026, 10, 2),
    dt.date(2026, 10, 9),
    dt.date(2026, 10, 12),
)
ACCOUNT = NS(id="A", ownerId="O")
LEDGER = NS(account=ACCOUNT)


class Session:
    """What the strategies read through a session here: an instrument's symbol."""

    def get(self, _entity, iid):
        return NS(symbol=f"<{iid}>")


class Book:
    """An account's positions as `strategies.Book` gives them: (quantity, basis) open, each
    instrument's first and last days, the closes, today's marks, prices by (instrument, day),
    None for today, and what each instrument moved to."""

    def __init__(self, open=None, first=None, disposals=(), last=None, marks=None, prices=None,
                 held=None, moved=None):  # fmt: skip
        self.s = Session()
        self.open = {k: (D(q), D(b)) for k, (q, b) in (open or {}).items()}
        self.first = first or {}
        self.disposals = list(disposals)
        self.last = last or {}
        self.marks = {k: NS(value=D(v)) for k, v in (marks or {}).items()}
        self.prices = prices or {}
        self.held = held
        self.moved = moved or {}

    def price(self, iid, day=None):
        return self.prices.get((iid, day))

    worth = strat.Book.worth
    became = strat.Book.became
    delivers = strat.Book.delivers

    def held_on(self, day):
        return self.open if self.held is None else self.held


def contract(right, strike, under="U", deliverable=None, cash=None):
    return NS(right=right, strike=D(strike), expiry=EXP, multiplier=100, underlyingId=under,
              deliverable=deliverable, deliverableCash=cash)  # fmt: skip


def strategy(sid, opened=D1, name=None, cash_secured=False, margin=None, under="U"):
    return NS(id=sid, accountId="A", underlyingId=under, openedOn=opened, name=name,
              cashSecured=cash_secured, marginRequirement=margin)  # fmt: skip


@pytest.fixture
def world(monkeypatch):
    """Contracts, the account's strategies (and those turned down) and their legs, read where
    the module reads them."""
    w = NS(contracts={}, strategies=[], dismissed=[], legs={})
    monkeypatch.setattr(strat, "contract_of", lambda s, iid: w.contracts.get(iid))
    monkeypatch.setattr(
        strat, "of_account",
        lambda s, aid, dismissed=False: (w.dismissed if dismissed else w.strategies)
        if aid == "A" else [],
    )  # fmt: skip
    monkeypatch.setattr(strat, "legs_of", lambda s, st: w.legs[st.id])
    clock.fix(T0)
    yield w
    clock.fix(None)


def test_an_option_leg_is_its_contract_its_position_and_its_closes_since_opening(world):
    """S3.5.2: a leg's realized P/L is its closes from the day the strategy opened, that day
    too; an adjusted contract carries its deliverable (S3.10.2)."""
    rows = '[{"instrumentId": "U", "shares": 150}]'
    world.contracts["C"] = contract("call", 500, deliverable=rows, cash=D(50))
    closes = [
        NS(instrumentId="C", soldOn=D1, gain=D(100)),  # the day it opened: the strategy's
        NS(instrumentId="C", soldOn=D0, gain=D(999)),  # before it: not
        NS(instrumentId="C", soldOn=D2, gain=None),  # no basis: nothing
        NS(instrumentId="X", soldOn=D2, gain=D(7)),  # another instrument's
    ]
    book = Book(open={"C": (-2, -824)}, marks={"C": -600}, disposals=closes)
    assert leg(book, LegRow("C", D2, None), D1) == Leg(
        "C", "<C>", "call", D(-2), D(-824), D(-600), D(500), EXP, 100, D(100), D2, None,
        D(150), D(50))  # fmt: skip
    assert leg(Book(open={"C": (-2, -824)}), LegRow("C", D2, None), D1).value is None


def test_a_closed_leg_closes_on_its_last_day_or_else_the_strategys_first(world):
    world.contracts["C"] = contract("call", 500)
    assert leg(Book(last={"C": D2}), LegRow("C", D1, None), D1).closedOn == D2
    # Its trades deleted, nothing dates it: the day the strategy opened.
    assert leg(Book(), LegRow("C", D1, None), D1).closedOn == D1


def test_a_stock_leg_is_its_part_of_the_shares_at_the_opening_days_price(world):
    """S3.5.4: shares count at their value on the day the strategy opened; their value now
    is today's."""
    book = Book(open={"U": (150, 61000)}, prices={("U", D1): D(400), ("U", None): D(450)})
    assert leg(book, LegRow("U", D1, D(100)), D1) == Leg(
        "U", "<U>", "stock", D(100), D("40000.00"), D("45000.00"), addedOn=D1)  # fmt: skip
    assert leg(book, LegRow("U", D1, None), D1).quantity == 150, "no quantity: all held"
    assert leg(book, LegRow("U", D1, D(200)), D1).quantity == 150, "no more than held"


def test_shares_with_no_price_count_at_their_basis_and_have_no_value(world):
    x = leg(Book(open={"U": (150, 61000)}), LegRow("U", D1, D(100)), D1)
    assert (x.cost, x.value) == (D("40666.67"), None)
    assert leg(Book(), LegRow("U", D1, D(100)), D1).cost == 0, "none held, none priced"


def test_capital_at_risk_values_open_shares_at_the_days_price_and_nothing_else():
    book = Book(prices={("U", D1): D(400), ("C", D1): D(5)})
    shares = Leg("U", "", "stock", D(100), D(1), None)
    call = Leg("C", "", "call", D(-1), D(-412), None, D(500), EXP, 100)
    gone = Leg("U", "", "stock", D(0), D(1), None)
    unpriced = Leg("V", "", "stock", D(100), D(7), None)
    out = at_prices(book, [shares, call, gone, unpriced], D1)
    assert [x.cost for x in out] == [D("40000.00"), D(-412), D(1), D(7)]


def _covered_call(world, **kw):
    world.contracts["C"] = contract("call", 500)
    world.legs["St"] = [LegRow("U", D1, D(100)), LegRow("C", D1, None)]
    return strategy("St", **kw)


def test_an_open_strategy_is_its_legs_now_and_at_open(world):
    """S3.5.4, S3.5.5: a covered call bought at $400 a share and marked at $450 today."""
    st = _covered_call(world)
    book = Book(open={"U": (100, 40000), "C": (-1, -412)}, marks={"C": -300},
                prices={("U", D1): D(400), ("U", None): D(450)})  # fmt: skip
    v = view(book, st)
    assert (v.name, v.shape, v.underlying, v.closedOn) == ("Covered call", "Covered call", "<U>",
                                                           None)  # fmt: skip
    assert (v.credit, v.unrealized, v.realized, v.pl) == (412, 5000 + 112, 0, 5112)
    assert (v.riskNow, v.riskAtOpen) == (D("44588.00"), D("39588.00"))


def test_a_strategy_closes_when_its_last_option_leg_does(world):
    """S3.5.2: the call bought back, the shares still held: closed that day, with no capital at
    risk now, and at open as it opened."""
    st = _covered_call(world, name="Wheel")
    book = Book(open={"U": (100, 40000)}, last={"C": D2, "U": D1},
                disposals=[NS(instrumentId="C", soldOn=D2, gain=D(312))],
                prices={("U", D1): D(400), ("U", None): D(450)},
                held={"U": (D(100), D(40000)), "C": (D(-1), D(-412))})  # fmt: skip
    v = view(book, st)
    assert (v.name, v.shape, v.closedOn, v.riskNow, v.riskAtOpen) == (
        "Wheel", "Shares", D2, None, D("39588.00"))  # fmt: skip
    assert (v.credit, v.unrealized, v.realized) == (0, 5000, 312)


def test_a_strategy_with_a_leg_unmarked_has_no_unrealized_pl(world):
    st = _covered_call(world)
    book = Book(open={"U": (100, 40000), "C": (-1, -412)}, prices={("U", None): D(450)})
    assert (view(book, st).unrealized, view(book, st).pl) == (None, None)


def test_a_strategy_takes_the_owners_tick_and_margin(world):
    """S3.5.3, S3.5.5: a short put ticked cash-secured is named so; a naked call risks the
    margin typed, now and at open."""
    world.contracts["P"] = contract("put", 480)
    world.legs["Put"] = [LegRow("P", D1, None)]
    book = Book(open={"P": (-1, -200), "C": (-1, -412)})
    v = view(book, strategy("Put", cash_secured=True))
    assert (v.name, v.riskNow) == ("Cash-secured put", D("47800.00"))
    world.contracts["C"] = contract("call", 500)
    world.legs["Call"] = [LegRow("C", D1, None)]
    v = view(book, strategy("Call", margin=D(5000)))
    assert (v.riskNow, v.riskAtOpen) == (5000, 5000)


def test_an_accounts_options_are_valued_and_each_outside_a_strategy_risks_its_own(world):
    """S3.5.6: a short put risks its strike less its premium, a long call its premium."""
    world.contracts |= {"P": contract("put", 480), "L": contract("call", 600)}
    book = Book(open={"P": (-1, -200), "L": (1, 150), "U": (100, 40000)},
                marks={"P": -150, "L": 100})  # fmt: skip
    assert risk_of_account(book.s, LEDGER, book) == (D(-50), D("47950.00"), True)


def test_an_account_with_shares_alone_has_nothing_open(world):
    value, risk, any_open = risk_of_account(Session(), LEDGER, Book(open={"U": (100, 40000)}))
    assert (value, risk) == (0, 0) and any_open is False


def test_an_accounts_strategies_risk_theirs_and_their_legs_count_once(world):
    """S3.5.6: each open strategy's capital at risk, a closed one's none, an option outside
    them its own; every option open is in the value."""
    world.contracts |= {"A1": contract("put", 540), "A2": contract("put", 530),
                        "B1": contract("put", 480), "K1": contract("call", 700),
                        "Z1": contract("call", 600)}  # fmt: skip
    world.legs |= {"Spread": [LegRow("A1", D1, None), LegRow("A2", D1, None)],
                   "Put": [LegRow("B1", D1, None)], "Gone": [LegRow("K1", D1, None)]}  # fmt: skip
    world.strategies = [strategy("Spread"), strategy("Put"), strategy("Gone")]
    book = Book(open={"A1": (-1, -200), "A2": (1, 120), "B1": (-1, -200), "Z1": (1, 150)},
                marks={"A1": -150, "A2": 60, "B1": -100, "Z1": 90}, last={"K1": D2})  # fmt: skip
    assert risk_of_account(book.s, LEDGER, book) == (D(-100), D(920 + 47800 + 150), True)


def test_an_unlimited_risk_anywhere_makes_the_accounts_unlimited(world):
    world.contracts |= {"C": contract("call", 500), "Z": contract("call", 600)}
    world.legs["Naked"] = [LegRow("C", D1, None)]
    world.strategies = [strategy("Naked")]
    book = Book(open={"C": (-1, -412), "Z": (1, 150)}, marks={"C": -300, "Z": 90})
    assert risk_of_account(book.s, LEDGER, book) == (D(-210), None, True)


def test_a_call_delivering_another_companys_shares_is_never_covered(world):
    """S3.10.2: the underlying's shares don't cover what else it delivers; each such call is
    still valued."""
    spun = '[{"instrumentId": "U", "shares": 100}, {"instrumentId": "V", "shares": 20}]'
    world.contracts |= {"C1": contract("call", 500, deliverable=spun),
                        "C2": contract("call", 510, deliverable=spun)}  # fmt: skip
    book = Book(open={"C1": (-1, -400), "C2": (-1, -300), "U": (200, 80000)},
                marks={"C1": -350, "C2": -250}, prices={("U", None): D(400)})  # fmt: skip
    assert risk_of_account(book.s, LEDGER, book) == (D(-600), None, True)


def test_shares_cover_calls_in_turn_and_only_shares_no_strategy_holds(world):
    """S3.5.6: 100 shares cover one short call, valued at today's price (without one, what they
    cost) less its premium; a second call is uncovered; shares a strategy holds cover none."""
    world.contracts |= {"C1": contract("call", 500), "C2": contract("call", 510)}
    one = Book(open={"C1": (-1, -412), "U": (100, 40000)}, prices={("U", None): D(450)})
    assert risk_of_account(one.s, LEDGER, one)[1] == D("44588.00")
    two = Book(open={"C1": (-1, -412), "C2": (-1, -300), "U": (100, 40000)},
               prices={("U", None): D(450)})  # fmt: skip
    assert risk_of_account(two.s, LEDGER, two)[1] is None
    world.legs["St"] = [LegRow("U", D1, D(100)), LegRow("C1", D1, None)]
    world.strategies = [strategy("St")]
    assert risk_of_account(two.s, LEDGER, two)[1] is None, "the strategy's shares are its own"
    unpriced = Book(open={"C1": (-1, -412), "U": (100, 40000)})
    world.strategies = []
    # Unpriced, the shares count at what they cost, as a strategy's do (CR3-429): never at 0.
    assert risk_of_account(unpriced.s, LEDGER, unpriced)[1] == D("39588.00")
    half = Book(open={"C1": (-1, -412), "U": (200, 80000)})
    assert risk_of_account(half.s, LEDGER, half)[1] == D("39588.00"), "the shares used, pro rata"


def test_one_share_covers_a_contract_that_delivers_one(world):
    """CR3-400: coverage counts what a contract delivers: an adjusted one delivering a share."""
    world.contracts["C"] = contract("call", 5, deliverable='[{"instrumentId": "U", "shares": 1}]')
    book = Book(open={"C": (-1, -4), "U": (1, 400)}, prices={("U", None): D(400)})
    assert risk_of_account(book.s, LEDGER, book)[1] == D("396.00")


def test_a_short_puts_risk_counts_the_cash_it_delivers(world):
    """S3.10.2: a put delivering 100 shares and $50 is at the money at $479.50."""
    rows = '[{"instrumentId": "U", "shares": 100}]'
    world.contracts["P"] = contract("put", 480, deliverable=rows, cash=D(50))
    book = Book(open={"P": (-1, -200)})
    assert risk_of_account(book.s, LEDGER, book)[1] == D("47750.00")


def _taken_over(other):
    """A short put whose underlying was taken over: it delivers 20 shares of another company
    and $50, none of its own underlying; `other` is what those 20 are worth."""
    return Leg("P", "", "put", D(-1), D(-300), None, D(480), EXP, 100, shares=D(0), cash=D(50),
               others=(("V", D(20)),), other=other)  # fmt: skip


@pytest.mark.parametrize(
    ("other", "profit", "loss"),
    [
        # Worth more than exercise pays ($47,950): it expires, and keeps its premium.
        (D(50000), D("300.00"), D("0.00")),
        # At $30 a share they are worth $600: exercise costs $47,350 less the $300 premium.
        (D(600), D("-47050.00"), D("47050.00")),
    ],
)
def test_another_companys_shares_a_contract_delivers_count_at_their_price(other, profit, loss):
    """S3.5.4, S3.10.2: its payoff has no kink in the underlying's price, nothing divides by
    its shares, and the other company's shares count at their price, never at nothing: the
    put's max profit is its premium when they cover what exercise pays."""
    f = figures([_taken_over(other)])
    assert (f.maxProfit, f.maxLoss, f.breakevens, f.priced) == (profit, loss, [], True)
    assert capital_at_risk([_taken_over(other)], None) == loss


def test_a_contract_delivering_unpriced_shares_is_not_priced():
    """S3.5.4: without that company's price the figures and capital at risk aren't known; a
    margin typed is the capital at risk."""
    f = figures([_taken_over(None)])
    assert (f.maxProfit, f.maxLoss, f.breakevens, f.expiryKnown, f.priced) == (
        None, None, [], True, False)  # fmt: skip
    assert capital_at_risk([_taken_over(None)], None) is None
    assert capital_at_risk([_taken_over(None)], D(5000)) == 5000
    closed = Leg(**{**_taken_over(None).__dict__, "quantity": D(0)})
    assert figures([closed, opt("put", -1, 480, "-300")]).priced, "a closed leg's isn't asked"


def test_a_strategy_prices_another_companys_shares_today_and_on_its_opening_day(world):
    """S3.5.4, S3.5.5: the takeover's put in a strategy, V at $2,500 today and $30 the day it
    opened: its figures and risk now at today's price, its risk at open at that day's; with no
    price, not priced."""
    rows = '[{"instrumentId": "V", "shares": 20}]'
    world.contracts["P"] = contract("put", 480, deliverable=rows, cash=D(50))
    world.legs["Put"] = [LegRow("P", D1, None)]
    book = Book(open={"P": (-1, -300)}, prices={("V", None): D(2500), ("V", D1): D(30)})
    v = view(book, strategy("Put"))
    assert v.legs[0].others == (("V", D(20)),) and v.legs[0].other == D(50000)
    assert (v.figures.maxProfit, v.figures.maxLoss, v.figures.priced) == (D(300), D(0), True)
    assert (v.riskNow, v.riskAtOpen) == (D(0), D("47050.00"))
    v = view(Book(open={"P": (-1, -300)}), strategy("Put"))
    assert (v.figures.priced, v.riskNow, v.riskAtOpen) == (False, None, None)
    v = view(Book(open={"P": (-1, -300)}), strategy("Put", margin=D(9000)))
    assert (v.riskNow, v.riskAtOpen) == (9000, 9000)


def test_an_option_outside_a_strategy_risks_what_exercise_pays_whatever_else_it_delivers(world):
    """S3.5.6: by the table, a short put outside a strategy risks its strike less the cash it
    delivers and its premium, a long call its premium, whatever another company's shares in it
    are worth."""
    rows = '[{"instrumentId": "V", "shares": 20}]'
    world.contracts |= {"P": contract("put", 480, deliverable=rows, cash=D(50)),
                        "L": contract("call", 500, deliverable=rows)}  # fmt: skip
    for prices in ({}, {("V", None): D(2500)}):
        book = Book(open={"P": (-1, -300), "L": (1, 150)}, prices=prices)
        assert risk_of_account(book.s, LEDGER, book)[1] == D(47650 + 150)


def test_legs_opened_together_are_proposed_as_one_group_each(world):
    """S3.5.1: two legs on one underlying the same day are proposed, one alone isn't, and a
    group turned down isn't again."""
    world.contracts |= {"H1": contract("call", 90, under="V"), "W1": contract("put", 50, under="W"),
                        "W2": contract("put", 45, under="W"), "G1": contract("put", 540),
                        "G2": contract("put", 530)}  # fmt: skip
    world.dismissed = [strategy("No", under="W")]
    world.legs["No"] = [LegRow("W1", D2, None), LegRow("W2", D2, None)]
    book = Book(open={"H1": (1, 50), "W1": (-1, -30), "W2": (1, 20), "G1": (-1, -200),
                      "G2": (1, 120)},
                first={"H1": D1, "W1": D2, "W2": D2, "G1": D1, "G2": D1},
                disposals=[NS(instrumentId="G1", soldOn=D1, gain=D(10))])  # fmt: skip
    assert proposals(book.s, ACCOUNT, book) == [
        Proposal(proposal_key("A", ["G1", "G2"]), "group", "A", "U", D1,
                 [("G1", None), ("G2", None)], "Bull put spread", None, ["<G1>", "<G2>"])
    ]  # fmt: skip


def test_a_leg_opened_the_day_another_closed_is_proposed_as_its_roll(world):
    """S3.5.3: a strategy's leg closed, and another on its underlying opened that day, is
    offered to the first strategy it could roll, once; a leg opened another day, or on another
    underlying, isn't."""
    world.contracts |= {x: contract("put", k) for x, k in (("X1", 540), ("X0", 530),
                        ("X2", 520), ("Y2", 510), ("N4", 500), ("N1", 490))}  # fmt: skip
    world.contracts["N3"] = contract("put", 90, under="V")
    world.legs |= {"First": [LegRow("X1", D0, None), LegRow("X0", D0, None),
                             LegRow("X2", D0, None)],
                   "Second": [LegRow("Y2", D0, None)]}  # fmt: skip
    # The first is named as it is shown: by its shape, the owner's tick in it (CR3-408).
    world.strategies = [strategy("First", D0, cash_secured=True),
                        strategy("Second", D0, name="Wheel")]  # fmt: skip
    book = Book(open={"X1": (-1, -200), "N4": (-1, -150), "N1": (-1, -100), "N3": (-1, -50)},
                first={"N4": D2, "N1": D3, "N3": D3},
                disposals=[NS(instrumentId="X1", soldOn=D2, gain=D(5)),
                           NS(instrumentId="X2", soldOn=D3, gain=D(6)),
                           NS(instrumentId="Y2", soldOn=D3, gain=D(7))])  # fmt: skip
    assert proposals(book.s, ACCOUNT, book) == [
        Proposal(proposal_key("A", ["N1"]), "roll", "A", "U", D3, [("N1", None)],
                 "Cash-secured put", "First", ["<N1>"])
    ]  # fmt: skip
    world.dismissed = [strategy("No")]
    world.legs["No"] = [LegRow("N1", D3, None)]
    assert proposals(book.s, ACCOUNT, book) == [], "a roll turned down isn't offered again"


def test_a_roll_turned_down_leaves_the_next_offered_and_groups_after_it(world):
    world.contracts |= {"X2": contract("put", 520), "N1": contract("put", 490),
                        "N5": contract("put", 480), "V1": contract("put", 90, under="V"),
                        "V2": contract("put", 80, under="V")}  # fmt: skip
    world.legs |= {"First": [LegRow("X2", D0, None)], "No": [LegRow("N1", D3, None)]}
    world.strategies, world.dismissed = [strategy("First", D0)], [strategy("No")]
    book = Book(open={"N1": (-1, -100), "N5": (-1, -90), "V1": (-1, -50), "V2": (1, 30)},
                first={"N1": D3, "N5": D3, "V1": D1, "V2": D1},
                disposals=[NS(instrumentId="X2", soldOn=D3, gain=D(6))])  # fmt: skip
    assert [(p.kind, p.legs) for p in proposals(book.s, ACCOUNT, book)] == [
        ("roll", [("N5", None)]), ("group", [("V1", None), ("V2", None)])]  # fmt: skip


def test_a_short_call_is_proposed_covered_by_the_shares_it_delivers(world):
    """S3.5.1: a short call against the 100 or more shares it delivers; not a put, not a call
    the shares don't cover, not one turned down."""
    world.contracts |= {"Q1": contract("put", 400), "C4": contract("call", 50, under="W"),
                        "C5": contract("call", 520), "C3": contract("call", 90, under="V"),
                        "L1": contract("call", 600), "C1": contract("call", 500)}  # fmt: skip
    world.dismissed = [strategy("No")]
    world.legs["No"] = [LegRow("C5", D2, None), LegRow("U", D2, D(100))]
    book = Book(open={"Q1": (-1, -200), "C4": (-1, -30), "C5": (-1, -20), "C3": (-2, -60),
                      "L1": (1, 150), "C1": (-1, -412), "U": (200, 80000), "V": (100, 9000)},
                first={"Q1": D0, "C4": D1, "C5": D2, "C3": D3, "L1": D3, "C1": D1})  # fmt: skip
    assert proposals(book.s, ACCOUNT, book) == [
        Proposal(proposal_key("A", ["C1", "U"]), "covered-call", "A", "U", D1,
                 [("U", D(100)), ("C1", None)], "Covered call", None, ["<U>", "<C1>"])
    ]  # fmt: skip


def test_calls_proposed_as_a_group_are_not_proposed_covered_too(world):
    world.contracts |= {"T1": contract("call", 500), "T2": contract("call", 510)}
    book = Book(open={"T1": (-1, -400), "T2": (-1, -300), "U": (200, 80000)},
                first={"T1": D2, "T2": D2})  # fmt: skip
    assert [p.kind for p in proposals(book.s, ACCOUNT, book)] == ["group"]


def test_a_book_sums_each_instruments_lots_and_dates_its_first_and_last_days(monkeypatch):
    monkeypatch.setattr(strat.valuation, "positions", lambda s, ledger: [NS(instrumentId="U")])
    lots = [NS(instrumentId="U", quantity=D(100), basis=D(40000), acquiredOn=D2),
            NS(instrumentId="U", quantity=D(50), basis=None, acquiredOn=D0),
            NS(instrumentId="U", quantity=D(10), basis=D(5000), acquiredOn=D1),
            NS(instrumentId="C", quantity=D(-1), basis=D(-412), acquiredOn=D1)]  # fmt: skip
    txns = [NS(instrumentId="U", date=D0), NS(instrumentId=None, date=D1),
            NS(instrumentId="C", date=D1), NS(instrumentId="U", date=D3)]  # fmt: skip
    ledger = NS(replay=lambda: NS(open=lots, disposals=["a close"]), transactions=txns)
    b = strat.Book("s", ledger)
    assert b.open == {"U": (D(160), D(45000)), "C": (D(-1), D(-412))}
    assert (b.first, b.last) == ({"U": D0, "C": D1}, {"U": D3, "C": D1})
    assert (b.disposals, list(b.marks)) == (["a close"], ["U"])


def test_a_books_prices_are_asked_once_each_for_the_day_and_owner(monkeypatch):
    asked = []

    def prices(s, ids, day, owner):
        asked.append((ids, day, owner))
        return {"U": NS(price=D(400) if day == D1 else D(450))} if ids == ["U"] else {}

    monkeypatch.setattr(strat.valuation, "prices", prices)
    monkeypatch.setattr(strat.valuation, "positions", lambda s, ledger: [])
    ledger = NS(replay=lambda: NS(open=[], disposals=[]), transactions=[], account=ACCOUNT)
    b = strat.Book("s", ledger)
    got = (b.price("U", D1), b.price("U"), b.price("V", D1), b.price("U", D1), b.price("V", D1))
    assert got == (D(400), D(450), None, D(400), None)
    assert asked == [(["U"], D1, "O"), (["U"], None, "O"), (["V"], D1, "O")]


def test_a_leg_follows_its_contract_through_each_adjustment_and_back(monkeypatch):
    """S3.10, CR3-401: the contract it became, its quantity times each ratio; adjusted back to
    a contract already passed, it stops there."""
    rows = [NS(instrumentId="A", addedOn=D1, quantity=D(2)),
            NS(instrumentId="U", addedOn=D1, quantity=None),
            NS(instrumentId="C", addedOn=D2, quantity=D(2)),
            NS(instrumentId="E", addedOn=D2, quantity=None)]  # fmt: skip
    moved = {"A": ("A2", D(2)), "A2": ("A3", D(3)), "C": ("C2", D(2)), "C2": ("C", D("0.5")),
             "E": ("E2", D(2))}  # fmt: skip
    monkeypatch.setattr(strat, "_adjusted", lambda s, aid: moved if aid == "Acct" else {})
    s = NS(scalars=lambda stmt: rows)
    assert strat.legs_of(s, NS(id="St", accountId="Acct")) == [
        LegRow("A3", D1, D(12), LegRow("A", D1, D(2))), LegRow("U", D1, None),
        LegRow("C", D2, D(2)), LegRow("E2", D2, None, LegRow("E", D2, None))]  # fmt: skip


def test_an_accounts_strategies_and_legs_are_its_own_and_not_deleted(server, alice):
    """An account's strategies in the order they opened, the same day in the order made, none
    deleted or turned down unless asked; a leg deleted is gone; a contract follows only its own
    account's adjustments, and not one deleted."""
    from itertools import permutations

    from moolakata.store.entities.accounts import Strategy, StrategyLeg

    a = new_account(alice, type="brokerage")["id"]
    b = new_account(alice, type="brokerage", name="Other", mask="5150")["id"]
    for day, strike in (("2026-10-05", "470"), ("2026-10-02", "480"), ("2026-10-05", "460"),
                        ("2026-10-02", "450"), ("2026-10-02", "440"), ("2026-10-05", "465"),
                        ("2026-10-05", "455")):  # fmt: skip
        assert option(alice, a, "sell-to-open", day, "2.00", strike=strike,
                      fees="0").status_code == 200  # fmt: skip
    assert option(alice, b, "sell-to-open", "2026-10-02", "2.00", fees="0").status_code == 200
    held = {x["symbol"].split()[2]: x["instrumentId"] for x in
            alice.get("/ui/api/positions").json()["open"] if x["accountId"] == a}  # fmt: skip

    def group(strike, account=a, **kw):
        return saved(create(alice, "Strat", accountId=account,
                            legs=[{"instrumentId": held[strike]}], **kw))["id"]  # fmt: skip

    early, gone, no = group("480"), group("450"), group("440", dismissed=True)
    same_day = [group(x) for x in ("470", "460", "465", "455")]
    other = group("480", account=b)
    assert remove(alice, "Strat", {"id": gone, "version": 1}).status_code == 200
    split = make(alice, "Txn", accountId=b, date="2026-10-06", kind="split", symbol="MSFT",
                 amount="0", splitRatio="2")  # fmt: skip
    assert split.status_code == 200, split.text
    # The same day's stamped in an order the database couldn't fall back on: the order made,
    # the ids' order, or either reversed.
    fallbacks = [same_day, sorted(same_day)]
    stamped = next(list(p) for p in permutations(same_day)
                   if all(list(p) not in (f, f[::-1]) for f in fallbacks))  # fmt: skip
    with server.db.tx(unscoped="test") as s:
        for days, sid in enumerate(reversed(stamped), 1):
            s.get(Strategy, sid).createdAt = T0 - dt.timedelta(days)
        adjusted = strat.legs_of(s, s.get(Strategy, other))[0].instrumentId
        mine = [r.instrumentId for r in strat.legs_of(s, s.get(Strategy, early))]
    assert adjusted != held["480"], "the split in b took b's contract with it"
    assert mine == [held["480"]], "and left a's as it was"
    assert remove(alice, "Txn", split.json()).status_code == 200
    with server.db.tx(unscoped="test") as s:
        assert [x.id for x in strat.of_account(s, a)] == [early, *stamped]
        assert [x.id for x in strat.of_account(s, a, dismissed=True)] == [no]
        assert strat.of_account(s, "Acct_none") == []
        assert [r.instrumentId for r in strat.legs_of(s, s.get(Strategy, other))] == [held["480"]]
        for x in s.scalars(select(StrategyLeg).where(StrategyLeg.strategyId == same_day[0])):
            x.mark_deleted(None)
    with server.db.tx(unscoped="test") as s:
        assert strat.legs_of(s, s.get(Strategy, same_day[0])) == []


def _grouped_covered_call(alice):
    """100 MSFT bought, a 500 call sold against them for $412, grouped as the covered call
    proposed: the account, the shares' instrument, and the strategy as shown."""
    a = new_account(alice, type="brokerage")["id"]
    r = create(alice, "Txn", accountId=a, date="2026-09-01", kind="buy", symbol="MSFT",
               quantity="100", price="400", amount="-40000.00")  # fmt: skip
    assert r.status_code == 200, r.text
    assert option(alice, a, "sell-to-open", "2026-10-02", "4.12", right="call", strike="500",
                  fees="0").status_code == 200  # fmt: skip
    [p] = alice.get("/ui/api/positions/strategies").json()["proposals"]
    legs = [{"instrumentId": x["instrumentId"], **({"quantity": x["quantity"]} if x["quantity"]
             else {})} for x in p["legs"]]  # fmt: skip
    saved(create(alice, "Strat", accountId=a, legs=legs))
    shares = next(x["instrumentId"] for x in p["legs"] if x["quantity"])
    [v] = alice.get("/ui/api/positions/strategies").json()["strategies"]
    return a, shares, v


def _strategy(alice):
    [v] = alice.get("/ui/api/positions/strategies").json()["strategies"]
    return v


def _figures(v):
    return {k: v[k] for k in ("shape", "maxProfit", "maxLoss", "breakevens", "capitalAtRiskNow",
                              "capitalAtRiskAtOpen", "priced")}  # fmt: skip


def test_a_strategys_shares_stay_its_own_through_a_spin_off(alice):
    """S2.4, S3.10: a spin-off moves no leg; the shares a company spun another off from are
    still held, and still the covered call's."""
    a, shares, before = _grouped_covered_call(alice)
    r = create(alice, "CorpA", accountId=a, instrumentId=shares, kind="spin-off",
               date="2026-10-06", newSymbol="SPUN", ratio="0.5", basisShare="10")  # fmt: skip
    assert r.status_code == 200, r.text
    v = _strategy(alice)
    assert (v["id"], v["shape"], v["underlying"]) == (before["id"], "Covered call", "MSFT")
    assert [(x["symbol"], x["quantity"]) for x in v["legs"]] == [
        ("MSFT", 100), ("MSFT 20NOV26 500 C", -1)]  # fmt: skip


def test_a_strategys_shares_follow_a_symbol_change_and_back(alice):
    """S2.4, S3.10: MSFT renamed MSFX: the shares leg holds the new shares, all 100, so the
    call is still covered and its figures are as they were; deleting the action brings the
    leg back."""
    a, shares, before = _grouped_covered_call(alice)
    assert (before["shape"], before["capitalAtRiskNow"]) == ("Covered call", 39588)
    r = create(alice, "CorpA", accountId=a, instrumentId=shares, kind="symbol-change",
               date="2026-10-06", newSymbol="MSFX")  # fmt: skip
    assert r.status_code == 200, r.text
    v = _strategy(alice)
    assert (v["id"], v["underlying"]) == (before["id"], "MSFX")
    assert [(x["symbol"], x["quantity"]) for x in v["legs"]] == [
        ("MSFX", 100), ("MSFT 20NOV26 500 C", -1)]  # fmt: skip
    assert _figures(v) == _figures(before)
    assert remove(alice, "CorpA", saved(r)).status_code == 200
    v = _strategy(alice)
    assert (v["underlying"], v["legs"]) == ("MSFT", before["legs"])


def test_a_strategys_shares_follow_a_merger_at_its_ratio(alice):
    """S2.4, S3.10: MSFT merged into ACQ, half a share each, and the call adjusted from the
    memo to deliver 50 ACQ: the shares leg holds the 50, which cover the call, so it is still a
    covered call, now on ACQ and at money at $1,000 a share; at open it is as it opened."""
    a, shares, before = _grouped_covered_call(alice)
    r = create(alice, "CorpA", accountId=a, instrumentId=shares, kind="merger",
               date="2026-10-06", newSymbol="ACQ", ratio="0.5")  # fmt: skip
    assert r.status_code == 200, r.text
    [g] = alice.get("/ui/api/options/adjustable").json()["items"]
    [cn] = g["contracts"]
    r = alice.post("/ui/api/options/adjust", json={"date": "2026-10-06", "contracts": [
        {"instrumentId": cn["instrumentId"], "root": "MSFT1", "strike": "500",
         "deliverable": [{"symbol": "ACQ", "shares": "50"}]}]})  # fmt: skip
    assert r.status_code == 200, r.text
    v = _strategy(alice)
    assert (v["id"], v["underlying"]) == (before["id"], "ACQ")
    assert [(x["symbol"], x["quantity"]) for x in v["legs"]] == [
        ("ACQ", 50), ("MSFT1 20NOV26 500 C", -1)]  # fmt: skip
    assert _figures(v) == _figures(before) | {"breakevens": [791.76]}
    assert alice.get(f"/ui/api/accounts/{a}").json()["capitalAtRisk"] == 39588


def _merged_calls(alice, strikes=("500",)):
    """100 MSFT bought and a call sold for each strike, $4.12 each, left ungrouped; MSFT then
    merged into ACQ, half a share each, every call adjusted from the memo to deliver 50 ACQ,
    and ACQ last traded at $800 in another account: the account, and ACQ's instrument."""
    a = new_account(alice, type="brokerage")["id"]
    r = create(alice, "Txn", accountId=a, date="2026-09-01", kind="buy", symbol="MSFT",
               quantity="100", price="400", amount="-40000.00")  # fmt: skip
    assert r.status_code == 200, r.text
    msft = saved(r)["instrumentId"]
    for k in strikes:
        assert option(alice, a, "sell-to-open", "2026-10-02", "4.12", right="call", strike=k,
                      fees="0").status_code == 200  # fmt: skip
    r = create(alice, "CorpA", accountId=a, instrumentId=msft, kind="merger",
               date="2026-10-06", newSymbol="ACQ", ratio="0.5")  # fmt: skip
    assert r.status_code == 200, r.text
    [g] = alice.get("/ui/api/options/adjustable").json()["items"]
    acq50 = [{"symbol": "ACQ", "shares": "50"}]
    r = alice.post("/ui/api/options/adjust", json={"date": "2026-10-06", "contracts": [
        {"instrumentId": cn["instrumentId"], "root": "MSFT1", "strike": cn["strike"],
         "deliverable": acq50} for cn in g["contracts"]]})  # fmt: skip
    assert r.status_code == 200, r.text
    [acq] = [x["instrumentId"] for x in alice.get("/ui/api/positions").json()["open"]
             if x["accountId"] == a and x["symbol"] == "ACQ"]  # fmt: skip
    b = new_account(alice, type="brokerage", name="Other", mask="5151")["id"]
    r = create(alice, "Txn", accountId=b, instrumentId=acq, date="2026-10-07", kind="buy",
               quantity="1", price="800", amount="-800.00")  # fmt: skip
    assert r.status_code == 200, r.text
    return a, acq


def _taken(p):
    """A proposal's legs, as a strategy taken as proposed saves them."""
    return [{"instrumentId": x["instrumentId"], **({"quantity": x["quantity"]} if x["quantity"]
             else {})} for x in p["legs"]]  # fmt: skip


def test_a_call_adjusted_to_deliver_the_acquirers_shares_held_is_proposed_covered(alice):
    """S3.5.1, S3.10: MSFT merged into ACQ and the short call adjusted to deliver 50 ACQ: the
    50 ACQ held cover it, as its underlying's own shares would, so it is proposed as a covered
    call on ACQ, and taken as proposed it is one."""
    a, _ = _merged_calls(alice)
    [p] = alice.get("/ui/api/positions/strategies").json()["proposals"]
    assert (p["kind"], p["shape"], p["underlying"]) == ("covered-call", "Covered call", "ACQ")
    assert [(x["symbol"], x["quantity"]) for x in p["legs"]] == [
        ("ACQ", 50), ("MSFT1 20NOV26 500 C", None)]  # fmt: skip
    st = saved(create(alice, "Strat", accountId=a, legs=_taken(p)))
    assert (st["shape"], st["underlying"]) == ("Covered call", "ACQ")
    assert alice.get("/ui/api/positions/strategies").json()["proposals"] == []


def test_the_acquirers_shares_cover_an_adjusted_call_outside_a_strategy_until_sold(alice):
    """S3.5.6, S3.10: outside a strategy, the 50 ACQ held cover the call adjusted to deliver
    them: a covered call's risk, their value less the premium, the same as grouped; sold, the
    call is uncovered and the account's risk unlimited."""
    a, acq = _merged_calls(alice)
    alone = _risk(alice, a)
    assert alone == 50 * 800 - 412
    [p] = alice.get("/ui/api/positions/strategies").json()["proposals"]
    st = saved(create(alice, "Strat", accountId=a, legs=_taken(p)))
    assert st["capitalAtRiskNow"] == alone, "grouped, the same legs risk the same"
    assert remove(alice, "Strat", st).status_code == 200
    assert _risk(alice, a) == alone
    r = create(alice, "Txn", accountId=a, instrumentId=acq, date="2026-10-09", kind="sell",
               quantity="50", price="800", amount="40000.00")  # fmt: skip
    assert r.status_code == 200, r.text
    assert _risk(alice, a) is None


def test_the_acquirers_shares_cover_adjusted_calls_in_turn(alice):
    """S3.5.6: two calls adjusted to deliver 50 ACQ each and 50 ACQ held: the shares cover one
    call, never both, so the other is uncovered; 50 more bought, both are covered."""
    a, acq = _merged_calls(alice, ("500", "510"))
    assert _risk(alice, a) is None
    r = create(alice, "Txn", accountId=a, instrumentId=acq, date="2026-10-09", kind="buy",
               quantity="50", price="800", amount="-40000.00")  # fmt: skip
    assert r.status_code == 200, r.text
    assert _risk(alice, a) == 100 * 800 - 2 * 412


def test_a_covered_call_rolls_onto_the_acquirers_calls_after_a_merger(alice):
    """S3.5.2, S3.10: the covered call grouped on MSFT, MSFT merged into ACQ and the call
    adjusted to deliver 50 ACQ; the adjusted call assigned and an ACQ call sold the same day is
    offered as its roll, on the same underlying, and taken in."""
    a, shares, before = _grouped_covered_call(alice)
    r = create(alice, "CorpA", accountId=a, instrumentId=shares, kind="merger",
               date="2026-10-06", newSymbol="ACQ", ratio="0.5")  # fmt: skip
    assert r.status_code == 200, r.text
    [g] = alice.get("/ui/api/options/adjustable").json()["items"]
    [cn] = g["contracts"]
    r = alice.post("/ui/api/options/adjust", json={"date": "2026-10-06", "contracts": [
        {"instrumentId": cn["instrumentId"], "root": "MSFT1", "strike": "500",
         "deliverable": [{"symbol": "ACQ", "shares": "50"}]}]})  # fmt: skip
    assert r.status_code == 200, r.text
    [old] = [x["instrumentId"] for x in _strategy(alice)["legs"] if x["symbol"][:5] == "MSFT1"]
    r = alice.post(f"/ui/api/accounts/{a}/options/{old}/settle",
                   json={"how": "assign", "date": "2026-10-09", "contracts": "1"})  # fmt: skip
    assert r.status_code == 201, r.text
    r = option_trade(alice, a, "2026-10-09", "sell-to-open", "acq", "call", "900",
                     "2026-12-18", "1", "5.00")  # fmt: skip
    assert r.status_code == 200, r.text
    [roll] = alice.get("/ui/api/positions/strategies").json()["proposals"]
    assert (roll["kind"], roll["strategyId"], roll["underlying"]) == ("roll", before["id"], "ACQ")
    r = alice.post(f"/ui/api/strategies/{before['id']}/roll",
                   json={"roll": [{"instrumentId": roll["legs"][0]["instrumentId"]}]})  # fmt: skip
    assert r.status_code == 200, r.text
    v = r.json()
    assert (v["underlying"], v["closedOn"], len(v["legs"])) == ("ACQ", None, 3)


# ---- A strategy as its draft saves it (S3.5) ----


def _book_of_legs(alice):
    """An account with 100 MSFT bought Jan 5, a MSFT 480 put sold Sep 2, a MSFT 500 call sold
    Sep 15 and an AAPL 200 put sold Sep 1, and another account's MSFT 470 put: the account and
    each holding's instrument, by a short name."""
    a = new_account(alice, type="brokerage", name="Brokerage")["id"]
    r = create(alice, "Txn", accountId=a, date="2026-01-05", kind="buy", symbol="MSFT",
               quantity="100", price="400", amount="-40000.00")  # fmt: skip
    assert r.status_code == 200, r.text
    for day, right, strike, under in (("2026-09-02", "put", "480", "msft"),
                                      ("2026-09-15", "call", "500", "msft"),
                                      ("2026-09-01", "put", "200", "aapl")):  # fmt: skip
        r = option_trade(alice, a, day, "sell-to-open", under, right, strike, "2026-11-20", "1",
                         "2.00")  # fmt: skip
        assert r.status_code == 200, r.text
    b = new_account(alice, type="brokerage", name="Other", mask="5150")["id"]
    r = option(alice, b, "sell-to-open", "2026-09-02", "2.00", strike="470", fees="0")
    assert r.status_code == 200, r.text
    names = {"MSFT": "shares", "MSFT 20NOV26 480 P": "put", "MSFT 20NOV26 500 C": "call",
             "AAPL 20NOV26 200 P": "aapl", "MSFT 20NOV26 470 P": "other"}  # fmt: skip
    held = {names[x["symbol"]]: x["instrumentId"] for x in
            alice.get("/ui/api/positions").json()["open"]}  # fmt: skip
    return a, held


def _legs(held, *names):
    return [{"instrumentId": held[n], **({"quantity": "100"} if n == "shares" else {})}
            for n in names]  # fmt: skip


def _refused(r):
    assert r.status_code == 422, r.text
    return [(e["field"], e["code"], e["message"]) for e in r.json()["errors"]]


@pytest.mark.parametrize(
    ("legs", "more", "error"),
    [
        ((), {}, ("legs", "legs-missing", "The legs it groups.")),
        (("put", "put"), {}, ("legs", "legs-twice", "Each leg once.")),
        (("put", "other"), {}, ("legs", "leg-not-held", "Legs held in this account.")),
        (("put", "aapl"), {}, ("legs", "legs-differ", "Legs on one underlying.")),
        (("shares",), {}, ("legs", "no-option", "At least one option leg.")),
        (("put",), {"marginRequirement": "-0.01"},
         ("marginRequirement", "margin-invalid", "An amount, or none.")),
    ],
)  # fmt: skip
def test_a_strategy_refused_names_its_field_and_says_why(alice, legs, more, error):
    a, held = _book_of_legs(alice)
    r = create(alice, "Strat", accountId=a, legs=_legs(held, *legs), **more)
    assert _refused(r) == [error]


def test_an_option_leg_is_in_one_strategy_and_shares_in_any(server, alice):
    """A contract grouped is taken; shares can cover a call in one strategy and back another;
    a proposal turned down is kept whatever its legs are in."""
    a, held = _book_of_legs(alice)
    saved(create(alice, "Strat", accountId=a, legs=_legs(held, "shares", "call")))
    r = create(alice, "Strat", accountId=a, legs=_legs(held, "put", "call"))
    assert _refused(r) == [("legs", "leg-grouped", "A leg is already in a strategy.")]
    st = saved(create(alice, "Strat", accountId=a, legs=_legs(held, "shares", "put")))
    assert [x["symbol"] for x in st["legs"]] == ["MSFT", "MSFT 20NOV26 480 P"]
    saved(create(alice, "Strat", accountId=a, legs=_legs(held, "put", "call"), dismissed=True))
    texts = [e["text"] for e in alice.get("/ui/api/activity").json()["items"]]
    assert sum("grouped legs as a strategy in Brokerage" in x for x in texts) == 2
    me = alice.get("/ui/api/session").json()["user"]["id"]
    assert _logged(server, "strategy.grouped") == (me, "account", a, me, "{}")


def test_a_strategy_opens_the_day_its_earliest_leg_did_and_keeps_what_is_typed(alice):
    a, held = _book_of_legs(alice)
    st = saved(create(alice, "Strat", accountId=a, legs=_legs(held, "call", "put"),
                      name=f"  {'W' * 85}  ", cashSecured=True, marginRequirement="0"))  # fmt: skip
    assert (st["openedOn"], st["name"], st["cashSecured"], st["marginRequirement"]) == (
        "2026-09-02", "W" * 80, True, "0.00")  # fmt: skip
    assert [x["addedOn"] for x in st["legs"]] == ["2026-09-02", "2026-09-02"]
    assert [(x["symbol"], x["kind"], x["strike"], x["expiry"], x["value"]) for x in
            st["legs"]] == [("MSFT 20NOV26 500 C", "call", 500, "2026-11-20", 0),
                            ("MSFT 20NOV26 480 P", "put", 480, "2026-11-20", -8000)]  # fmt: skip
    assert (st["unrealized"], st["realized"], st["pl"], st["credit"]) == (-7600, 0, -7600, 400)
    unnamed = saved(create(alice, "Strat", accountId=a, legs=_legs(held, "aapl"), name="   "))
    assert unnamed["name"] == "Short put", "a blank name is none: the shape names it"


def test_a_strategys_legs_account_and_turning_down_are_fixed(alice):
    a, held = _book_of_legs(alice)
    b = new_account(alice, type="brokerage", name="Third", mask="5151")["id"]
    st = saved(create(alice, "Strat", accountId=a, legs=_legs(held, "shares", "call")))
    same = _legs(held, "shares", "call")
    for field, value in (("accountId", b), ("legs", _legs(held, "call")), ("dismissed", True)):
        fields = {"accountId": a, "legs": same, field: value}
        r = change(alice, "Strat", st, **fields)
        assert _refused(r) == [
            (field, "strategy-fixed", "Its legs change by a roll; undo it to regroup.")
        ]
    r = change(alice, "Strat", st, accountId=a, legs=same, marginRequirement="-1")
    assert _refused(r) == [("marginRequirement", "margin-invalid", "An amount, or none.")]
    r = change(alice, "Strat", st, accountId=a, legs=same, name=f" {'N' * 81}",
               cashSecured=True, marginRequirement="0")  # fmt: skip
    v = saved(r)
    assert (v["name"], v["cashSecured"], v["marginRequirement"], v["version"]) == (
        "N" * 80, True, "0.00", st["version"] + 1)  # fmt: skip
    v = saved(change(alice, "Strat", v, accountId=a, legs=same, marginRequirement="10"))
    assert (v["name"], v["cashSecured"]) == ("N" * 80, True), "what isn't sent stays"
    for blank in ("  ", None):
        v = saved(change(alice, "Strat", v, accountId=a, legs=same, name=blank,
                         cashSecured=False, marginRequirement=None))  # fmt: skip
        assert (v["name"], v["cashSecured"], v["marginRequirement"]) == (
            "Covered call", False, None)  # fmt: skip
        v = saved(change(alice, "Strat", v, accountId=a, legs=same, name="Named"))


def test_a_strategy_turned_down_or_gone_is_not_found_and_another_users_is_not_theirs(server):
    from edits import share
    from test_sharing import setup

    u, c = setup(server)
    alice, bob = c["alice"], c["bob"]
    a, held = _book_of_legs(alice)
    no = saved(create(alice, "Strat", accountId=a, legs=_legs(held, "put"), dismissed=True))
    assert no["id"] and no["legs"][0]["symbol"] == "MSFT 20NOV26 480 P"
    assert change(alice, "Strat", no, accountId=a, legs=_legs(held, "put"),
                  dismissed=True).status_code == 404  # fmt: skip
    st = saved(create(alice, "Strat", accountId=a, legs=_legs(held, "put")))
    assert share(alice, "account", a, users={u["bob"].id: "read"}).status_code == 200
    assert change(bob, "Strat", st, accountId=a, legs=_legs(held, "put"),
                  name="Mine").status_code == 403  # fmt: skip
    assert create(bob, "Strat", accountId=a, legs=_legs(held, "aapl")).status_code == 403
    v = bob.get("/ui/api/positions/strategies").json()
    assert [x["id"] for x in v["strategies"]] == [st["id"]] and v["proposals"] == []
    assert alice.get("/ui/api/positions/strategies").json()["proposals"] != []
    assert remove(alice, "Strat", st).status_code == 200
    assert remove(alice, "Strat", st).status_code == 404


def _spread(alice, a, day="2026-10-02"):
    """A 540/530 bull put spread opened on `day` for an $80 credit: its legs."""
    for action, strike, premium in (("sell-to-open", "540", "2.00"),
                                    ("buy-to-open", "530", "1.20")):  # fmt: skip
        r = option(alice, a, action, day, premium, strike=strike, fees="0")
        assert r.status_code == 200, r.text
    return [{"instrumentId": x["instrumentId"]} for x in alice.get("/ui/api/positions").json()[
        "open"] if x["accountId"] == a and x["symbol"].split()[2] in ("540", "530")]  # fmt: skip


def test_a_strategys_return_is_its_pl_on_its_capital_at_risk_at_open(alice):
    """S3.5.5: $100 realized, closed, on the $920 the spread risked at open is 10.87%; a short
    straddle with no margin typed risks no limit, and with a margin of 0 nothing: neither has a
    return."""
    a = new_account(alice, type="brokerage")["id"]
    st = saved(create(alice, "Strat", accountId=a, legs=_spread(alice, a)))
    option(alice, a, "buy-to-close", "2026-10-09", "1.00", strike="540", fees="0")
    option(alice, a, "sell-to-close", "2026-10-09", "1.20", strike="530", fees="0")
    [v] = alice.get("/ui/api/positions/strategies").json()["strategies"]
    assert (v["id"], v["pl"], v["capitalAtRiskAtOpen"], v["returnPct"]) == (
        st["id"], 100, 920, 10.87)  # fmt: skip
    b = new_account(alice, type="brokerage", name="Straddle", mask="5150")["id"]
    for right in ("call", "put"):
        assert option(alice, b, "sell-to-open", "2026-10-02", "3.00", right=right,
                      fees="0").status_code == 200  # fmt: skip
    legs = [{"instrumentId": x["instrumentId"]} for x in
            alice.get("/ui/api/positions").json()["open"] if x["accountId"] == b]  # fmt: skip
    st = saved(create(alice, "Strat", accountId=b, legs=legs))
    for right in ("call", "put"):
        assert option(alice, b, "buy-to-close", "2026-10-09", "1.00", right=right,
                      fees="0").status_code == 200  # fmt: skip
    [v] = [x for x in alice.get("/ui/api/positions/strategies").json()["strategies"]
           if x["id"] == st["id"]]  # fmt: skip
    assert (v["pl"], v["capitalAtRiskAtOpen"], v["returnPct"]) == (400, None, None)
    v = saved(change(alice, "Strat", v, accountId=b, legs=legs, marginRequirement="0"))
    assert (v["pl"], v["capitalAtRiskAtOpen"], v["returnPct"]) == (400, 0, None)


def test_strategies_list_open_first_by_underlying_then_the_day_opened(alice):
    a = new_account(alice, type="brokerage")["id"]
    opened = (("msft", "2026-09-03", "100"), ("aapl", "2026-09-04", "100"),
              ("msft", "2026-09-01", "110"), ("aapl", "2026-09-02", "110"))  # fmt: skip
    for under, day, strike in opened:
        r = option_trade(alice, a, day, "sell-to-open", under, "put", strike, "2026-11-20", "1",
                         "1.00")  # fmt: skip
        assert r.status_code == 200, r.text
    for x in alice.get("/ui/api/positions").json()["open"]:
        saved(create(alice, "Strat", accountId=a, legs=[{"instrumentId": x["instrumentId"]}]))
    r = alice.post(f"/ui/api/accounts/{a}/options/"
                   f"{_strategy_of(alice, 'AAPL', '2026-09-02')}/settle",
                   json={"how": "expired", "date": "2026-09-30", "contracts": "1"})  # fmt: skip
    assert r.status_code == 201, r.text
    got = [(x["underlying"], x["openedOn"], x["closedOn"]) for x in
           alice.get("/ui/api/positions/strategies").json()["strategies"]]  # fmt: skip
    assert got == [("AAPL", "2026-09-04", None), ("MSFT", "2026-09-01", None),
                   ("MSFT", "2026-09-03", None), ("AAPL", "2026-09-02", "2026-09-30")]  # fmt: skip


def _strategy_of(alice, underlying, opened):
    v = alice.get("/ui/api/positions/strategies").json()["strategies"]
    [st] = [x for x in v if (x["underlying"], x["openedOn"]) == (underlying, opened)]
    return st["legs"][0]["instrumentId"]


def test_a_roll_takes_new_legs_on_its_underlying_and_turned_down_isnt_offered_again(alice):
    a = new_account(alice, type="brokerage")["id"]
    st = saved(create(alice, "Strat", accountId=a, legs=_spread(alice, a)))
    option(alice, a, "buy-to-close", "2026-10-10", "1.00", strike="540", fees="0")
    option(alice, a, "sell-to-open", "2026-10-10", "1.50", strike="535", fees="0")
    r = option_trade(alice, a, "2026-10-10", "sell-to-open", "aapl", "put", "200",
                     "2026-11-20", "1", "1.00")  # fmt: skip
    assert r.status_code == 200, r.text
    held = {x["symbol"]: x["instrumentId"] for x in alice.get("/ui/api/positions").json()["open"]}
    url = f"/ui/api/strategies/{st['id']}/roll"
    r = alice.post(url, json={"roll": [{"instrumentId": held["AAPL 20NOV26 200 P"]}]})
    assert _refused(r) == [("roll", "legs-differ", "A roll stays on the same underlying.")]
    r = alice.post(url, json={"declineRoll": [held["MSFT 20NOV26 535 P"]]})
    assert r.status_code == 200, r.text
    assert len(r.json()["legs"]) == 2
    v = alice.get("/ui/api/positions/strategies").json()
    assert [p["kind"] for p in v["proposals"] if p["strategyId"] == st["id"]] == []
    # Taken in by hand after all, a leg already in it is passed over.
    r = alice.post(url, json={"roll": [{"instrumentId": held["MSFT 20NOV26 535 P"]},
                                       {"instrumentId": held["MSFT 20NOV26 530 P"]}]})  # fmt: skip
    assert r.status_code == 200, r.text
    legs = {x["symbol"]: x["addedOn"] for x in r.json()["legs"]}
    assert legs == {"MSFT 20NOV26 540 P": "2026-10-02", "MSFT 20NOV26 530 P": "2026-10-02",
                    "MSFT 20NOV26 535 P": "2026-10-10"}  # fmt: skip


def test_a_roll_is_of_a_strategy_the_caller_may_change(server):
    from edits import share
    from test_sharing import setup

    u, c = setup(server)
    a = new_account(c["alice"], type="brokerage")["id"]
    st = saved(create(c["alice"], "Strat", accountId=a, legs=_spread(c["alice"], a)))
    assert share(c["alice"], "account", a, users={u["bob"].id: "read"}).status_code == 200
    assert c["bob"].post(f"/ui/api/strategies/{st['id']}/roll", json={}).status_code == 403
    assert c["alice"].post("/ui/api/strategies/Strat_01m4tj4gg0f02s596bvjcn26rw/roll",
                           json={}).status_code == 404  # fmt: skip
