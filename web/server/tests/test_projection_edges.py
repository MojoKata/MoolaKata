"""Projections at their edges (requirements S6): each input refused at its field (R3.11,
S13.8.3), never an error out of the model."""

from decimal import Decimal

import pytest
from conftest import make_user, sign_in
from edits import change, make, new_id, saved
from test_projections import T0

from moolakata import clock


@pytest.fixture
def jane(server):
    clock.fix(T0)
    make_user(server, "jane", born=1979)
    yield sign_in(server, "jane")
    clock.fix(None)


def refused(r, field, code="input-invalid"):
    assert r.status_code == 422, r.text
    assert [(e["field"], e["code"]) for e in r.json()["errors"]] == [(field, code)]


@pytest.mark.parametrize("amount", ["NaN", "inf", "-inf", float("nan"), float("inf"), -1,
                                    1e11, "1e11", "lots", "", True, None])  # fmt: skip
def test_a_typed_amount_is_a_finite_number_in_range(jane, amount):
    """R3.11: a typed amount that isn't a number of 0 or more within its bound is refused at
    its field, never sent on to the model."""
    built = {"kind": "typed", "amount": amount, "allocation": {"usStocks": 100}}
    r = make(jane, "Prjct", name="What if", goal="savings", builtOn=built,
             inputs={"target": 1000, "date": "2028-01-01", "monthly": 0,
                     "fees": 0.1})  # fmt: skip
    refused(r, "builtOn.amount", "amount-invalid")


def test_a_typed_amount_of_nothing_its_most_or_a_decimal_is_taken(jane):
    for amount in (0, 1e10, "1000.50"):
        built = {"kind": "typed", "amount": amount, "allocation": {"cash": 100}}
        r = make(jane, "Prjct", name="What if", goal="savings", builtOn=built,
                 inputs={"target": 1000, "date": "2028-01-01", "monthly": 0,
                     "fees": 0.1})  # fmt: skip
        assert r.status_code == 200, r.text


RETIRE = {"people": [{"name": "Jane", "birthYear": 1979, "retireAge": 62}],
          "income": [{"label": "Pension", "person": 0, "fromAge": 67, "monthly": 900}],
          "contribution": {"amount": 30000, "growth": 3}, "horizonAge": 95,
          "fees": 0.1}  # fmt: skip
PENSION = {"person": 0, "fromAge": 67, "monthly": 1}
US = "overrides.classes.usStocks"
TYPED = {"kind": "typed", "amount": 500000, "allocation": {"usStocks": 60, "bonds": 40}}
SPENT = {"monthly": 0, "fees": 0.1}  # a goal saving nothing more, at the usual fees


def _retire(c, built=TYPED, **inputs):
    return make(c, "Prjct", name="Retire", goal="retirement", builtOn=built,
                inputs={**RETIRE, **inputs})  # fmt: skip


@pytest.mark.parametrize(
    ("inputs", "field"),
    [
        ({"withdrawal": {"method": "fixed", "amount": "lots"}}, "withdrawal.amount"),
        ({"withdrawal": {"method": "fixed", "amount": None}}, "withdrawal.amount"),
        ({"withdrawal": {"method": "fixed"}}, "withdrawal.amount"),
        ({"withdrawal": {"method": "fixed", "amount": -1}}, "withdrawal.amount"),
        ({"withdrawal": {"method": "percent", "percent": None}}, "withdrawal.percent"),
        ({"withdrawal": {"method": "percent", "percent": 101}}, "withdrawal.percent"),
        ({"withdrawal": "fourPercent"}, "withdrawal"),
        ({"overrides": {"inflation": "x"}}, "overrides.inflation"),
        ({"overrides": {"inflation": 21}}, "overrides.inflation"),
        ({"overrides": {"classes": {"usStocks": {"return": None}}}}, f"{US}.return"),
        ({"overrides": {"classes": {"usStocks": {"volatility": -1}}}}, f"{US}.volatility"),
        ({"overrides": {"classes": {"usStocks": {"growth": 1}}}}, f"{US}.growth"),
        ({"overrides": {"classes": {"usStocks": 7}}}, US),
        ({"overrides": {"classes": {"gold": {"return": 5}}}}, "overrides.classes.gold"),
        ({"overrides": {"taxes": 5}}, "overrides.taxes"),
        ({"overrides": []}, "overrides"),
        ({"income": [{"person": "x", "fromAge": 67, "monthly": 1}]}, "income.0.person"),
        ({"income": [{"person": 1, "fromAge": 67, "monthly": 1}]}, "income.0.person"),
        ({"income": [{"person": 0, "fromAge": None, "monthly": 1}]}, "income.0.fromAge"),
        ({"income": [{"person": 0, "fromAge": 67, "monthly": None}]}, "income.0.monthly"),
        ({"income": [{**PENSION, "inflates": "no"}]}, "income.0.inflates"),
        ({"income": [{**PENSION, "label": 5}]}, "income.0.label"),
        ({"income": ["pension"]}, "income.0"),
        ({"people": ["Jane"]}, "people.0"),
        ({"people": [{"name": 5, "birthYear": 1979}]}, "people.0.name"),
        ({"contribution": None}, "contribution"),
        ({"contribution": 3000}, "contribution"),
        ({"runs": None}, "runs"),
        ({"bitcoinModel": "moon"}, "bitcoinModel"),
    ],
)  # fmt: skip
def test_every_input_the_model_reads_is_checked_at_its_field(jane, inputs, field):
    """S13.8.3, R3.11: an input the model reads that isn't of its kind and range is refused
    at its field, never a server error."""
    refused(_retire(jane, **inputs), f"inputs.{field}")


