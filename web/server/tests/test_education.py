"""529 plans (requirements S1.8), the people they are for (S7.7), and the education goal
(S6.2.2)."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import attach, change, detach, make, new_id, plan529, remove, saved, share
from test_accounts import add, new_account

from moolakata import clock

T0 = dt.datetime(2026, 10, 13, 12, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


@pytest.fixture
def jane(server, frozen):
    make_user(server, "jane")
    return sign_in(server, "jane")


def plan(c, **kw):
    made = make(
        c, "GfPln", name="Lisa Doe", sex="female", birthYear=2018, birthMonth=10, birthDay=20
    ).json()
    lisa = c.get(f"/ui/api/persons/{made['personId']}").json()
    acct = new_account(c, name="Lisa's 529", type="529", institution="my529")
    r = plan529(c, acct["id"], planState="Utah", planName="my529", beneficiaryId=lisa["id"],
                openedOn=kw.get("opened", "2018-05-02"), stateDeduction="2410")  # fmt: skip
    return acct, lisa, saved(r)


def test_gift_plans_are_their_owners_alone(server, jane):
    make(jane, "GfPln", name="Lisa", sex="female", birthYear=2018)
    make_user(server, "john")
    john = sign_in(server, "john")
    assert john.get("/ui/api/gift-plans").json()["items"] == []
    assert "Lisa" in {p["name"] for p in john.get("/ui/api/persons").json()["items"]}
    bad = make(jane, "GfPln", name=" ", birthMonth=13)
    assert {e["field"] for e in bad.json()["errors"]} >= {"name", "sex", "birthMonth"}


def test_the_plan_and_its_beneficiary(jane):
    acct, lisa, p = plan(jane)
    assert p["beneficiary"] == {
        "kind": "person",
        "id": lisa["id"],
        "name": "Lisa Doe",
        "birthYear": 2018,
        "deleted": False,
    }
    assert p["planState"] == "Utah" and p["stateDeduction"] == "2410.00"
    assert p["rollover"]["possibleFrom"] == "2033-05-02" and p["rollover"]["limit"] == "35000.00"
    a = jane.get(f"/ui/api/accounts/{acct['id']}").json()
    assert a["group"] == "education" and a["investing"]


def test_contributions_against_the_gift_exclusion(server, jane):
    acct, _, _ = plan(jane)
    gran = {"id": make(jane, "GfPln", name="Candace Doe", sex="female").json()["personId"]}
    bank = new_account(jane, name="Checking")
    add(jane, bank["id"], "20000.00", "2026-01-02")
    r = make(
        jane,
        "Cntrb",
        accountId=acct["id"],
        date="2026-02-01",
        amount="6000",
        fromAccountId=bank["id"],
    )
    assert r.status_code == 200, r.text
    assert jane.get(f"/ui/api/accounts/{bank['id']}").json()["balance"] == "14000.00"
    make(
        jane,
        "Cntrb",
        accountId=acct["id"],
        date="2024-03-01",
        amount="90000",
        contributor=f"person:{gran['id']}",
        fiveYear=True,
    )
    make(
        jane,
        "Cntrb",
        accountId=acct["id"],
        date="2026-06-01",
        amount="2500",
        contributor=f"person:{gran['id']}",
    )
    v = jane.get(f"/ui/api/accounts/{acct['id']}/contributions").json()
    years = {(y["name"], y["year"]): y for y in v["years"]}
    g24 = years[("Candace Doe", 2024)]
    assert g24["counted"] == "18000.00" and g24["fromElection"] == 2024 and not g24["over"]
    g26 = years[("Candace Doe", 2026)]
    assert g26["counted"] == "20500.00" and g26["over"], "18,000 of the election and 2,500 more"
    assert ("Candace Doe", 2028) in years and ("Candace Doe", 2029) not in years
    owner = next(y for y in v["years"] if y["contributor"] == "owner" and y["year"] == 2026)
    assert owner["counted"] == "6000.00" and not owner["over"]
    # An imported deposit is tagged afterwards.
    t = add(jane, acct["id"], "1000.00", "2026-09-01")
    tag = {"accountId": acct["id"], "transactionId": t["id"], "contributor": f"person:{gran['id']}"}
    r = jane.post(
        "/ui/api/save",
        json={"ops": [{"op": "create", "entity": "Cntrb", "id": new_id("Cntrb"), "fields": tag}]},
    )
    assert saved(r)["name"] == "Candace Doe"
    # Told again, it was the owner's; its deposit can't change from here.
    mine = saved(change(jane, "Cntrb", saved(r), contributor="owner"))
    assert mine["contributor"] == "owner"
    r = change(jane, "Cntrb", mine, amount="5")
    assert r.json()["errors"][0]["code"] == "contribution-fixed"


def test_an_election_spreads_five_exclusions_and_counts_the_rest_in_its_year(jane):
    """S1.8.2: only five times the year's exclusion is spread, a fifth a year; the rest, and
    any cent the fifths leave, counts in the contribution's own year."""
    acct, _, _ = plan(jane)
    who = {}
    for name in ("Candace Doe", "Jeremy Doe"):
        who[name] = make(jane, "GfPln", name=name, sex="female").json()["personId"]
    for name, amount in (("Candace Doe", "100000.03"), ("Jeremy Doe", "10000.03")):
        r = make(
            jane,
            "Cntrb",
            accountId=acct["id"],
            date="2026-02-01",
            amount=amount,
            contributor=f"person:{who[name]}",
            fiveYear=True,
        )
        assert r.status_code == 200, r.text
    v = jane.get(f"/ui/api/accounts/{acct['id']}/contributions").json()
    years = {(y["name"], y["year"]): y for y in v["years"]}
    big = [years[("Candace Doe", y)] for y in range(2026, 2031)]
    assert [(g["counted"], g["over"]) for g in big] == [("24000.03", True)] + [
        ("19000.00", False)
    ] * 4, "95,000 spread at the 2026 exclusion of 19,000; 5,000.03 more in 2026"
    small = [years[("Jeremy Doe", y)]["counted"] for y in range(2026, 2031)]
    assert small == ["2000.03"] + ["2000.00"] * 4


