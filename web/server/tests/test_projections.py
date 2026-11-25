"""Projections and assumptions (requirements S6.1–S6.9) and the tax tables (S16.11)."""

import datetime as dt
from decimal import Decimal

import pytest
from conftest import make_user, sign_in
from edits import change, make, new_id, remove, saved, share
from test_accounts import add, new_account

from moolakata import alerts, clock
from moolakata.projections import engine

T0 = dt.datetime(2026, 10, 13, 12, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


@pytest.fixture
def jane(server, frozen):
    make_user(server, "jane", born=1979)
    return sign_in(server, "jane")


def retirement(c, **inputs):
    body = {
        "name": "Retire at 62",
        "goal": "retirement",
        "builtOn": {"kind": "typed", "amount": 500000, "allocation": {"usStocks": 60, "bonds": 40}},
        "inputs": {
            "people": [{"name": "Jane", "birthYear": 1979, "retireAge": 62}],
            "contribution": {"amount": 30000, "growth": 3},
            "withdrawal": {"method": "fourPercent"},
            "income": [{"label": "Social Security", "person": 0, "fromAge": 67, "monthly": 2900}],
            "horizonAge": 95,
            "fees": 0.1,
            **inputs,
        },
    }
    r = make(c, "Prjct", **body)
    assert r.status_code == 200, r.text
    return r.json()


def test_the_same_inputs_give_the_same_figures(jane):
    p = retirement(jane)
    again = jane.get(f"/ui/api/projections/{p['id']}").json()
    assert again["result"]["percentiles"]["50"] == p["result"]["percentiles"]["50"]
    res = p["result"]
    assert res["years"][0] == 2026 and res["years"][-1] == 1979 + 95
    assert res["assumptions"]["inflation"] == 2.5, "the assumptions it ran on, in full"
    assert [x["name"] for x in res["answer"]["people"]] == ["Jane"]
    lo, mid, hi = (res["percentiles"][k][-10] for k in ("10", "50", "90"))
    assert lo <= mid <= hi
    assert 0 <= res["answer"]["chance"] <= 1 and res["answer"]["retireYear"] == 2041
    assert p["headline"].endswith("chance the money lasts to 95")


def test_retiring_later_makes_the_money_more_likely_to_last(jane):
    tight = {"withdrawal": {"method": "fixed", "amount": 90000}, "income": []}
    early = retirement(jane, people=[{"name": "A", "birthYear": 1979, "retireAge": 55}], **tight)
    late = retirement(jane, people=[{"name": "A", "birthYear": 1979, "retireAge": 67}], **tight)
    assert late["result"]["answer"]["chance"] > early["result"]["answer"]["chance"] + Decimal("0.2")


def test_a_savings_target_says_how_likely_and_what_would_do_it(jane):
    r = make(
        jane,
        "Prjct",
        name="House deposit",
        goal="savings",
        builtOn={"kind": "typed", "amount": 38200, "allocation": {"cash": 100}},
        inputs={"target": 60000, "date": "2028-10-01", "monthly": 300, "fees": 0.1},
    )
    assert r.status_code == 200, r.text
    a = r.json()["result"]["answer"]
    assert a["chance"] < 0.5, "300 a month falls short"
    assert 800 < a["neededMonthly"] < 1000


def test_inputs_are_checked(jane):
    r = make(
        jane,
        "Prjct",
        name="",
        goal="lottery",
        builtOn={"kind": "accounts", "ids": ["Acct_nope"]},
        inputs={"fees": 9, "date": "2001-01-01"},
    )
    assert r.status_code == 422
    assert {e["field"] for e in r.json()["errors"]} >= {
        "name",
        "goal",
        "builtOn",
        "inputs.fees",
        "inputs.date",
    }


def test_a_changed_projection_is_checked_as_a_new_one_is(jane):
    """Its name, what it is built on and its inputs are each refused at their field."""
    p = retirement(jane)
    for fields, field in (
        ({"name": " "}, "name"),
        ({"builtOn": {"kind": "moon"}}, "builtOn"),
        ({"inputs": {**p["inputs"], "fees": 9}}, "inputs.fees"),
    ):
        r = change(jane, "Prjct", p, **fields)
        assert r.status_code == 422, fields
        assert [e["field"] for e in r.json()["errors"]] == [field]


def test_an_education_projection_keeps_its_beneficiary_made_or_changed(jane):
    """S6.6, S10.10: an education goal is for someone: made or changed without them, it is
    refused at the beneficiary."""
    me = jane.get("/ui/api/profile").json()["personId"]
    body = {"name": "College", "goal": "education",
            "builtOn": {"kind": "typed", "amount": 1000, "allocation": {"bonds": 100}},
            "inputs": {"startAge": 18, "schoolYears": 4, "cost": 20000, "monthly": 0,
                       "fees": 0.1}}  # fmt: skip
    r = make(jane, "Prjct", **body)
    assert r.status_code == 422
    assert [e["field"] for e in r.json()["errors"]] == ["inputs.beneficiary"]
    who = {"beneficiary": {"kind": "person", "id": me}}
    r = make(jane, "Prjct", **{**body, "inputs": {**body["inputs"], **who}})
    assert r.status_code == 200, r.text
    r = change(jane, "Prjct", r.json(), inputs=body["inputs"])
    assert r.status_code == 422
    assert [e["field"] for e in r.json()["errors"]] == ["inputs.beneficiary"]


def test_built_on_accounts_starts_from_their_value(jane):
    acct = new_account(jane, name="Savings", type="savings")
    add(jane, acct["id"], "12000.00", "2026-10-01")
    r = make(
        jane,
        "Prjct",
        name="Car",
        goal="savings",
        builtOn={"kind": "accounts", "ids": [acct["id"]]},
        inputs={"target": 20000, "date": "2028-01-01", "monthly": 250, "fees": 0.1},
    )
    res = r.json()["result"]
    assert res["start"] == 12000.0 and res["weights"] == {"cash": 1.0}
    assert r.json()["builtOnLabel"] == "Savings"


def test_one_active_plan_per_subject_and_its_baseline(jane):
    a = retirement(jane)
    b = retirement(jane, contribution={"amount": 40000, "growth": 3})
    assert jane.post(f"/ui/api/projections/{a['id']}/activate").json() == {"replaced": []}
    assert jane.post(f"/ui/api/projections/{b['id']}/activate").json() == {
        "replaced": ["Retire at 62"]
    }
    rows = {p["id"]: p for p in jane.get("/ui/api/projections").json()["items"]}
    assert rows[b["id"]]["active"] and not rows[a["id"]]["active"]
    got = jane.get(f"/ui/api/projections/{b['id']}").json()
    assert got["tracking"]["status"] == "untracked", "a typed amount has nothing to track"
    # Changing inputs keeps the baseline unless asked to re-baseline.
    base = got["result"]["percentiles"]["50"]
    r = change(jane, "Prjct", got, inputs={**got["inputs"], "fees": 1.0})
    assert saved(r)["result"]["percentiles"]["50"] != base
    assert saved(r)["baselineAt"] == got["baselineAt"]
    clock.fix(dt.datetime(2026, 10, 13, 12, 5, tzinfo=dt.UTC))
    r = change(jane, "Prjct", saved(r), inputs={**got["inputs"], "fees": 0.5}, rebaseline=True)
    assert saved(r)["baselineAt"] == "2026-10-13T12:05:00Z"
    assert change(jane, "Prjct", saved(r), goal="education").json()["errors"][0]["code"] == (
        "goal-fixed"
    )


def test_tracking_against_the_band_and_the_alert_when_behind(server, jane):
    acct = new_account(jane, name="Brokerage cash", type="savings")
    add(jane, acct["id"], "100000.00", "2026-10-01")
    r = make(
        jane,
        "Prjct",
        name="Nest egg",
        goal="savings",
        builtOn={"kind": "accounts", "ids": [acct["id"]]},
        inputs={"target": 150000, "date": "2030-01-01", "monthly": 500, "fees": 0.1},
    )
    pid = r.json()["id"]
    jane.post(f"/ui/api/projections/{pid}/activate")
    assert jane.get(f"/ui/api/projections/{pid}").json()["tracking"]["status"] == "on track"
    # Most of it is spent, and a month passes.
    add(jane, acct["id"], "-60000.00", "2026-10-20")
    clock.fix(dt.datetime(2026, 11, 3, 12, tzinfo=dt.UTC))
    jane2 = sign_in(server, "jane")
    assert jane2.get(f"/ui/api/projections/{pid}").json()["tracking"]["status"] == "behind"
    opened = alerts.evaluate(server)
    assert [a.kind for a in opened] == ["projection-behind"]
    plans = jane2.get("/ui/api/dashboard/plans").json()["items"]
    assert plans[0]["status"] == "behind" and plans[0]["actual"]


def test_assumptions_are_each_users_and_checked(jane):
    got = jane.get("/ui/api/assumptions").json()
    figures = got["figures"]
    assert figures["inflation"] == 2.5 and figures["classes"]["usStocks"]["return"] == 7.0
    figures["classes"]["usStocks"]["return"] = 6.0
    op = {"op": "create", "entity": "Asmpt", "id": new_id("Asmpt"), "fields": {"figures": figures}}
    mine = saved(jane.post("/ui/api/save", json={"ops": [op]}))
    assert mine["figures"]["classes"]["usStocks"]["return"] == 6.0
    r = change(jane, "Asmpt", mine, figures={**figures, "inflation": 40})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "figures.inflation"
    # Deleted, the shipped figures stand again.
    assert remove(jane, "Asmpt", mine).status_code == 200
    got = jane.get("/ui/api/assumptions").json()
    assert got["id"] is None and got["figures"]["classes"]["usStocks"]["return"] == 7.0


US = "classes.usStocks"


@pytest.mark.parametrize(
    ("path", "value", "words"),
    [
        (f"{US}.return", None, "Between −50% and 100%."),
        (f"{US}.return", "7", "Between −50% and 100%."),
        (f"{US}.return", True, "Between −50% and 100%."),
        (f"{US}.return", -51, "Between −50% and 100%."),
        (f"{US}.return", float("nan"), "Between −50% and 100%."),
        (f"{US}.volatility", 201, "Between 0% and 200%."),
        (f"{US}.volatility", False, "Between 0% and 200%."),
        ("inflation", -1, "Between 0% and 20%."),
        ("inflation", True, "Between 0% and 20%."),
        ("educationInflation", "5", "Between 0% and 20%."),
        ("bitcoinModel", "moon", "Choose a model."),
    ],
)
def test_each_assumption_is_refused_at_its_field(jane, path, value, words):
    """S6.3, R3.11: a figure that isn't a number in its range, a yes or no among them, is
    refused at its field, never read as a figure."""
    import copy

    figures = copy.deepcopy(jane.get("/ui/api/assumptions").json()["figures"])
    *group, key = path.split(".")
    at = figures
    for part in group:
        at = at[part]
    at[key] = value
    op = {"op": "create", "entity": "Asmpt", "id": new_id("Asmpt"), "fields": {"figures": figures}}
    r = jane.post("/ui/api/save", json={"ops": [op]})
    assert r.status_code == 422, r.text
    assert [(e["field"], e["code"], e["message"]) for e in r.json()["errors"]] == [
        (f"figures.{path}", "assumption-invalid", words)
    ]


def test_ones_own_assumptions_are_made_once_and_only_by_them(server, jane):
    """S6.3: a user's own figures are one record: a second is refused, and another user's is
    not found to them."""
    figures = jane.get("/ui/api/assumptions").json()["figures"]
    op = {"op": "create", "entity": "Asmpt", "id": new_id("Asmpt"), "fields": {"figures": figures}}
    mine = saved(jane.post("/ui/api/save", json={"ops": [op]}))
    again = {**op, "id": new_id("Asmpt")}
    r = jane.post("/ui/api/save", json={"ops": [again]})
    assert r.status_code == 409 and r.json()["errors"][0]["code"] == "assumptions-exist"
    make_user(server, "john")
    r = change(sign_in(server, "john"), "Asmpt", mine, figures=figures)
    assert r.status_code == 404
    r = change(jane, "Asmpt", {**mine, "id": new_id("Asmpt")}, figures=figures)
    assert r.status_code == 404
    changed = saved(change(jane, "Asmpt", mine, figures={**figures, "inflation": 3.5}))
    assert changed["figures"]["inflation"] == 3.5
    assert jane.get("/ui/api/assumptions").json()["figures"]["inflation"] == 3.5


def test_assumptions_saved_in_part_keep_the_shipped_rest(server, jane):
    """What is kept is laid over the shipped figures: a class or a figure not kept is the
    shipped one; one MoolaKata has no row for is passed over."""
    from moolakata.projections import assumptions

    uid = jane.get("/ui/api/session").json()["user"]["id"]
    with server.db.tx(unscoped="test: assumptions kept in part") as s:
        assumptions.save(s, uid, {"classes": {"bonds": {"return": 5.5}}})
        assumptions.save(s, uid, {"classes": {"bonds": {"return": 4.5}, "gold": {"return": 9}},
                                  "inflation": 3.0})  # fmt: skip
        got = assumptions.load(s, uid)
    assert got["classes"]["bonds"] == {"return": 4.5, "volatility": 6.0}
    assert "gold" not in got["classes"]
    assert (got["inflation"], got["educationInflation"]) == (3.0, 5.0)


def test_bitcoin_models_compare(server, jane):
    from test_account_world import _closes_installed
    from test_projection_edges import _bitcoin

    _bitcoin(server)
    with _closes_installed():
        rows = {r["model"]: r for r in jane.get("/ui/api/bitcoin-models").json()["rows"]}
    assert set(rows) == {"powerLaw", "logRegression", "stockToFlow", "saylor", "ark"}
    assert rows["ark"]["at"]["2030"] == pytest.approx(1_200_000, rel=0.01)
    assert rows["saylor"]["at"]["2045"] == pytest.approx(13_000_000, rel=0.01)
    assert "stake" in rows["saylor"]["record"] or "holds" in rows["saylor"]["record"]


def test_tax_tables_ship_and_can_be_corrected(server, frozen, admin_client):
    t = admin_client.get("/ui/api/settings/tax-tables").json()
    assert t["year"] == 2026
    ira = next(r for r in t["rows"] if r["key"] == "iraLimit")
    assert ira["value"] == 7500 and not ira["corrected"]
    fig = {"year": 2026, "key": "iraLimit", "value": 8000}
    op = {"op": "create", "entity": "TaxFg", "id": new_id("TaxFg"), "fields": fig}
    t = saved(admin_client.post("/ui/api/save", json={"ops": [op]}))
    ira = next(x for x in t["rows"] if x["key"] == "iraLimit")
    assert ira["corrected"] and ira["value"] == 8000
    bad = {"year": 2026, "key": "btcArk2030", "value": [1, 2]}
    op = {"op": "create", "entity": "TaxFg", "id": new_id("TaxFg"), "fields": bad}
    assert admin_client.post("/ui/api/save", json={"ops": [op]}).status_code == 422
    # The shipped value is no correction; deleting the correction puts it back.
    correction = {"id": ira["figureId"], "version": ira["version"]}
    r = change(admin_client, "TaxFg", correction, value=7500)
    assert r.json()["errors"][0]["code"] == "figure-shipped"
    assert remove(admin_client, "TaxFg", correction).status_code == 200
    t = admin_client.get("/ui/api/settings/tax-tables").json()
    assert not next(x for x in t["rows"] if x["key"] == "iraLimit")["corrected"]


def test_a_bitcoin_model_with_cases_gives_three_paths(server, jane):
    from test_account_world import _closes_installed
    from test_projection_edges import _bitcoin

    _bitcoin(server)
    p = retirement(jane, bitcoinModel="ark")
    # A typed amount with some crypto in it.
    typed = {"kind": "typed", "amount": 100000, "allocation": {"usStocks": 80, "crypto": 20}}
    with _closes_installed():
        sc = saved(change(jane, "Prjct", p, builtOn=typed))["result"]["scenarios"]
    assert set(sc) == {"bear", "base", "bull"}
    assert sc["bear"][-1] < sc["base"][-1] < sc["bull"][-1]


def test_engine_withdrawals_run_the_money_out():
    plan = engine.Plan(
        start=100000,
        weights={"cash": 1.0},
        returns={"cash": 0.0},
        vols={"cash": 0.0},
        inflation=0.0,
        fees=0.0,
        first_year=2026,
        years=12,
        withdraw_from=1,
        withdrawal={"method": "fixed", "amount": 20000},
    )
    r = engine.run(plan)
    assert r.lasted == 0.0 and r.percentiles[50][5] == 0.0 and r.percentiles[50][4] == 20000


def test_a_bitcoin_model_drives_the_bitcoin_only():
    # Of the crypto, the model drives the bitcoin's part; other coins keep the crypto
    # assumption.
    base = dict(
        start=100_000.0,
        weights={"crypto": 1.0},
        returns={"crypto": 0.0},
        vols={"crypto": 0.0},
        inflation=0.0,
        fees=0.0,
        first_year=2026,
        years=2,
        crypto_path=[2.0, 2.0],
    )
    all_btc = engine._expected_return(engine.Plan(**base, bitcoin_share=1.0))
    half = engine._expected_return(engine.Plan(**base, bitcoin_share=0.5))
    assert list(all_btc) == [1.0, 1.0] and list(half) == [0.5, 0.5]


def test_every_year_a_book_may_cover_has_its_own_figures(admin_client):
    # A book ten years back takes that year's figures, never 2025's; a past year lists
    # its tax figures only.
    t = admin_client.get("/ui/api/settings/tax-tables", params={"year": 2016}).json()
    assert t["year"] == 2016 and 2016 in t["years"]
    rows = {r["key"]: r["value"] for r in t["rows"]}
    assert rows["iraLimit"] == 5500 and rows["giftExclusion"] == 14000
    assert "collegePublic" not in rows and "btcArk2030" not in rows
    fig = {"year": 2016, "key": "collegePublic", "value": 1}
    op = {"op": "create", "entity": "TaxFg", "id": new_id("TaxFg"), "fields": fig}
    r = admin_client.post("/ui/api/save", json={"ops": [op]})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "figure-not-of-year"


def test_the_tracking_floor_is_a_minimum_width():
    # A narrow band widens to 2% of its median; a wide one is left as it is.
    from moolakata.projections import widened

    D = Decimal
    assert widened(D(100), D(100), D(100)) == (D(98), D(100), D(102))
    assert widened(D(80), D(100), D(120)) == (D(80), D(100), D(120))


def test_the_years_a_projection_runs_are_bounded(jane):
    # A birth year centuries back, or a date a thousand years on, would stall the server.
    r = make(
        jane,
        "Prjct",
        name="Far",
        goal="retirement",
        builtOn={"kind": "typed", "amount": "1000"},
        inputs={
            "people": [{"birthYear": 1000}, {"birthYear": 1980}, {"birthYear": 1990}],
            "income": [{"fromAge": 900, "monthly": 10}],
            "date": "3026-01-01",
            "firstYear": 9999,
        },
    )
    assert r.status_code == 422
    assert {e["field"] for e in r.json()["errors"]} >= {
        "inputs.people",
        "inputs.income.0.fromAge",
        "inputs.date",
        "inputs.firstYear",
    }
    r = make(
        jane,
        "Prjct",
        name="Old",
        goal="retirement",
        builtOn={"kind": "typed", "amount": "1000"},
        inputs={"people": [{"birthYear": 1800}]},
    )
    assert "inputs.people.0.birthYear" in {e["field"] for e in r.json()["errors"]}


def test_a_viewer_tracks_only_the_accounts_shared_with_them(server, jane):
    # S6.1: the projection's results, and the balance of only the accounts they can see.
    shared = new_account(jane, name="Joint savings", type="savings")
    own = new_account(jane, name="Jane's savings", type="savings")
    add(jane, shared["id"], "1000.00", "2026-10-01")
    add(jane, own["id"], "9000.00", "2026-10-01")
    r = make(
        jane,
        "Prjct",
        name="House",
        goal="savings",
        builtOn={"kind": "accounts", "ids": [shared["id"], own["id"]]},
        inputs={"target": 50000, "date": "2030-01-01", "monthly": 500, "fees": 0.1},
    )
    pid = r.json()["id"]
    jane.post(f"/ui/api/projections/{pid}/activate")
    john = make_user(server, "john")
    for kind, item in (("projection", pid), ("account", shared["id"])):
        r = share(jane, kind, item, users={john.id: "read"})
        assert r.status_code == 200, r.text
    mine = jane.get(f"/ui/api/projections/{pid}").json()["tracking"]
    assert mine["band"] and Decimal(str(mine["points"][-1][1])) == 10000
    theirs = sign_in(server, "john").get(f"/ui/api/projections/{pid}").json()["tracking"]
    assert theirs["partial"] and theirs["band"] == [] and theirs["status"] == mine["status"]
    assert Decimal(str(theirs["points"][-1][1])) == 1000, "only the joint account's balance"


@pytest.mark.parametrize("kind", ["portfolio", "accounts"])
def test_one_shared_a_projection_sees_its_results_over_what_it_is_built_on(server, jane, kind):
    # S6.1: its results are the projection's, worked out over its owner's accounts, though
    # what it is built on isn't shared with them; named as not shared, never by its name.
    own = new_account(jane, name="Jane's savings", type="savings")
    add(jane, own["id"], "9000.00", "2026-10-01")
    built = {"kind": "accounts", "ids": [own["id"]]}
    if kind == "portfolio":
        port = make(jane, "Portf", name="Jane's nest egg", accountIds=[own["id"]])
        assert port.status_code == 200, port.text
        built = {"kind": "portfolio", "id": port.json()["id"]}
    r = make(jane, "Prjct", name="House", goal="savings", builtOn=built,
             inputs={"target": 50000, "date": "2030-01-01", "monthly": 500,
                     "fees": 0.1})  # fmt: skip
    pid = r.json()["id"]
    john = make_user(server, "john")
    assert share(jane, "projection", pid, users={john.id: "read"}).status_code == 200
    mine = jane.get(f"/ui/api/projections/{pid}").json()
    johns = sign_in(server, "john")
    (row,) = johns.get("/ui/api/projections").json()["items"]
    theirs = johns.get(f"/ui/api/projections/{pid}").json()
    assert theirs["result"]["start"] == mine["result"]["start"] == Decimal("9000.00")
    assert theirs["result"]["percentiles"] == mine["result"]["percentiles"]
    assert mine["builtOnLabel"] in ("Portfolio: Jane's nest egg", "Jane's savings")
    what = "a portfolio" if kind == "portfolio" else "an account"
    assert row["builtOnLabel"] == theirs["builtOnLabel"] == f"{what} not shared with you"
    # Shared with them, it is named as its owner names it: the portfolio, though its one
    # account isn't shared with them; the account.
    item = ("portfolio", built["id"]) if kind == "portfolio" else ("account", own["id"])
    assert share(jane, *item, users={john.id: "read"}).status_code == 200
    seen = johns.get(f"/ui/api/projections/{pid}").json()
    assert seen["builtOnLabel"] == mine["builtOnLabel"]


def test_a_shared_projection_shows_on_a_dashboard_when_its_receiver_asks(server, jane):
    # S6.8.3: a set of the receiver's own record, through the save.
    p = retirement(jane)
    jane.post(f"/ui/api/projections/{p['id']}/activate")
    john_user = make_user(server, "john")
    assert share(jane, "projection", p["id"], users={john_user.id: "read"}).status_code == 200
    john = sign_in(server, "john")
    assert john.get(f"/ui/api/projections/{p['id']}").json()["shown"] is False
    me = john.get("/ui/api/profile").json()
    saved(change(john, "User", me, shownProjectionIds=[p["id"]]))
    assert john.get(f"/ui/api/projections/{p['id']}").json()["shown"] is True
    assert john.get("/ui/api/profile").json()["shownProjectionIds"] == [p["id"]]
    me = jane.get("/ui/api/profile").json()
    r = change(jane, "User", me, shownProjectionIds=[p["id"]])
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "owner-sees-it"
    # Hidden again, then shown again: the one row, taken up again.
    me = saved(change(john, "User", john.get("/ui/api/profile").json(), shownProjectionIds=[]))
    assert me["shownProjectionIds"] == []
    assert john.get(f"/ui/api/projections/{p['id']}").json()["shown"] is False
    me = saved(change(john, "User", me, shownProjectionIds=[p["id"]]))
    assert me["shownProjectionIds"] == [p["id"]]
    # One not shared with them is refused at its field.
    r = change(john, "User", me, shownProjectionIds=["Prjct_00000000000000000000000000"])
    assert r.status_code == 422
    (e,) = r.json()["errors"]
    assert (e["field"], e["code"], e["message"]) == (
        "shownProjectionIds",
        "projection-unknown",
        "A projection shared with you.",
    )


# ---------- the saving that reaches a target (S6.4.2.4)


def _plan(start: float, days: int) -> tuple[engine.Plan, int]:
    """A savings plan to a date `days` away, as `prepare` makes one: the last year counts
    its part."""
    import math

    span = days / 365.25
    idx = max(1, math.ceil(span))
    plan = engine.Plan(start=start, weights={"usStocks": 0.6, "cash": 0.4},
                       returns={"usStocks": 0.07, "cash": 0.03},
                       vols={"usStocks": 0.16, "cash": 0.01}, inflation=0.025, fees=0.001,
                       first_year=2026, years=idx + 1, contribute_years=idx,
                       last_part=span - (idx - 1), seed=7)  # fmt: skip
    return plan, idx


def _reaches(plan: engine.Plan, target: float, idx: int, chance: float, saving: float) -> bool:
    """Whether a yearly saving reaches the target, on the runs `needed_saving` draws."""
    import numpy as np

    trial = engine.Plan(**{**plan.__dict__, "runs": 400})
    rets = engine._returns(trial, np.random.default_rng(plan.seed), trial.runs)
    path, _ = engine._simulate(engine.Plan(**{**trial.__dict__, "contribution": saving}), rets)
    return bool((path[:, idx] >= target).mean() >= chance)


@pytest.mark.parametrize("days", [10, 91, 182, 365, 366, 913, 2190])
@pytest.mark.parametrize("start", [0.0, 4_000.0, 13_000.0])
@pytest.mark.parametrize("chance", [0.9, 0.5])
def test_the_saving_named_reaches_the_target_and_a_dollar_less_doesnt(days, start, chance):
    """Every case of one kind of bug: a search that assumed its bound was enough. Across dates
    (days, months, a year either side of one, years), starts (nothing, part, past the target) and
    both chances asked (savings 90%, education 50%), the saving named is the least that reaches the
    target, to the dollar a year."""
    plan, idx = _plan(start, days)
    target = 12_000.0
    got = engine.needed_saving(plan, target, idx, chance)
    assert got is not None
    if _reaches(plan, target, idx, chance, 0.0):
        assert got == 0.0
    else:
        assert _reaches(plan, target, idx, chance, got)
        assert not _reaches(plan, target, idx, chance, got - engine.PRECISION)


def test_no_saving_changes_todays_balance_and_the_search_has_an_end(monkeypatch):
    plan, idx = _plan(0.0, 91)
    assert engine.needed_saving(plan, 12_000.0, 0) is None, "a date of today"
    monkeypatch.setattr(engine, "DOUBLINGS", 3)
    assert engine.needed_saving(plan, 12_000.0, idx) is None, "past what the search goes to"


def test_a_target_months_away_names_a_saving_that_reaches_it(jane):
    """A target under a year: $12,000 by Apr 13, 2027 from nothing, in cash: the saving named
    reaches it, where $1,000 a month (a bound assumed enough) reaches half."""
    inputs = {"target": 12000, "date": "2027-04-13", "monthly": 1000, "fees": 0.1}
    built = {"kind": "typed", "amount": 0, "allocation": {"cash": 100}}
    r = make(jane, "Prjct", name="Car", goal="savings", builtOn=built, inputs=inputs)
    assert r.status_code == 200, r.text
    a = r.json()["result"]["answer"]
    assert a["chance"] == 0 and 1_950 < a["neededMonthly"] < 2_100
    inputs["monthly"] = a["neededMonthly"]
    again = saved(change(jane, "Prjct", r.json(), inputs=inputs))
    assert again["result"]["answer"]["chance"] >= 0.9


def test_an_answer_no_saving_reaches_says_so(jane, monkeypatch):
    monkeypatch.setattr(engine, "DOUBLINGS", 0)
    inputs = {"target": 12000, "date": "2027-04-13", "monthly": 0, "fees": 0.1}
    built = {"kind": "typed", "amount": 0, "allocation": {"cash": 100}}
    r = make(jane, "Prjct", name="Car", goal="savings", builtOn=built, inputs=inputs)
    assert r.status_code == 200, r.text
    assert r.json()["result"]["answer"]["neededMonthly"] is None


def test_a_saving_that_stops_mid_year_counts_its_part_and_rises_each_year():
    """The model's savings in a year (S6.4): a year's contribution rising by its growth, the last
    year of saving counting its part (school's start). No returns, no fees."""
    plan = engine.Plan(start=0.0, weights={"cash": 1.0}, returns={"cash": 0.0},
                       vols={"cash": 0.0}, inflation=0.0, fees=0.0, first_year=2026, years=4,
                       contribution=1000.0, contribution_growth=0.1, contribute_years=2,
                       contribute_part=0.25)  # fmt: skip
    path, _ = engine._simulate(plan, engine._expected_return(plan)[None, :])
    assert path[0].tolist() == pytest.approx([0.0, 1000.0, 1000.0 + 1100.0 * 0.25, 1275.0])


def _flat(start: float) -> tuple[engine.Plan, int]:
    """A plan with no returns, fees or spread: what is saved is what there is."""
    return engine.Plan(start=start, weights={"cash": 1.0}, returns={"cash": 0.0},
                       vols={"cash": 0.0}, inflation=0.0, fees=0.0, first_year=2026, years=2,
                       contribute_years=1), 1  # fmt: skip


def test_a_target_met_exactly_needs_nothing_and_a_quarter_short_needs_a_quarter(monkeypatch):
    plan, idx = _flat(1_000.0)
    assert engine.needed_saving(plan, 1_000.0, idx) == 0.0, "exactly at the target reaches it"
    monkeypatch.setattr(engine, "PRECISION", 0.01)
    plan, idx = _flat(999.75)
    assert engine.needed_saving(plan, 1_000.0, idx) == pytest.approx(0.25, abs=0.01)


def test_a_target_under_a_year_away_is_one_part_year(server, jane):
    """A savings date months away is the projection's first year, counting its part (S6.4.2.1)."""
    from moolakata import projections
    from moolakata.store.entities.projections import Projection

    inputs = {"target": 12000, "date": "2027-04-13", "monthly": 1000, "fees": 0.1}
    built = {"kind": "typed", "amount": 0, "allocation": {"cash": 100}}
    p = make(jane, "Prjct", name="Car", goal="savings", builtOn=built, inputs=inputs).json()
    with server.db.read(unscoped="test") as s:
        row = s.get(Projection, p["id"])
        prep = projections.prepare(s, row, row.ownerId)
    days = (dt.date(2027, 4, 13) - T0.date()).days
    assert prep.target_index == 1 and prep.plan.years == 2
    assert prep.plan.last_part == pytest.approx(days / 365.25)