def test_a_target_date_that_isnt_text_is_refused(jane):
    r = make(jane, "Prjct", name="Car", goal="savings", builtOn=TYPED,
             inputs={"target": 1000, "date": 20280101, "monthly": 0,
                     "fees": 0.1})  # fmt: skip
    refused(r, "inputs.date", "date-invalid")


@pytest.mark.parametrize(
    "allocation",
    [{"usStocks": 300, "cash": -200}, {"usStocks": "60"}, {"usStocks": float("nan")},
     {"gold": 100}, {"usStocks": 0}, {}, [60, 40], "60/40", {"usStocks": 101}],
)  # fmt: skip
def test_a_typed_mix_is_shares_of_the_classes_never_levered(jane, allocation):
    """S6.4.2.2: a typed amount gives its own mix, each class's share 0 to 100, some of it
    held: never a negative share that levers another."""
    refused(_retire(jane, {**TYPED, "allocation": allocation}), "builtOn.allocation",
            "allocation-invalid")  # fmt: skip


@pytest.mark.parametrize("built", [{"kind": "accounts", "ids": 5},
                                   {"kind": "accounts", "ids": [{"id": "x"}]},
                                   {"kind": "portfolio", "id": 5}])  # fmt: skip
def test_what_it_is_built_on_names_ids(jane, built):
    r = _retire(jane, built)
    assert r.status_code == 422, r.text
    assert [e["field"] for e in r.json()["errors"]] == ["builtOn"]


def test_the_inputs_the_form_sends_are_taken(jane):
    r = _retire(jane, withdrawal={"method": "fixed", "amount": 60000},
                overrides={"inflation": 3, "classes": {"bonds": {"return": 3.5}}},
                bitcoinModel="", contribution={"amount": 0, "growth": None})  # fmt: skip
    assert r.status_code == 200, r.text
    assert r.json()["result"]["assumptions"]["inflation"] == 3
    r = _retire(jane, {**TYPED, "allocation": {"usStocks": 100, "cash": 0}},
                withdrawal={"method": "percent"}, bitcoinModel="stockToFlow")  # fmt: skip
    assert r.status_code == 200, r.text


def made(r) -> dict:
    assert r.status_code == 200, r.text
    return r.json()


def _in_cents(xs) -> bool:
    return all(Decimal(str(x)) == Decimal(str(x)).quantize(Decimal("0.01")) for x in xs)


def _bitcoin(server, closes=(("2026-10-12", "100000"),)):
    """Bitcoin, with its stored daily closes (S4.6)."""
    import datetime as dt

    from moolakata import ids
    from moolakata.store.entities.accounts import Instrument
    from moolakata.store.entities.prices import Price

    iid = ids.new_id("Instr")
    with server.db.tx(unscoped="test") as s:
        s.add(Instrument(id=iid, symbol="BTC", name="Bitcoin", instrumentClass="crypto"))
        for day, close in closes:
            s.add(Price(instrumentId=iid, date=dt.date.fromisoformat(day), close=Decimal(close),
                        source="test"))  # fmt: skip


@pytest.fixture
def closes():
    """Stored closes value bitcoin, as on the running server."""
    from test_account_world import _closes_installed

    with _closes_installed():
        yield


def test_its_figures_go_out_in_cents(server, jane, closes):
    """S6.9: the fan's percentiles, its path at expected returns, each scenario's path and
    every money answer are rounded to cents and sent as exact numbers; chances aren't money."""
    _bitcoin(server)
    crypto = {**TYPED, "amount": 123456.78, "allocation": {"usStocks": 80, "crypto": 20}}
    res = made(_retire(jane, crypto, bitcoinModel="ark"))["result"]
    paths = [*res["percentiles"].values(), *res["real"].values(), res["expected"],
             *res["scenarios"].values()]  # fmt: skip
    assert len(res["scenarios"]) == 3 and all(_in_cents(p) for p in paths)
    assert _in_cents([res["answer"]["atRetirement"]])
    assert res["percentiles"]["50"][0] == Decimal("123456.78")
    saving = make(jane, "Prjct", name="Car", goal="savings", builtOn=TYPED,
                  inputs={"target": 600000.5, "date": "2029-06-30", "monthly": 333.33,
                          "fees": 0.1})  # fmt: skip
    a = made(saving)["result"]["answer"]
    assert _in_cents([a["target"], a["monthly"], a["neededMonthly"]])
    assert 0 <= a["chance"] <= 1  # a share of the runs, as it is


def test_an_education_answer_goes_out_in_cents(jane):
    who = {"kind": "person", "id": jane.get("/ui/api/profile").json()["personId"]}
    r = make(jane, "Prjct", name="College", goal="education", builtOn=TYPED,
             inputs={"beneficiary": who, "firstYear": 2031, "costBasis": "typed",
                     "cost": 23456.789, "monthly": 100.5, "fees": 0.1})  # fmt: skip
    a = made(r)["result"]["answer"]
    money = [a["costToday"], *a["costs"], a["atStart"], a["needed"], a["monthly"]]
    assert _in_cents(money) and a["costs"][0] != a["costToday"]
    assert a["neededMonthly"] is None or _in_cents([a["neededMonthly"]])


def test_a_baseline_is_kept_in_cents(server, jane):
    import json

    from moolakata.store.entities.projections import Projection

    p = made(_retire(jane))
    assert jane.post(f"/ui/api/projections/{p['id']}/activate").status_code == 200
    with server.db.read(unscoped="test") as s:
        base = json.loads(s.get(Projection, p["id"]).baseline)
    assert all(_in_cents(base[k]) for k in ("p10", "p50", "p90"))