def test_withdrawals_against_qualified_expenses(jane):
    acct, _, _ = plan(jane)
    add(jane, acct["id"], "50000.00", "2025-01-02")
    add(jane, acct["id"], "-46000.00", "2026-08-20")
    r = make(
        jane,
        "QExpn",
        accountId=acct["id"],
        date="2026-08-15",
        kind="tuition",
        description="Fall tuition",
        amount="44200",
    )
    assert r.status_code == 200, r.text
    y = jane.get(f"/ui/api/accounts/{acct['id']}/withdrawals").json()["years"][0]
    assert (y["year"], y["distributions"], y["expenses"], y["notCovered"]) == (
        2026,
        "46000.00",
        "44200.00",
        "1800.00",
    )
    bad = make(jane, "QExpn", accountId=acct["id"], date="2026-08-15", kind="car", amount="1")
    assert bad.status_code == 422
    e = jane.get(f"/ui/api/accounts/{acct['id']}/withdrawals").json()["expenses"][0]
    # Its receipt, kept with it as a link the save makes (S1.8.3, S9.3), and taken away.
    rid = jane.post(
        "/ui/api/receipts", files={"file": ("bill.pdf", b"%PDF-1.4 bill", "application/pdf")}
    ).json()["id"]
    assert saved(attach(jane, rid, e["id"], "expense"))["kind"] == "expense"
    e = jane.get(f"/ui/api/accounts/{acct['id']}/withdrawals").json()["expenses"][0]
    assert [d["id"] for d in e["documents"]] == [rid]
    assert detach(jane, rid, e["id"]).status_code == 200
    e = jane.get(f"/ui/api/accounts/{acct['id']}/withdrawals").json()["expenses"][0]
    assert e["documents"] == []
    assert remove(jane, "QExpn", e).status_code == 200
    assert jane.get(f"/ui/api/accounts/{acct['id']}/withdrawals").json()["expenses"] == []


def test_a_rollover_is_a_distribution_covered_by_its_own_column(server, jane):
    """S1.8.3, S8.10: money moved to the beneficiary's Roth IRA or another 529 is in the
    year's distributions, as Form 1099-Q has it, and covered as Rolled Over, not left
    uncovered."""
    acct, _, _ = plan(jane, opened="2010-05-01")
    roth = new_account(jane, name="Lisa's Roth IRA", type="roth-ira")
    sibling = new_account(jane, name="Sam's 529", type="529")
    add(jane, acct["id"], "40000.00", "2012-01-02")
    for to, amount, day in ((roth, "7000.00", "2026-03-02"), (sibling, "3000.00", "2026-04-01")):
        out = add(jane, acct["id"], f"-{amount}", day, payee=to["name"])
        inn = add(jane, to["id"], amount, day, payee="From the 529", kind="deposit")
        assert inn["transferId"] == out["id"]
    add(jane, acct["id"], "-5000.00", "2026-08-20", payee="Withdrawal")
    r = make(jane, "QExpn", accountId=acct["id"], date="2026-08-15", kind="tuition", amount="4000")
    assert r.status_code == 200, r.text
    (y,) = jane.get(f"/ui/api/accounts/{acct['id']}/withdrawals").json()["years"]
    assert (y["distributions"], y["expenses"], y["rolledOver"], y["notCovered"]) == (
        "15000.00",
        "4000.00",
        "10000.00",
        "1000.00",
    )
    p = jane.get(f"/ui/api/accounts/{acct['id']}/plan529").json()["rollover"]
    assert p["used"] == "7000.00", "only the Roth IRA's counts against the lifetime limit"
    # One who reads the 529 alone sees the same: the receiving accounts are read as the
    # server, and never named (S7.1.1).
    make_user(server, "john")
    john = sign_in(server, "john")
    john_id = john.get("/ui/api/session").json()["user"]["id"]
    share(jane, "account", acct["id"], users={john_id: "read"})
    assert john.get(f"/ui/api/accounts/{acct['id']}/withdrawals").json()["years"] == [y]
    p = john.get(f"/ui/api/accounts/{acct['id']}/plan529").json()["rollover"]
    assert p["used"] == "7000.00"


