"""529 plans (requirements S1.8), the people they are for (S7.7), and the education goal
(S6.2.2)."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import attach, change, detach, make, new_id, plan529, remove, saved
from test_accounts import add, new_account

from moolakata import clock

T0 = dt.datetime(2026, 10, 13, 12, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


@pytest.fixture
def alice(server, frozen):
    make_user(server, "alice")
    return sign_in(server, "alice")


def plan(c, **kw):
    made = make(
        c, "GfPln", name="Emma Griffin", sex="female", birthYear=2018, birthMonth=10, birthDay=20
    ).json()
    emma = c.get(f"/ui/api/persons/{made['personId']}").json()
    acct = new_account(c, name="Emma's 529", type="529", institution="my529")
    r = plan529(c, acct["id"], planState="Utah", planName="my529", beneficiaryId=emma["id"],
                openedOn=kw.get("opened", "2018-05-02"), stateDeduction="2410")  # fmt: skip
    return acct, emma, saved(r)


def test_gift_plans_are_their_owners_alone(server, alice):
    make(alice, "GfPln", name="Emma", sex="female", birthYear=2018)
    make_user(server, "bob")
    bob = sign_in(server, "bob")
    assert bob.get("/ui/api/gift-plans").json()["items"] == []
    assert "Emma" in {p["name"] for p in bob.get("/ui/api/persons").json()["items"]}
    bad = make(alice, "GfPln", name=" ", birthMonth=13)
    assert {e["field"] for e in bad.json()["errors"]} >= {"name", "sex", "birthMonth"}


def test_the_plan_and_its_beneficiary(alice):
    acct, emma, p = plan(alice)
    assert p["beneficiary"] == {
        "kind": "person",
        "id": emma["id"],
        "name": "Emma Griffin",
        "birthYear": 2018,
        "deleted": False,
    }
    assert p["planState"] == "Utah" and p["stateDeduction"] == "2410.00"
    assert p["rollover"]["possibleFrom"] == "2033-05-02" and p["rollover"]["limit"] == "35000.00"
    a = alice.get(f"/ui/api/accounts/{acct['id']}").json()
    assert a["group"] == "education" and a["investing"]


def test_contributions_against_the_gift_exclusion(server, alice):
    acct, _, _ = plan(alice)
    gran = {"id": make(alice, "GfPln", name="Margaret Griffin", sex="female").json()["personId"]}
    bank = new_account(alice, name="Checking")
    add(alice, bank["id"], "20000.00", "2026-01-02")
    r = make(
        alice,
        "Cntrb",
        accountId=acct["id"],
        date="2026-02-01",
        amount="6000",
        fromAccountId=bank["id"],
    )
    assert r.status_code == 200, r.text
    assert alice.get(f"/ui/api/accounts/{bank['id']}").json()["balance"] == "14000.00"
    make(
        alice,
        "Cntrb",
        accountId=acct["id"],
        date="2024-03-01",
        amount="90000",
        contributor=f"person:{gran['id']}",
        fiveYear=True,
    )
    make(
        alice,
        "Cntrb",
        accountId=acct["id"],
        date="2026-06-01",
        amount="2500",
        contributor=f"person:{gran['id']}",
    )
    v = alice.get(f"/ui/api/accounts/{acct['id']}/contributions").json()
    years = {(y["name"], y["year"]): y for y in v["years"]}
    g24 = years[("Margaret Griffin", 2024)]
    assert g24["counted"] == "18000.00" and g24["fromElection"] == 2024 and not g24["over"]
    g26 = years[("Margaret Griffin", 2026)]
    assert g26["counted"] == "20500.00" and g26["over"], "18,000 of the election and 2,500 more"
    assert ("Margaret Griffin", 2028) in years and ("Margaret Griffin", 2029) not in years
    owner = next(y for y in v["years"] if y["contributor"] == "owner" and y["year"] == 2026)
    assert owner["counted"] == "6000.00" and not owner["over"]
    # An imported deposit is tagged afterwards.
    t = add(alice, acct["id"], "1000.00", "2026-09-01")
    tag = {"accountId": acct["id"], "transactionId": t["id"], "contributor": f"person:{gran['id']}"}
    r = alice.post(
        "/ui/api/save",
        json={"ops": [{"op": "create", "entity": "Cntrb", "id": new_id("Cntrb"), "fields": tag}]},
    )
    assert saved(r)["name"] == "Margaret Griffin"
    # Told again, it was the owner's; its deposit can't change from here.
    mine = saved(change(alice, "Cntrb", saved(r), contributor="owner"))
    assert mine["contributor"] == "owner"
    r = change(alice, "Cntrb", mine, amount="5")
    assert r.json()["errors"][0]["code"] == "contribution-fixed"


def test_withdrawals_against_qualified_expenses(alice):
    acct, _, _ = plan(alice)
    add(alice, acct["id"], "50000.00", "2025-01-02")
    add(alice, acct["id"], "-46000.00", "2026-08-20")
    r = make(
        alice,
        "QExpn",
        accountId=acct["id"],
        date="2026-08-15",
        kind="tuition",
        description="Fall tuition",
        amount="44200",
    )
    assert r.status_code == 200, r.text
    y = alice.get(f"/ui/api/accounts/{acct['id']}/withdrawals").json()["years"][0]
    assert (y["year"], y["distributions"], y["expenses"], y["notCovered"]) == (
        2026,
        "46000.00",
        "44200.00",
        "1800.00",
    )
    bad = make(alice, "QExpn", accountId=acct["id"], date="2026-08-15", kind="car", amount="1")
    assert bad.status_code == 422
    e = alice.get(f"/ui/api/accounts/{acct['id']}/withdrawals").json()["expenses"][0]
    # Its receipt, kept with it as a link the save makes (S1.8.3, S9.3), and taken away.
    rid = alice.post(
        "/ui/api/receipts", files={"file": ("bill.pdf", b"%PDF-1.4 bill", "application/pdf")}
    ).json()["id"]
    assert saved(attach(alice, rid, e["id"], "expense"))["kind"] == "expense"
    e = alice.get(f"/ui/api/accounts/{acct['id']}/withdrawals").json()["expenses"][0]
    assert [d["id"] for d in e["documents"]] == [rid]
    assert detach(alice, rid, e["id"]).status_code == 200
    e = alice.get(f"/ui/api/accounts/{acct['id']}/withdrawals").json()["expenses"][0]
    assert e["documents"] == []
    assert remove(alice, "QExpn", e).status_code == 200
    assert alice.get(f"/ui/api/accounts/{acct['id']}/withdrawals").json()["expenses"] == []


def test_the_roth_rollover_after_fifteen_years(alice):
    acct, _, _ = plan(alice, opened="2010-05-01")
    add(alice, acct["id"], "20000.00", "2012-01-02")
    add(alice, acct["id"], "9000.00", "2024-01-02")
    p = alice.get(f"/ui/api/accounts/{acct['id']}/plan529").json()["rollover"]
    assert p["possibleFrom"] == "2025-05-01"
    assert p["eligible"] == "20000.00" and p["available"] == "20000.00"


def test_the_goal_tab_starts_an_education_projection(alice):
    acct, _, _ = plan(alice)
    add(alice, acct["id"], "48000.00", "2023-06-01")
    assert alice.get(f"/ui/api/accounts/{acct['id']}/goal").json()["projection"] is None
    r = alice.post(f"/ui/api/accounts/{acct['id']}/goal")
    assert r.status_code == 201, r.text
    p = r.json()["projection"]
    a = p["result"]["answer"]
    assert a["kind"] == "education" and a["firstYear"] == 2036 and a["years"] == 4
    assert a["costToday"] == 27100 and 0 < a["funded"] <= 100
    assert a["funded"] < 100 and a["neededMonthly"] > 0
    assert p["headline"].endswith("funded for Emma Griffin's 4 years")
    # More saved each month funds more of it.
    more = saved(change(alice, "Prjct", p, inputs={**p["inputs"], "monthly": 2000}))
    assert more["result"]["answer"]["funded"] > a["funded"]
    again = alice.get(f"/ui/api/accounts/{acct['id']}/goal").json()
    assert again["projection"]["id"] == p["id"]
    bad = make(
        alice,
        "Prjct",
        name="X",
        goal="education",
        builtOn={"kind": "typed", "amount": 1},
        inputs={"beneficiary": {"kind": "person", "id": "Persn_nope"}},
    )
    assert bad.json()["errors"][0]["field"] == "inputs.beneficiary"


@pytest.mark.parametrize(
    ("first_year", "low", "high"),
    [
        # Today is Oct 13, 2026. School this year has started: nothing saved now reaches it.
        (2026, 0, 0),
        # Next year: the 10.6 months to Sep 1, 2027, saved at $1,000 a month.
        (2027, 10_400, 10_800),
        # Three years on: two whole years and the same part, grown.
        (2029, 34_000, 37_500),
    ],
)
def test_saving_counts_until_school_starts_on_sep_1(alice, first_year, low, high):
    """S6.2.2: the balance when school starts counts every month saved before Sep 1 of its
    first year; it counted whole years ending a year before school, so a school next year saw
    no saving at all."""
    acct, _, _ = plan(alice)
    p = alice.post(f"/ui/api/accounts/{acct['id']}/goal").json()["projection"]
    p = saved(change(alice, "Prjct", p, inputs={**p["inputs"], "firstYear": first_year,
                                                "monthly": 1000}))  # fmt: skip
    a = p["result"]["answer"]
    assert low <= a["atStart"] <= high, a["atStart"]
    if first_year == 2026:
        assert a["neededMonthly"] is None, "no monthly saving reaches it by then"
    else:
        # Saving what it names funds it: the median at the start meets what is needed.
        p = saved(change(alice, "Prjct", p, inputs={**p["inputs"],
                                                    "monthly": a["neededMonthly"]}))  # fmt: skip
        assert p["result"]["answer"]["funded"] >= 97


def _prepared(server, alice, today: dt.date, first_year: int):
    """The education plan `prepare` makes for school starting `first_year`, on `today`."""
    from moolakata import projections
    from moolakata.store.entities.projections import Projection

    acct, _, _ = plan(alice)
    p = alice.post(f"/ui/api/accounts/{acct['id']}/goal").json()["projection"]
    p = saved(change(alice, "Prjct", p, inputs={**p["inputs"], "firstYear": first_year,
                                                "schoolYears": 4}))  # fmt: skip
    clock.fix(dt.datetime.combine(today, dt.time(12), tzinfo=dt.UTC))
    with server.db.read(unscoped="test") as s:
        row = s.get(Projection, p["id"])
        return projections.prepare(s, row, row.ownerId)


@pytest.mark.parametrize(
    ("today", "first_year", "index", "part"),
    [
        (dt.date(2026, 10, 13), 2027, 1, "span"),  # next year: the months to Sep 1
        (dt.date(2027, 8, 31), 2027, 1, "span"),  # the day before: one day's saving
        (dt.date(2027, 9, 1), 2027, 1, 0.0),  # the day it starts: under way, nothing
        (dt.date(2026, 10, 13), 2029, 3, "span"),  # two whole years and the part
        (dt.date(2026, 10, 13), 2123, 97, "span"),  # the last year a projection runs to
        (dt.date(2026, 10, 13), 2124, 97, 1.0),  # past it: the projection's last 100 years
    ],
)
def test_school_starts_on_sep_1_and_saving_counts_until_then(
    server, alice, today, first_year, index, part
):
    """S6.2.2, CR3-31: saving goes on until Sep 1 of school's first year, its last year counting
    the part before then; a projection runs at most 100 years on, school's 4 among them."""
    if part == "span":  # the days to Sep 1, in years, less the whole years before
        part = (dt.date(first_year, 9, 1) - today).days / 365.25 - (index - 1)
    prep = _prepared(server, alice, today, first_year)
    assert prep.target_index == index and prep.start_part == pytest.approx(part, abs=1e-9)
    plan = prep.plan
    assert (plan.contribute_years, plan.years) == (index, index + 4)
    assert plan.contribute_part == pytest.approx(part, abs=1e-9)