def test_the_bitcoin_grows_as_the_model_does_in_the_same_year(server, jane, closes):
    """S6.3.1, S6.4.2.3: a bitcoin model sets the bitcoin's growth each year; the projection's
    year grows by the model's growth into that year, its first year's included, so the
    stock-to-flow step at the 2028 halving lands in 2028."""
    from moolakata.projections import bitcoin, taxtables

    _bitcoin(server)
    btc = {"kind": "typed", "amount": 100000, "allocation": {"crypto": 100}}
    r = make(jane, "Prjct", name="Stack", goal="savings", builtOn=btc,
             inputs={"target": 1, "date": "2033-12-31", "fees": 0, "monthly": 0,
                     "bitcoinModel": "stockToFlow"})  # fmt: skip
    res = made(r)["result"]
    years, path = res["years"], [float(v) for v in res["expected"]]
    with server.db.read(unscoped="test") as s:
        f = taxtables.figures(s, 2026)
    model = [bitcoin.stock_to_flow(y, f) for y in years]
    # Every whole year: the last counts only the part up to the target date.
    for t in range(1, len(years) - 1):
        assert path[t] / path[t - 1] == pytest.approx(model[t] / model[t - 1], rel=1e-6)
    jump = max(range(1, len(years) - 1), key=lambda t: path[t] / path[t - 1])
    assert years[jump] == 2028


CRYPTO = {"kind": "typed", "amount": 100000, "allocation": {"crypto": 100}}


def _stack(c, model):
    goal = {"target": 1, "date": "2033-12-31", "monthly": 0, "fees": 0.1, "bitcoinModel": model}
    return made(make(c, "Prjct", name="Stack", goal="savings", builtOn=CRYPTO, inputs=goal))


def test_with_no_bitcoin_price_no_model_starts_from_a_made_up_one(server, jane, closes):
    """S6.3.1: a model's path starts from today's price; with none on the server, Compare
    models has nothing to show, and a projection's bitcoin grows by the crypto assumption,
    saying the model isn't used, its bear, base and bull cases too."""
    _bitcoin(server, closes=())
    v = jane.get("/ui/api/bitcoin-models").json()
    assert (v["price"], v["rows"], v["history"]) == (None, [], [])
    plain = _stack(jane, "assumption")["result"]
    assert not plain["noBitcoinPrice"]
    for model in ("powerLaw", "ark"):
        res = _stack(jane, model)["result"]
        assert res["noBitcoinPrice"] and res["scenarios"] == {}
        assert res["expected"] == plain["expected"], "the crypto assumption's growth"


def test_compare_models_draws_the_price_history_behind_the_paths(server, jane, closes):
    """S6.3.1.1: the stored daily closes go out with the paths, oldest first, exact; the
    paths start from the latest."""
    days = (("2024-01-02", "45000.5"), ("2025-06-30", "107000"), ("2026-10-12", "98000.25"))
    _bitcoin(server, closes=days)
    v = jane.get("/ui/api/bitcoin-models").json()
    assert v["price"] == Decimal("98000.25")
    assert v["history"] == [[d, Decimal(c)] for d, c in days]
    assert {r["model"] for r in v["rows"]} == {"powerLaw", "logRegression", "stockToFlow",
                                                "saylor", "ark"}  # fmt: skip
    ark = next(r for r in v["rows"] if r["model"] == "ark")
    assert ark["path"][0] == [2026, 98000]
    assert not _stack(jane, "ark")["result"]["noBitcoinPrice"]


@pytest.mark.parametrize(
    ("method", "second"),
    [("fourPercent", 96000 - 4400), ("percent", 96000 - 3840)],
)
def test_the_4_percent_rule_is_4_percent_at_retirement_then_rising_with_inflation(method, second):
    """S6.2.1: the 4% rule takes 4% of the balance at retirement, then that amount rising with
    inflation (10% here), never 4% of each year's balance, which is the percentage method."""
    from moolakata.projections import engine

    plan = engine.Plan(start=100000.0, weights={"cash": 1.0}, returns={"cash": 0.0},
                       vols={"cash": 0.0}, inflation=0.1, fees=0.0, first_year=2026, years=3,
                       withdraw_from=1, withdrawal={"method": method, "percent": 4})  # fmt: skip
    path = engine.run(plan).percentiles[50]
    assert path[1] == pytest.approx(96000) and path[2] == pytest.approx(second)


def test_a_targets_path_stops_at_its_year(server, jane, closes):
    """S6.3.1.6: a target says nothing of the years after it: Compare models draws ARK's path
    to 2030 and Saylor's to 2045, and their figures after them are none."""
    _bitcoin(server)
    rows = {r["model"]: r for r in jane.get("/ui/api/bitcoin-models").json()["rows"]}
    for model, last in (("ark", 2030), ("saylor", 2045), ("powerLaw", 2045)):
        years = [y for y, _ in rows[model]["path"]]
        assert years == list(range(2026, last + 1)), model
    assert rows["ark"]["at"]["2030"] == rows["ark"]["path"][-1][1]
    assert (rows["ark"]["at"]["2035"], rows["ark"]["at"]["2045"]) == (None, None)
    assert None not in rows["saylor"]["at"].values()


def test_after_a_targets_year_the_bitcoin_grows_by_the_crypto_assumption(server, jane, closes):
    """S6.3.1.6: a projection following ARK grows its bitcoin toward the 2030 target, then by
    the crypto assumption's return (8%), its bear, base and bull paths alike."""
    _bitcoin(server)
    r = make(jane, "Prjct", name="Stack", goal="savings", builtOn=CRYPTO,
             inputs={"target": 1, "date": "2033-12-31", "fees": 0, "monthly": 0,
                     "bitcoinModel": "ark"})  # fmt: skip
    res = made(r)["result"]
    years = res["years"]
    for path in (res["expected"], *res["scenarios"].values()):
        growth = {y: float(path[t]) / float(path[t - 1]) for t, y in enumerate(years) if t}
        assert growth[2030] > 1.4, "toward the target, the bear case's too"
        assert growth[2031] == pytest.approx(1.08, rel=1e-6)
        assert growth[2032] == pytest.approx(1.08, rel=1e-6)