def test_the_roth_rollover_after_fifteen_years(jane):
    acct, _, _ = plan(jane, opened="2010-05-01")
    add(jane, acct["id"], "20000.00", "2012-01-02")
    add(jane, acct["id"], "9000.00", "2024-01-02")
    p = jane.get(f"/ui/api/accounts/{acct['id']}/plan529").json()["rollover"]
    assert p["possibleFrom"] == "2025-05-01"
    assert p["eligible"] == "20000.00" and p["available"] == "20000.00"


@pytest.mark.parametrize(
    ("moves", "eligible", "available"),
    [
        # Old contributions' earnings count: 20,000 grown to 60,000, the lifetime limit caps.
        ([("20000.00", "2008-01-02", "deposit"), ("40000.00", "2015-01-02", "interest")],
         "60000.00", "35000.00"),
        # A recent contribution keeps its own earnings out: 9,000 grew 900/29,000 with the
        # rest, so 9,279.31 of the 29,900 can't roll over yet.
        ([("20000.00", "2012-01-02", "deposit"), ("9000.00", "2024-01-02", "deposit"),
          ("900.00", "2025-01-02", "interest")], "20620.69", "20620.69"),
        # Worth less than the recent contributions grown: nothing.
        ([("9000.00", "2024-01-02", "deposit"), ("-2000.00", "2025-01-02", "fee")],
         "0.00", "0.00"),
        # Part of the lifetime limit already used: what is left of it caps.
        ([("20000.00", "2008-01-02", "deposit"), ("40000.00", "2015-01-02", "interest"),
          ("-5000.00", "2026-03-02", "roth")], "55000.00", "30000.00"),
        # What was rolled over comes off the limit only: the value has already dropped by it.
        ([("40000.00", "2008-01-02", "deposit"), ("-10000.00", "2026-03-02", "roth")],
         "30000.00", "25000.00"),
    ],
)  # fmt: skip
def test_what_could_still_roll_over_counts_the_earnings_on_old_contributions(
    jane, moves, eligible, available
):
    """S1.8.4: the account's value, less the last five years' contributions and their
    estimated earnings (each grown by the account's return since it), capped by what is left
    of the lifetime limit after what was rolled over."""
    acct, _, _ = plan(jane, opened="2008-01-01")
    for amount, day, kind in moves:
        if kind == "roth":
            roth = new_account(jane, name="Lisa's Roth IRA", type="roth-ira")
            out = add(jane, acct["id"], amount, day, payee="To the Roth IRA")
            inn = add(jane, roth["id"], amount[1:], day, payee="From the 529", kind="deposit")
            assert inn["transferId"] == out["id"]
        else:
            add(jane, acct["id"], amount, day, kind=kind)
    p = jane.get(f"/ui/api/accounts/{acct['id']}/plan529").json()["rollover"]
    assert (p["eligible"], p["available"]) == (eligible, available)