def test_a_fully_funded_school_needs_no_more_saving(alice):
    acct, _, _ = plan(alice)
    add(alice, acct["id"], "900000.00", "2023-06-01")
    a = alice.post(f"/ui/api/accounts/{acct['id']}/goal").json()["projection"]["result"]["answer"]
    assert a["funded"] == 100 and a["neededMonthly"] == 0.0


def test_the_saving_named_funds_school_at_the_median(alice, monkeypatch):
    """Funds it fully means the median balance meets the cost (S6.2.2): the search asks for a
    50% chance; and when no saving reaches it, the answer says so."""
    from moolakata.projections import engine

    asked = []
    real = engine.needed_saving

    def spy(*args, **kw):
        asked.append(kw.get("chance", 0.9))
        return real(*args, **kw)

    monkeypatch.setattr(engine, "needed_saving", spy)
    acct, _, _ = plan(alice)
    p = alice.post(f"/ui/api/accounts/{acct['id']}/goal").json()["projection"]
    assert asked == [0.5] and p["result"]["answer"]["neededMonthly"] > 0
    monkeypatch.setattr(engine, "DOUBLINGS", 0)
    p = saved(change(alice, "Prjct", p, inputs={**p["inputs"], "monthly": 10}))
    assert p["result"]["answer"]["neededMonthly"] is None