@pytest.mark.parametrize("share", [1.0, 0.5])
def test_the_fan_follows_the_model_then_the_assumption(share):
    """S6.3.1.6: each run grows the bitcoin by the model while it has a price, and by the
    crypto assumption after; other coins by the assumption throughout."""
    from moolakata.projections import engine

    plan = engine.Plan(start=100.0, weights={"crypto": 1.0}, returns={"crypto": 0.1},
                       vols={"crypto": 0.0}, inflation=0.0, fees=0.0, first_year=2026,
                       years=3, crypto_path=[1.0, 2.0, None], bitcoin_share=share)  # fmt: skip
    path = engine.run(plan).percentiles[50]
    first = 100.0 * (share * 2.0 + (1 - share) * 1.1)
    assert path == pytest.approx([100.0, first, first * 1.1])


def test_a_cases_path_grows_from_its_first_year():
    """The bear, base and bull paths take the same year's growth as the fan: the first year's
    growth brings today's balance to next year's."""
    from moolakata.projections import engine

    plan = engine.Plan(start=100.0, weights={"crypto": 1.0}, returns={"crypto": 0.0},
                       vols={"crypto": 0.0}, inflation=0.0, fees=0.0, first_year=2026,
                       years=4)  # fmt: skip
    f = {"btcArk2030": [200_000.0, 400_000.0, 800_000.0]}
    paths = engine.scenario_paths(plan, "ark", f, 100_000.0)
    assert paths["base"] == pytest.approx([100.0, 100.0 * 4**0.25, 200.0, 100.0 * 4**0.75])


@pytest.mark.parametrize("value", [[4], [4, 31], [13, 1], [0, 15], [4.5, 15], [2, 29],
                                   [4, 15, 1], [float("nan"), 15]])  # fmt: skip
def test_a_federal_due_date_is_a_month_and_a_day(value):
    """S16.11, S8.15.3: a corrected federal due date is a real month and day of any year."""
    from moolakata.projections import taxtables

    with pytest.raises(taxtables.Invalid, match="a month and a day"):
        taxtables.check("federalDue", value)
    assert taxtables.check("federalDue", [4, 30]) == [4, 30]
    assert taxtables.check("federalDue", [4.0, 30]) == [4, 30]


@pytest.mark.parametrize("key", ["iraLimit", "collectablesRate", "rmdAge", "btcArk2030"])
def test_no_figure_is_nan_or_infinite(key):
    """R3.11: a correction is a number, never NaN or an infinity, whatever its kind."""
    from moolakata.projections import taxtables

    for bad in (float("nan"), float("inf")):
        value = [bad, 1.0, 2.0] if key == "btcArk2030" else bad
        with pytest.raises(taxtables.Invalid):
            taxtables.check(key, value)


@pytest.mark.parametrize(
    ("key", "value", "words"),
    [
        ("btcArk2030", [500_000, 1_200_000], "3 numbers"),
        ("btcArk2030", [], "numbers separated by commas"),
        ("btcArk2030", "1,2,3", "numbers separated by commas"),
        ("collectablesRate", 101, "a percentage up to 100"),
        ("iraLimit", -1, "a number, zero or more"),
        ("iraLimit", True, "a number, zero or more"),
        ("noSuchFigure", 1, "there is no such figure"),
    ],
)
def test_a_correction_is_of_its_figures_kind(key, value, words):
    """S16.11, R3.11: a correction is a figure's kind: so many numbers for a model, a
    percentage up to 100, an amount of zero or more; and only of a figure MoolaKata ships."""
    from moolakata.projections import taxtables

    with pytest.raises(taxtables.Invalid) as e:
        taxtables.check(key, value)
    assert str(e.value) == words
    assert taxtables.check("collectablesRate", 100) == 100


def test_a_correction_of_a_figure_no_longer_shipped_is_passed_over(server):
    """A year's figures read only the corrections of figures this release ships: one kept of
    a figure since dropped is left out, never sent on as a figure."""
    from moolakata import ids
    from moolakata.projections import taxtables
    from moolakata.store.entities.projections import TaxFigure

    with server.db.tx(unscoped="test: a correction of a dropped figure") as s:
        s.add(TaxFigure(id=ids.new_id("TaxFg"), year=2026, key="oldFigure", value="5"))
        s.add(TaxFigure(id=ids.new_id("TaxFg"), year=2026, key="iraLimit", value="7600"))
        s.flush()
        got = taxtables.figures(s, 2026)
    assert "oldFigure" not in got and got["iraLimit"] == 7600


def test_a_bad_due_date_is_refused_and_the_books_still_open(server, admin_client):
    """A due date no calendar has is refused at its field, so the year's books still find
    their due date."""
    from moolakata.taxes import books

    fig = {"year": 2026, "key": "federalDue", "value": [4, 31]}
    op = {"op": "create", "entity": "TaxFg", "id": new_id("TaxFg"), "fields": fig}
    r = admin_client.post("/ui/api/save", json={"ops": [op]})
    assert r.status_code == 422, r.text
    e = r.json()["errors"][0]
    assert (e["field"], e["code"], e["message"]) == ("value", "figure-invalid",
                                                     "Must be a month and a day.")  # fmt: skip
    with server.db.read(unscoped="test") as s:
        assert books.federal_due(s, 2026).month == 4


