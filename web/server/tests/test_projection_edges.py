"""Projections at their edges (requirements S6): each input refused at its field (R3.11,
S13.8.3), never an error out of the model."""

from decimal import Decimal

import pytest
from conftest import make_user, sign_in
from edits import change, make, new_id
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
             inputs={"target": 1000, "date": "2028-01-01"})  # fmt: skip
    refused(r, "builtOn.amount", "amount-invalid")


def test_a_typed_amount_of_nothing_its_most_or_a_decimal_is_taken(jane):
    for amount in (0, 1e10, "1000.50"):
        built = {"kind": "typed", "amount": amount, "allocation": {"cash": 100}}
        r = make(jane, "Prjct", name="What if", goal="savings", builtOn=built,
                 inputs={"target": 1000, "date": "2028-01-01"})  # fmt: skip
        assert r.status_code == 200, r.text


RETIRE = {"people": [{"name": "Jane", "birthYear": 1979, "retireAge": 62}],
          "income": [{"label": "Pension", "person": 0, "fromAge": 67, "monthly": 900}]}  # fmt: skip
PENSION = {"person": 0, "fromAge": 67, "monthly": 1}
US = "overrides.classes.usStocks"
TYPED = {"kind": "typed", "amount": 500000, "allocation": {"usStocks": 60, "bonds": 40}}


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
             inputs={"target": 1000, "date": 20280101})  # fmt: skip
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
                bitcoinModel="", contribution={"amount": None, "growth": None})  # fmt: skip
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
                  inputs={"target": 600000.5, "date": "2029-06-30", "monthly": 333.33})  # fmt: skip
    a = made(saving)["result"]["answer"]
    assert _in_cents([a["target"], a["monthly"], a["neededMonthly"]])
    assert 0 <= a["chance"] <= 1  # a share of the runs, as it is


def test_an_education_answer_goes_out_in_cents(jane):
    who = {"kind": "person", "id": jane.get("/ui/api/profile").json()["personId"]}
    r = make(jane, "Prjct", name="College", goal="education", builtOn=TYPED,
             inputs={"beneficiary": who, "firstYear": 2031, "costBasis": "typed",
                     "cost": 23456.789, "monthly": 100.5})  # fmt: skip
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
             inputs={"target": 1, "date": "2033-12-31", "fees": 0,
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
    goal = {"target": 1, "date": "2033-12-31", "bitcoinModel": model}
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
        r = make(jane, "Prjct", **college, inputs={"beneficiary": who})
        refused(r, "inputs.beneficiary", "beneficiary-invalid")
    me = {"kind": "person", "id": users["jane"].personId}
    p = made(make(jane, "Prjct", **college, inputs={"beneficiary": me}))
    assert p["result"]["answer"]["name"] == users["jane"].displayName
    r = change(jane, "Prjct", p, inputs={"beneficiary": {"kind": "user", "id": users["jane"].id}})
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
                  inputs={"target": 50000, "date": "2030-01-01", "monthly": 500}))  # fmt: skip
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


def test_a_portfolio_not_shared_is_not_named_by_its_id(server, jane):
    from edits import share
    from test_accounts import add, new_account

    own = new_account(jane, name="Jane's savings", type="savings")
    add(jane, own["id"], "9000.00", "2026-10-01")
    port = made(make(jane, "Portf", name="Nest egg", accountIds=[own["id"]]))
    p = made(make(jane, "Prjct", name="House", goal="savings",
                  builtOn={"kind": "portfolio", "id": port["id"]},
                  inputs={"target": 50000, "date": "2030-01-01"}))  # fmt: skip
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
                     inputs={"target": 50000, "date": "2030-01-01"}))  # fmt: skip


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