def test_the_goal_tab_starts_an_education_projection(jane):
    acct, _, _ = plan(jane)
    add(jane, acct["id"], "48000.00", "2023-06-01")
    assert jane.get(f"/ui/api/accounts/{acct['id']}/goal").json()["projection"] is None
    r = jane.post(f"/ui/api/accounts/{acct['id']}/goal")
    assert r.status_code == 201, r.text
    p = r.json()["projection"]
    a = p["result"]["answer"]
    assert a["kind"] == "education" and a["firstYear"] == 2036 and a["years"] == 4
    assert a["costToday"] == 27100 and 0 < a["funded"] <= 100
    assert a["funded"] < 100 and a["neededMonthly"] > 0
    assert p["headline"].endswith("funded for Lisa Doe's 4 years")
    # More saved each month funds more of it.
    more = saved(change(jane, "Prjct", p, inputs={**p["inputs"], "monthly": 2000}))
    assert more["result"]["answer"]["funded"] > a["funded"]
    again = jane.get(f"/ui/api/accounts/{acct['id']}/goal").json()
    assert again["projection"]["id"] == p["id"]
    bad = make(
        jane,
        "Prjct",
        name="X",
        goal="education",
        builtOn={"kind": "typed", "amount": 1},
        inputs={"beneficiary": {"kind": "person", "id": "Persn_nope"}, "monthly": 0, "fees": 0.1},
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
def test_saving_counts_until_school_starts_on_sep_1(jane, first_year, low, high):
    """S6.2.2: the balance when school starts counts every month saved before Sep 1 of its
    first year; it counted whole years ending a year before school, so a school next year saw
    no saving at all."""
    acct, _, _ = plan(jane)
    p = jane.post(f"/ui/api/accounts/{acct['id']}/goal").json()["projection"]
    p = saved(change(jane, "Prjct", p, inputs={**p["inputs"], "firstYear": first_year,
                                                "monthly": 1000}))  # fmt: skip
    a = p["result"]["answer"]
    assert low <= a["atStart"] <= high, a["atStart"]
    if first_year == 2026:
        assert a["neededMonthly"] is None, "no monthly saving reaches it by then"
    else:
        # Saving what it names funds it: the median at the start meets what is needed.
        p = saved(change(jane, "Prjct", p, inputs={**p["inputs"],
                                                    "monthly": a["neededMonthly"]}))  # fmt: skip
        assert p["result"]["answer"]["funded"] >= 97


def _prepared(server, jane, today: dt.date, first_year: int):
    """The education plan `prepare` makes for school starting `first_year`, on `today`."""
    from moolakata import projections
    from moolakata.store.entities.projections import Projection

    acct, _, _ = plan(jane)
    p = jane.post(f"/ui/api/accounts/{acct['id']}/goal").json()["projection"]
    p = saved(change(jane, "Prjct", p, inputs={**p["inputs"], "firstYear": first_year,
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
    server, jane, today, first_year, index, part
):
    """S6.2.2: saving goes on until Sep 1 of school's first year, its last year counting
    the part before then; a projection runs at most 100 years on, school's 4 among them."""
    if part == "span":  # the days to Sep 1, in years, less the whole years before
        part = (dt.date(first_year, 9, 1) - today).days / 365.25 - (index - 1)
    prep = _prepared(server, jane, today, first_year)
    assert prep.target_index == index and prep.start_part == pytest.approx(part, abs=1e-9)
    plan = prep.plan
    assert (plan.contribute_years, plan.years) == (index, index + 4)
    assert plan.contribute_part == pytest.approx(part, abs=1e-9)


def test_a_fully_funded_school_needs_no_more_saving(jane):
    acct, _, _ = plan(jane)
    add(jane, acct["id"], "900000.00", "2023-06-01")
    a = jane.post(f"/ui/api/accounts/{acct['id']}/goal").json()["projection"]["result"]["answer"]
    assert a["funded"] == 100 and a["neededMonthly"] == 0.0


def test_the_saving_named_funds_school_at_the_median(jane, monkeypatch):
    """Funds it fully means the median balance meets the cost (S6.2.2): the search asks for a
    50% chance; and when no saving reaches it, the answer says so."""
    from moolakata.projections import engine

    asked = []
    real = engine.needed_saving

    def spy(*args, **kw):
        asked.append(kw.get("chance", 0.9))
        return real(*args, **kw)

    monkeypatch.setattr(engine, "needed_saving", spy)
    acct, _, _ = plan(jane)
    p = jane.post(f"/ui/api/accounts/{acct['id']}/goal").json()["projection"]
    assert asked == [0.5] and p["result"]["answer"]["neededMonthly"] > 0
    monkeypatch.setattr(engine, "DOUBLINGS", 0)
    p = saved(change(jane, "Prjct", p, inputs={**p["inputs"], "monthly": 10}))
    assert p["result"]["answer"]["neededMonthly"] is None


def test_a_school_under_way_and_funded_needs_no_more_saving(server, jane):
    """Funded is funded: a school already started that the balance covers names no saving,
    rather than saying none reaches it."""
    acct, _, _ = plan(jane)
    add(jane, acct["id"], "900000.00", "2023-06-01")
    p = jane.post(f"/ui/api/accounts/{acct['id']}/goal").json()["projection"]
    p = saved(change(jane, "Prjct", p, inputs={**p["inputs"], "firstYear": 2026}))
    a = p["result"]["answer"]
    assert a["funded"] == 100 and a["neededMonthly"] == 0.0