@pytest.mark.parametrize(
    ("cls", "symbol", "name", "grows"),
    [
        ("cash", "SWVXX", "Schwab Value Advantage", "cash"),
        ("money-market", "VMFXX", "Federal Money Market", "cash"),
        ("bond", "T 4 30", "Treasury note", "bonds"),
        ("crypto", "ETH", "Ether", "crypto"),
        ("metal", "GLD", "Gold", "metals"),
        ("option", "AAPL 261218C200", "AAPL call", None),
        ("etf", "VNQ", "Vanguard Real Estate", "realEstate"),
        ("etf", "BND", "Total Bond Market", "bonds"),
        ("etf", "VXUS", "Total International", "intlStocks"),
        ("stock", "AAPL", "Apple", "usStocks"),
    ],
)
def test_a_holding_grows_by_its_class(cls, symbol, name, grows):
    """S6.4.2.2: cash and money-market funds are cash, bonds and bond funds bonds, crypto
    crypto, metals metals; an option isn't grown; other funds and shares are US stocks unless
    their name says international or real estate."""
    from moolakata.projections import asset_class
    from moolakata.store.entities.accounts import Instrument

    inst = Instrument(id="Instr_test", symbol=symbol, name=name, instrumentClass=cls)
    assert asset_class(inst) == grows


def test_tracking_follows_only_what_a_projection_grows(server, jane):
    """S6.4.2.2, S6.7.3: tracking counts what the start counted: cash, and a metal item at its
    value; a loan isn't drawn on, so it is left out of both."""
    from test_accounts import add, new_account
    from test_assets import item

    cash = new_account(jane, name="Savings", type="savings")
    add(jane, cash["id"], "1000.00", "2026-10-01")
    metals = new_account(jane, name="Metals", type="precious-metals")
    item(jane, metals["id"], name="Silver bar", valuation="spot", metal="silver",
         unitWeight="100", weightUnit="ozt", purity=".999", costBasis="2800")  # fmt: skip
    loan = new_account(jane, name="Car loan", type="auto-loan")
    ids_ = [cash["id"], metals["id"], loan["id"]]
    p = made(make(jane, "Prjct", name="House", goal="savings",
                  builtOn={"kind": "accounts", "ids": ids_},
                  inputs={"target": 50000, "date": "2030-01-01", **SPENT}))  # fmt: skip
    assert p["result"]["start"] == Decimal("3800.00")
    assert jane.post(f"/ui/api/projections/{p['id']}/activate").status_code == 200
    t = jane.get(f"/ui/api/projections/{p['id']}").json()["tracking"]
    assert t["points"][-1][1] == Decimal("3800.00") and t["status"] == "on track"


def test_tracking_with_the_account_gone_has_nothing_to_draw(server, jane):
    """S6.7.3: the one account it is built on removed, it starts from nothing and tracking has
    no balance to draw."""
    from edits import remove
    from test_accounts import add, new_account

    cash = new_account(jane, name="Savings", type="savings")
    add(jane, cash["id"], "1000.00", "2026-10-01")
    p = made(make(jane, "Prjct", name="House", goal="savings",
                  builtOn={"kind": "accounts", "ids": [cash["id"]]},
                  inputs={"target": 50000, "date": "2030-01-01", **SPENT}))  # fmt: skip
    assert jane.post(f"/ui/api/projections/{p['id']}/activate").status_code == 200
    acct = jane.get(f"/ui/api/accounts/{cash['id']}").json()
    r = remove(jane, "Acct", acct, confirm=True)
    assert r.status_code == 200, r.text
    got = jane.get(f"/ui/api/projections/{p['id']}").json()
    assert (got["builtOnLabel"], got["result"]["start"]) == ("no accounts", 0)
    assert (got["tracking"]["points"], got["tracking"]["band"]) == ([], [])


def test_one_active_education_plan_per_beneficiary(jane):
    """S6.7.1: an education goal's subject is its beneficiary: making a second for the same
    person active turns off the first, and one for another person stays."""
    me = {"kind": "person", "id": jane.get("/ui/api/profile").json()["personId"]}
    gift = made(make(jane, "GfPln", name="Lisa Doe", sex="female", birthYear=2018))
    lisa = {"kind": "person", "id": gift["personId"]}
    goal = {"name": "College", "goal": "education", "builtOn": TYPED}
    a = made(make(jane, "Prjct", **goal, inputs={"beneficiary": me, **SPENT}))
    b = made(make(jane, "Prjct", **goal, inputs={"beneficiary": me, **SPENT}))
    other = made(make(jane, "Prjct", **goal, inputs={"beneficiary": lisa, **SPENT}))
    for p in (a, other):
        assert jane.post(f"/ui/api/projections/{p['id']}/activate").status_code == 200
    assert _replaces(jane, b) == [{"id": a["id"], "name": "College", "accounts": []}]


def test_an_education_goal_is_for_a_person_never_a_user(server, jane):
    """S6.2.2, S1.8.1, S10.10: a beneficiary is a person the user can see; a user's id, their
    own or anyone's (a private person's, a linked server's), is refused at its field."""
    from conftest import make_user

    make_user(server, "john")
    with server.db.read(unscoped="test") as s:
        from moolakata.store.entities.users import User

        users = {u.username: u for u in s.query(User)}
    college = {"name": "College", "goal": "education", "builtOn": TYPED}
    for user in ("jane", "john"):
        who = {"kind": "user", "id": users[user].id}
        r = make(jane, "Prjct", **college, inputs={"beneficiary": who, **SPENT})
        refused(r, "inputs.beneficiary", "beneficiary-invalid")
    me = {"kind": "person", "id": users["jane"].personId}
    p = made(make(jane, "Prjct", **college, inputs={"beneficiary": me, **SPENT}))
    assert p["result"]["answer"]["name"] == users["jane"].displayName
    r = change(
        jane, "Prjct", p, inputs={"beneficiary": {"kind": "user", "id": users["jane"].id}, **SPENT}
    )
    refused(r, "inputs.beneficiary", "beneficiary-invalid")


