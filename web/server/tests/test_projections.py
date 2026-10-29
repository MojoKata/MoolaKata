"""Projections and assumptions (requirements S6.1–S6.9) and the tax tables (S16.11)."""

import datetime as dt
from decimal import Decimal

import pytest
from conftest import make_user, sign_in
from edits import change, new_id, remove, saved, share
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
def alice(server, frozen):
    make_user(server, "alice", born=1979)
    return sign_in(server, "alice")


def retirement(c, **inputs):
    body = {
        "name": "Retire at 62",
        "goal": "retirement",
        "builtOn": {"kind": "typed", "amount": 500000, "allocation": {"usStocks": 60, "bonds": 40}},
        "inputs": {
            "people": [{"name": "Alice", "birthYear": 1979, "retireAge": 62}],
            "contribution": {"amount": 30000, "growth": 3},
            "withdrawal": {"method": "fourPercent"},
            "income": [{"label": "Social Security", "person": 0, "fromAge": 67, "monthly": 2900}],
            **inputs,
        },
    }
    r = c.post("/ui/api/projections", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_the_same_inputs_give_the_same_figures(alice):
    p = retirement(alice)
    again = alice.get(f"/ui/api/projections/{p['id']}").json()
    assert again["result"]["percentiles"]["50"] == p["result"]["percentiles"]["50"]
    res = p["result"]
    assert res["years"][0] == 2026 and res["years"][-1] == 1979 + 95
    lo, mid, hi = (res["percentiles"][k][-10] for k in ("10", "50", "90"))
    assert lo <= mid <= hi
    assert 0 <= res["answer"]["chance"] <= 1 and res["answer"]["retireYear"] == 2041
    assert p["headline"].endswith("chance the money lasts to 95")


def test_retiring_later_makes_the_money_more_likely_to_last(alice):
    tight = {"withdrawal": {"method": "fixed", "amount": 90000}, "income": []}
    early = retirement(alice, people=[{"name": "A", "birthYear": 1979, "retireAge": 55}], **tight)
    late = retirement(alice, people=[{"name": "A", "birthYear": 1979, "retireAge": 67}], **tight)
    assert late["result"]["answer"]["chance"] > early["result"]["answer"]["chance"] + Decimal("0.2")


def test_a_savings_target_says_how_likely_and_what_would_do_it(alice):
    r = alice.post(
        "/ui/api/projections",
        json={
            "name": "House deposit",
            "goal": "savings",
            "builtOn": {"kind": "typed", "amount": 38200, "allocation": {"cash": 100}},
            "inputs": {"target": 60000, "date": "2028-10-01", "monthly": 300},
        },
    )
    assert r.status_code == 201, r.text
    a = r.json()["result"]["answer"]
    assert a["chance"] < 0.5, "300 a month falls short"
    assert 800 < a["neededMonthly"] < 1000


def test_inputs_are_checked(alice):
    r = alice.post(
        "/ui/api/projections",
        json={
            "name": "",
            "goal": "lottery",
            "builtOn": {"kind": "accounts", "ids": ["Acct_nope"]},
            "inputs": {"fees": 9, "date": "2001-01-01"},
        },
    )
    assert r.status_code == 422
    assert {e["field"] for e in r.json()["errors"]} >= {
        "name",
        "goal",
        "builtOn",
        "inputs.fees",
        "inputs.date",
    }


def test_built_on_accounts_starts_from_their_value(alice):
    acct = new_account(alice, name="Savings", type="savings")
    add(alice, acct["id"], "12000.00", "2026-10-01")
    r = alice.post(
        "/ui/api/projections",
        json={
            "name": "Car",
            "goal": "savings",
            "builtOn": {"kind": "accounts", "ids": [acct["id"]]},
            "inputs": {"target": 20000, "date": "2028-01-01", "monthly": 250},
        },
    )
    res = r.json()["result"]
    assert res["start"] == 12000.0 and res["weights"] == {"cash": 1.0}
    assert r.json()["builtOnLabel"] == "Savings"


def test_one_active_plan_per_subject_and_its_baseline(alice):
    a = retirement(alice)
    b = retirement(alice, contribution={"amount": 40000, "growth": 3})
    assert alice.post(f"/ui/api/projections/{a['id']}/activate").json() == {"replaced": None}
    assert alice.post(f"/ui/api/projections/{b['id']}/activate").json() == {
        "replaced": "Retire at 62"
    }
    rows = {p["id"]: p for p in alice.get("/ui/api/projections").json()["items"]}
    assert rows[b["id"]]["active"] and not rows[a["id"]]["active"]
    got = alice.get(f"/ui/api/projections/{b['id']}").json()
    assert got["tracking"]["status"] == "untracked", "a typed amount has nothing to track"
    # Changing inputs keeps the baseline unless asked to re-baseline.
    base = got["result"]["percentiles"]["50"]
    r = change(alice, "Prjct", got, inputs={**got["inputs"], "fees": 1.0})
    assert saved(r)["result"]["percentiles"]["50"] != base
    assert saved(r)["baselineAt"] == got["baselineAt"]
    clock.fix(dt.datetime(2026, 10, 13, 12, 5, tzinfo=dt.UTC))
    r = change(alice, "Prjct", saved(r), inputs={**got["inputs"], "fees": 0.5}, rebaseline=True)
    assert saved(r)["baselineAt"] == "2026-10-13T12:05:00Z"
    assert change(alice, "Prjct", saved(r), goal="education").json()["errors"][0]["code"] == (
        "goal-fixed"
    )


def test_tracking_against_the_band_and_the_alert_when_behind(server, alice):
    acct = new_account(alice, name="Brokerage cash", type="savings")
    add(alice, acct["id"], "100000.00", "2026-10-01")
    r = alice.post(
        "/ui/api/projections",
        json={
            "name": "Nest egg",
            "goal": "savings",
            "builtOn": {"kind": "accounts", "ids": [acct["id"]]},
            "inputs": {"target": 150000, "date": "2030-01-01", "monthly": 500},
        },
    )
    pid = r.json()["id"]
    alice.post(f"/ui/api/projections/{pid}/activate")
    assert alice.get(f"/ui/api/projections/{pid}").json()["tracking"]["status"] == "on track"
    # Most of it is spent, and a month passes.
    add(alice, acct["id"], "-60000.00", "2026-10-20")
    clock.fix(dt.datetime(2026, 11, 3, 12, tzinfo=dt.UTC))
    alice2 = sign_in(server, "alice")
    assert alice2.get(f"/ui/api/projections/{pid}").json()["tracking"]["status"] == "behind"
    opened = alerts.evaluate(server)
    assert [a.kind for a in opened] == ["projection-behind"]
    plans = alice2.get("/ui/api/dashboard/plans").json()["items"]
    assert plans[0]["status"] == "behind" and plans[0]["actual"]


def test_assumptions_are_each_users_and_checked(alice):
    got = alice.get("/ui/api/assumptions").json()
    figures = got["figures"]
    assert figures["inflation"] == 2.5 and figures["classes"]["usStocks"]["return"] == 7.0
    figures["classes"]["usStocks"]["return"] = 6.0
    op = {"op": "create", "entity": "Asmpt", "id": new_id("Asmpt"), "fields": {"figures": figures}}
    mine = saved(alice.post("/ui/api/save", json={"ops": [op]}))
    assert mine["figures"]["classes"]["usStocks"]["return"] == 6.0
    r = change(alice, "Asmpt", mine, figures={**figures, "inflation": 40})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "figures.inflation"
    # Deleted, the shipped figures stand again.
    assert remove(alice, "Asmpt", mine).status_code == 200
    got = alice.get("/ui/api/assumptions").json()
    assert got["id"] is None and got["figures"]["classes"]["usStocks"]["return"] == 7.0


def test_bitcoin_models_compare(alice):
    rows = {r["model"]: r for r in alice.get("/ui/api/bitcoin-models").json()["rows"]}
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


def test_a_bitcoin_model_with_cases_gives_three_paths(server, alice):
    from moolakata import ids
    from moolakata.store.entities.accounts import Instrument

    with server.db.tx() as s:
        s.add(
            Instrument(
                id=ids.new_id("Instr"), symbol="BTC", name="Bitcoin", instrumentClass="crypto"
            )
        )
    p = retirement(
        alice,
        bitcoinModel="ark",
    )
    # A typed amount with some crypto in it.
    typed = {"kind": "typed", "amount": 100000, "allocation": {"usStocks": 80, "crypto": 20}}
    sc = saved(change(alice, "Prjct", p, builtOn=typed))["result"]["scenarios"]
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
    # B14: of the crypto, the model drives the bitcoin's part; other coins keep the crypto
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
    # B17: a book ten years back takes that year's figures, never 2025's; a past year lists
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
    # B22: a narrow band widens to 2% of its median; a wide one is left as it is.
    from moolakata.projections import widened

    D = Decimal
    assert widened(D(100), D(100), D(100)) == (D(98), D(100), D(102))
    assert widened(D(80), D(100), D(120)) == (D(80), D(100), D(120))


def test_the_years_a_projection_runs_are_bounded(alice):
    # A birth year centuries back, or a date a thousand years on, would stall the server.
    r = alice.post(
        "/ui/api/projections",
        json={
            "name": "Far",
            "goal": "retirement",
            "builtOn": {"kind": "typed", "amount": "1000"},
            "inputs": {
                "people": [{"birthYear": 1000}, {"birthYear": 1980}, {"birthYear": 1990}],
                "income": [{"fromAge": 900, "monthly": 10}],
                "date": "3026-01-01",
                "firstYear": 9999,
            },
        },
    )
    assert r.status_code == 422
    assert {e["field"] for e in r.json()["errors"]} >= {
        "inputs.people",
        "inputs.income.0.fromAge",
        "inputs.date",
        "inputs.firstYear",
    }
    r = alice.post(
        "/ui/api/projections",
        json={
            "name": "Old",
            "goal": "retirement",
            "builtOn": {"kind": "typed", "amount": "1000"},
            "inputs": {"people": [{"birthYear": 1800}]},
        },
    )
    assert r.json()["errors"][0]["field"] == "inputs.people.0.birthYear"


def test_a_viewer_tracks_only_the_accounts_shared_with_them(server, alice):
    # S6.1: the projection's results, and the balance of only the accounts they can see.
    shared = new_account(alice, name="Joint savings", type="savings")
    own = new_account(alice, name="Alice's savings", type="savings")
    add(alice, shared["id"], "1000.00", "2026-10-01")
    add(alice, own["id"], "9000.00", "2026-10-01")
    r = alice.post(
        "/ui/api/projections",
        json={
            "name": "House",
            "goal": "savings",
            "builtOn": {"kind": "accounts", "ids": [shared["id"], own["id"]]},
            "inputs": {"target": 50000, "date": "2030-01-01", "monthly": 500},
        },
    )
    pid = r.json()["id"]
    alice.post(f"/ui/api/projections/{pid}/activate")
    bob = make_user(server, "bob")
    for kind, item in (("projection", pid), ("account", shared["id"])):
        r = share(alice, kind, item, users={bob.id: "read"})
        assert r.status_code == 200, r.text
    mine = alice.get(f"/ui/api/projections/{pid}").json()["tracking"]
    assert mine["band"] and Decimal(str(mine["points"][-1][1])) == 10000
    theirs = sign_in(server, "bob").get(f"/ui/api/projections/{pid}").json()["tracking"]
    assert theirs["partial"] and theirs["band"] == [] and theirs["status"] == mine["status"]
    assert Decimal(str(theirs["points"][-1][1])) == 1000, "only the joint account's balance"