def test_a_viewer_not_shared_its_accounts_sees_its_start_but_not_their_mix(server, jane):
    """S6.1, S5.1.1: shared a projection but not every account it is built on, a viewer sees
    its start, a result, but not the mix the accounts hold, nor the ids of those they aren't
    shared; shared them all, they see the mix as its owner does."""
    from edits import share
    from test_accounts import add, new_account

    joint = new_account(jane, name="Joint savings", type="savings")
    own = new_account(jane, name="Jane's savings", type="savings")
    add(jane, joint["id"], "1000.00", "2026-10-01")
    add(jane, own["id"], "9000.00", "2026-10-01")
    built = {"kind": "accounts", "ids": [joint["id"], own["id"]]}
    p = made(make(jane, "Prjct", name="House", goal="savings", builtOn=built,
                  inputs={"target": 50000, "date": "2030-01-01", "monthly": 500,
                          "fees": 0.1}))  # fmt: skip
    assert jane.post(f"/ui/api/projections/{p['id']}/activate").status_code == 200
    john = make_user(server, "john")
    for kind, item in (("projection", p["id"]), ("account", joint["id"])):
        assert share(jane, kind, item, users={john.id: "read"}).status_code == 200
    johns = sign_in(server, "john")
    me = johns.get("/ui/api/profile").json()
    assert change(johns, "User", me, shownProjectionIds=[p["id"]]).status_code == 200
    theirs = johns.get(f"/ui/api/projections/{p['id']}").json()
    (row,) = johns.get("/ui/api/projections").json()["items"]
    (plan,) = johns.get("/ui/api/dashboard/plans").json()["items"]
    assert theirs["result"]["start"] == Decimal("10000.00") and theirs["result"]["weights"] is None
    for seen in (theirs, row, plan):
        assert seen["builtOn"] == {"kind": "accounts", "ids": [joint["id"]]}
    mine = jane.get(f"/ui/api/projections/{p['id']}").json()
    assert mine["result"]["weights"] == {"cash": 1} and mine["builtOn"] == built
    assert share(jane, "account", own["id"], users={john.id: "read"}).status_code == 200
    whole = johns.get(f"/ui/api/projections/{p['id']}").json()
    assert whole["result"]["weights"] == {"cash": 1} and whole["builtOn"] == built


def _coins(server, account_id: str, btc: str) -> None:
    """Bitcoin held in a wallet, received on Oct 1."""
    import datetime as dt

    from moolakata import ids
    from moolakata.store.entities.accounts import Lot, Transaction
    from moolakata.store.repos import ledger as repo

    day = dt.date(2026, 10, 1)
    with server.db.tx(unscoped="test: coins held") as s:
        coin = repo.instrument(s, "BTC", "Bitcoin", "crypto")
        got = Transaction(id=ids.new_id("Txn"), accountId=account_id, date=day,
                          kind="transfer-in", amount=Decimal(0), instrumentId=coin.id,
                          quantity=Decimal(btc))  # fmt: skip
        s.add(got)
        s.flush()
        s.add(Lot(id=ids.new_id("Lot"), accountId=account_id, instrumentId=coin.id,
                  transactionId=got.id, acquiredOn=day, quantity=Decimal(btc),
                  costBasis=Decimal("50000")))  # fmt: skip


def test_a_viewer_not_shared_its_accounts_isnt_told_its_bitcoin_share(server, jane, closes):
    """S6.1, S5.1.1: the share of bitcoin in what it is built on is of their mix: a viewer
    shared the projection but not every account it is built on isn't sent it; shared them
    all, they are, as its owner is."""
    from edits import share
    from test_accounts import add, new_account

    _bitcoin(server)
    joint = new_account(jane, name="Joint savings", type="savings")
    add(jane, joint["id"], "1000.00", "2026-10-01")
    wallet = new_account(jane, name="Cold storage", type="crypto-wallet")
    _coins(server, wallet["id"], "0.5")
    built = {"kind": "accounts", "ids": [joint["id"], wallet["id"]]}
    p = made(make(jane, "Prjct", name="Stack", goal="savings", builtOn=built,
                  inputs={"target": 90000, "date": "2030-01-01", **SPENT,
                          "bitcoinModel": "powerLaw"}))  # fmt: skip
    mine = p["result"]
    assert (mine["bitcoinModel"], mine["bitcoinShare"]) == ("powerLaw", 1)
    john = make_user(server, "john")
    for kind, item in (("projection", p["id"]), ("account", joint["id"])):
        assert share(jane, kind, item, users={john.id: "read"}).status_code == 200
    johns = sign_in(server, "john")
    theirs = johns.get(f"/ui/api/projections/{p['id']}").json()["result"]
    assert theirs["start"] == mine["start"] and theirs["bitcoinShare"] is None
    assert share(jane, "account", wallet["id"], users={john.id: "read"}).status_code == 200
    whole = johns.get(f"/ui/api/projections/{p['id']}").json()["result"]
    assert whole["bitcoinShare"] == 1


def test_a_writer_not_shared_its_accounts_keeps_the_owners_unseen_ones(server, jane):
    """S6.1: a writer shared the projection but not every account it is built on changes what
    it is built on among the accounts they see; those they don't see stay, and are still not
    named to them."""
    from edits import share
    from test_accounts import add, new_account

    joint = new_account(jane, name="Joint savings", type="savings")
    own = new_account(jane, name="Jane's savings", type="savings")
    house = new_account(jane, name="House fund", type="savings")
    for a in (joint, own, house):
        add(jane, a["id"], "1000.00", "2026-10-01")
    p = made(make(jane, "Prjct", name="House", goal="savings",
                  builtOn={"kind": "accounts", "ids": [joint["id"], own["id"]]},
                  inputs={"target": 50000, "date": "2030-01-01", **SPENT}))  # fmt: skip
    john = make_user(server, "john")
    assert share(jane, "projection", p["id"], users={john.id: "write"}).status_code == 200
    for a in (joint, house):
        assert share(jane, "account", a["id"], users={john.id: "read"}).status_code == 200
    johns = sign_in(server, "john")
    theirs = johns.get(f"/ui/api/projections/{p['id']}").json()
    assert theirs["builtOn"]["ids"] == [joint["id"]]
    chosen = {"kind": "accounts", "ids": [joint["id"], house["id"]]}
    after = saved(change(johns, "Prjct", theirs, builtOn=chosen))
    assert after["builtOn"] == chosen, "the unseen one still not named to them"
    mine = jane.get(f"/ui/api/projections/{p['id']}").json()
    assert sorted(mine["builtOn"]["ids"]) == sorted([joint["id"], house["id"], own["id"]])
    assert mine["result"]["start"] == Decimal("3000.00")
    # Changing only its inputs leaves what it is built on as it is.
    after = saved(change(johns, "Prjct", after, inputs={**after["inputs"], "monthly": 100}))
    assert len(jane.get(f"/ui/api/projections/{p['id']}").json()["builtOn"]["ids"]) == 3
    # Down to one they see, the owner's unseen one stays.
    one = {"kind": "accounts", "ids": [house["id"]]}
    after = saved(change(johns, "Prjct", after, builtOn=one))
    mine = jane.get(f"/ui/api/projections/{p['id']}").json()
    assert sorted(mine["builtOn"]["ids"]) == sorted([house["id"], own["id"]])
    # None of theirs is a blank, refused (R3.11), never read as the owner's alone.
    r = change(johns, "Prjct", after, builtOn={"kind": "accounts", "ids": []})
    refused(r, "builtOn", "accounts-unknown")
    # Shared none of them now, they still change its inputs, and it stays built on them.
    assert share(jane, "account", house["id"], users={john.id: "none"}).status_code == 200
    theirs = johns.get(f"/ui/api/projections/{p['id']}").json()
    assert theirs["builtOn"]["ids"] == []
    saved(change(johns, "Prjct", theirs, inputs={**theirs["inputs"], "monthly": 200}))
    mine = jane.get(f"/ui/api/projections/{p['id']}").json()
    assert sorted(mine["builtOn"]["ids"]) == sorted([house["id"], own["id"]])
    assert mine["inputs"]["monthly"] == 200


def test_a_portfolio_not_shared_is_not_named_by_its_id(server, jane):
    from edits import share
    from test_accounts import add, new_account

    own = new_account(jane, name="Jane's savings", type="savings")
    add(jane, own["id"], "9000.00", "2026-10-01")
    port = made(make(jane, "Portf", name="Nest egg", accountIds=[own["id"]]))
    p = made(make(jane, "Prjct", name="House", goal="savings",
                  builtOn={"kind": "portfolio", "id": port["id"]},
                  inputs={"target": 50000, "date": "2030-01-01", **SPENT}))  # fmt: skip
    john = make_user(server, "john")
    assert share(jane, "projection", p["id"], users={john.id: "read"}).status_code == 200
    theirs = sign_in(server, "john").get(f"/ui/api/projections/{p['id']}").json()
    assert theirs["builtOn"] == {"kind": "portfolio"} and theirs["result"]["weights"] is None


def test_a_typed_mix_is_the_projections_own_and_shown_to_a_viewer(server, jane):
    from edits import share

    p = made(_retire(jane))
    john = make_user(server, "john")
    assert share(jane, "projection", p["id"], users={john.id: "read"}).status_code == 200
    theirs = sign_in(server, "john").get(f"/ui/api/projections/{p['id']}").json()
    assert theirs["result"]["weights"] == {"usStocks": Decimal("0.6"), "bonds": Decimal("0.4")}
    assert theirs["builtOn"] == TYPED


def _saving(c, name, built):
    return made(make(c, "Prjct", name=name, goal="savings", builtOn=built,
                     inputs={"target": 50000, "date": "2030-01-01", **SPENT}))  # fmt: skip


def _active(c) -> set[str]:
    return {p["name"] for p in c.get("/ui/api/projections").json()["items"] if p["active"]}


def _replaces(c, p) -> list[dict]:
    r = c.get(f"/ui/api/projections/{p['id']}/replaces")
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_an_account_backs_at_most_one_active_savings_target(jane):
    """S6.7.1: two active savings targets over one account would both count its whole balance;
    making one active turns off those it shares an account with, a portfolio's included, and
    asks first, naming them and the accounts they share."""
    from test_accounts import add, new_account

    joint = new_account(jane, name="Joint Savings", type="savings")
    other = new_account(jane, name="Brokerage", type="savings")
    for a in (joint, other):
        add(jane, a["id"], "9000.00", "2026-10-01")
    car = _saving(jane, "Car", {"kind": "accounts", "ids": [joint["id"]]})
    trip = _saving(jane, "Trip", {"kind": "accounts", "ids": [other["id"]]})
    port = made(make(jane, "Portf", name="Both", accountIds=[joint["id"], other["id"]]))
    house = _saving(jane, "House", {"kind": "portfolio", "id": port["id"]})
    typed = _saving(jane, "What if", {"kind": "typed", "amount": 1000})
    for p in (car, trip, typed):
        assert jane.post(f"/ui/api/projections/{p['id']}/activate").json() == {"replaced": []}
    assert _active(jane) == {"Car", "Trip", "What if"}, "disjoint and typed never conflict"
    assert _replaces(jane, house) == [
        {"id": car["id"], "name": "Car", "accounts": ["Joint Savings"]},
        {"id": trip["id"], "name": "Trip", "accounts": ["Brokerage"]},
    ]
    assert jane.post(f"/ui/api/projections/{house['id']}/activate").json() == {
        "replaced": ["Car", "Trip"]
    }
    assert _active(jane) == {"House", "What if"}
    # One account in common is enough.
    again = _saving(jane, "Car again", {"kind": "accounts", "ids": [joint["id"]]})
    assert [x["name"] for x in _replaces(jane, again)] == ["House"]
    assert _replaces(jane, typed) == []


def test_one_active_retirement_per_people_asked_the_same_way(jane):
    """S6.7.1: a retirement's subject is its people, whatever it is built on."""
    a = made(_retire(jane))
    b = made(_retire(jane, people=[{"name": "Jane", "birthYear": 1979, "retireAge": 65}]))
    other = made(_retire(jane, people=[{"name": "Jim", "birthYear": 1980, "retireAge": 65}]))
    for p in (a, other):
        assert jane.post(f"/ui/api/projections/{p['id']}/activate").status_code == 200
    assert _replaces(jane, b) == [{"id": a["id"], "name": "Retire", "accounts": []}]


def test_only_its_owner_asks_what_making_it_active_replaces(server, jane):
    from edits import share

    p = _saving(jane, "What if", {"kind": "typed", "amount": 1000})
    john = make_user(server, "john")
    assert share(jane, "projection", p["id"], users={john.id: "read"}).status_code == 200
    r = sign_in(server, "john").get(f"/ui/api/projections/{p['id']}/replaces")
    assert r.status_code == 403


# Every figure each goal's model reads, given: a blank of any one is refused at its field.
GIVEN = {
    "retirement": RETIRE,
    "savings": {"target": 1000, "date": "2028-01-01", "monthly": 100, "fees": 0.1},
    "education": {"firstYear": 2031, "monthly": 100, "fees": 0.1},
}  # fmt: skip
BLANK = object()  # the key left out


@pytest.mark.parametrize("blank", [BLANK, None, ""], ids=["missing", "null", "empty"])
@pytest.mark.parametrize(
    ("goal", "path"),
    [("retirement", "contribution.amount"), ("retirement", "horizonAge"),
     ("retirement", "fees"), ("savings", "monthly"), ("savings", "fees"),
     ("education", "monthly"), ("education", "fees")],
)  # fmt: skip
def test_a_blank_the_model_would_read_as_0_or_its_default_is_refused(jane, goal, path, blank):
    """R3.11: a contribution, a monthly saving, the fees and the age a retirement runs to are
    each refused blank at their field, never read as 0 or the default; made or changed."""
    import copy

    inputs = copy.deepcopy(GIVEN[goal])
    if goal == "education":
        inputs["beneficiary"] = {"kind": "person",
                                 "id": jane.get("/ui/api/profile").json()["personId"]}  # fmt: skip
    p = made(make(jane, "Prjct", name="Goal", goal=goal, builtOn=TYPED, inputs=inputs))
    *group, key = path.split(".")
    at = inputs
    for part in group:
        at = at[part]
    if blank is BLANK:
        del at[key]
    else:
        at[key] = blank
    refused(make(jane, "Prjct", name="Goal", goal=goal, builtOn=TYPED, inputs=inputs),
            f"inputs.{path}")  # fmt: skip
    refused(change(jane, "Prjct", p, inputs=inputs), f"inputs.{path}")


def test_after_school_ends_whats_left_stays_and_grows():
    """S6.2.2: an education plan pays each year of school's cost, rising by its inflation,
    until school ends; what is left over stays, and grows on."""
    from moolakata.projections import engine

    plan = engine.Plan(start=1000.0, weights={"cash": 1.0}, returns={"cash": 0.1},
                       vols={"cash": 0.0}, inflation=0.0, fees=0.0, first_year=2026, years=4,
                       withdraw_from=1,
                       withdrawal={"method": "costs", "amount": 100.0, "growth": 0.0,
                                   "years": 2})  # fmt: skip
    r = engine.run(plan)
    assert r.percentiles[50] == pytest.approx([1000.0, 1000.0, 1000.0, 1100.0])
    assert r.lasted == 1.0


def test_a_model_with_no_cases_has_no_case_paths():
    """S6.3.1.4: only a model with bear, base and bull cases draws them."""
    from moolakata.projections import engine

    plan = engine.Plan(start=100.0, weights={"crypto": 1.0}, returns={"crypto": 0.0},
                       vols={"crypto": 0.0}, inflation=0.0, fees=0.0, first_year=2026,
                       years=2)  # fmt: skip
    assert engine.scenario_paths(plan, "powerLaw", {}, 100_000.0) == {}


def test_your_assumption_is_no_published_model():
    """S6.3.1: the crypto assumption has no median path of a model's, and no targets."""
    from moolakata.projections import bitcoin

    assert bitcoin.median_path("assumption", {}, 100_000.0, [2026, 2027]) is None
    assert bitcoin.scenarios("assumption", {}) is None
    assert bitcoin.scenarios("powerLaw", {}) is None


def test_only_the_figures_its_goal_reads_are_asked_for(jane):
    """A savings target has no contribution, age or people to give: only what its model reads
    is asked for."""
    made(make(jane, "Prjct", name="Car", goal="savings", builtOn=TYPED, inputs=GIVEN["savings"]))
