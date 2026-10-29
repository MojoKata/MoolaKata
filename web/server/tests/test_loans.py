"""Loans (requirements S1.9)."""

import datetime as dt
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import create, remove, saved, terms
from test_accounts import add, new_account

from moolakata import clock
from moolakata import loans as L
from moolakata.loans import payoff as P

T0 = dt.datetime(2026, 10, 13, 12, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def mortgage_terms(**kw):
    return L.Terms(principal=D(300000), start=dt.date(2025, 1, 1), months=360, rate=D(6), **kw)


def test_the_level_payment_and_its_first_split():
    t = mortgage_terms(escrowTax=D(300), escrowInsurance=D(100), pmi=D(90))
    assert L.scheduled_payment(t) == D("1798.65")
    p = L.split_for(t, [], [], dt.date(2025, 2, 1), D("2288.65"))
    assert (p.interest, p.principal, p.escrowTax, p.pmi) == (
        D("1500.00"),
        D("298.65"),
        D(300),
        D(90),
    )
    assert p.overpayment == 0


def test_pmi_ends_at_78_percent_of_the_original_value():
    # B21: not charged to payoff; the schedule drops it once the balance is 78% of the value.
    t = mortgage_terms(pmi=D(90), originalValue=D(360000))  # 78% is 280,800
    rows = L.schedule(t, [], [], dt.date(2025, 1, 15))
    charged = [r for r in rows if r.pmi]
    assert charged and rows[-1].pmi == 0
    assert all(r.balance > D(280800) for r in charged)
    assert next(r for r in rows if not r.pmi).balance <= D(280800)
    assert L.split_for(t, [], [], dt.date(2025, 2, 1), D("1888.65")).pmi == D(90)


def test_a_payment_typed_in_the_loans_account_is_split_by_the_schedule(server, frozen):
    # B21: not wholly principal; and its interest counts as the loan's interest on Taxes.
    make_user(server, "alice")
    c = sign_in(server, "alice")
    loan = new_account(c, name="Home", type="mortgage")
    saved(
        terms(c, loan["id"], principal="300000", startDate="2026-01-01", termMonths=360, rate="6")
    )
    add(c, loan["id"], "1798.65", "2026-02-01", kind="deposit")
    v = c.get(f"/ui/api/accounts/{loan['id']}/loan").json()
    assert v["balance"] == "299701.35" and v["interestPaid"] == "1500.00"


def test_an_overpayment_pays_it_off_sooner():
    t = mortgage_terms()
    plain, extra = [], []
    for i in range(1, 25):
        d = L.add_months(t.start, i)
        plain.append(L.split_for(t, plain, [], d, D("1798.65")))
        extra.append(L.split_for(t, extra, [], d, D("1798.65") + (D(20000) if i == 12 else 0)))
    assert extra[11].overpayment == D(20000)
    today = dt.date(2027, 1, 15)
    a, _ = L.summary(t, plain, [], today)
    b, _ = L.summary(t, extra, [], today)
    assert b.payoffDate < a.payoffDate and b.interestAhead < a.interestAhead - 30000
    assert a.payoffDate == dt.date(2055, 1, 1)


def test_a_recast_lowers_the_payment_and_keeps_the_end():
    t = mortgage_terms()
    pays = []
    for i in range(1, 13):
        d = L.add_months(t.start, i)
        pays.append(L.split_for(t, pays, [], d, D("1798.65") + (D(50000) if i == 6 else 0)))
    t.recasts = [(dt.date(2025, 12, 15), D(250))]
    s, _ = L.summary(t, pays, [], dt.date(2026, 1, 15))
    assert s.payment < D("1500") and s.payoffDate == dt.date(2055, 1, 1)


def test_an_arm_reset_changes_the_payment():
    t = mortgage_terms(resets=[(dt.date(2030, 1, 1), D("7.5"))])
    _, rows = L.summary(t, [], [], dt.date(2025, 1, 15))
    before = next(r for r in rows if r.date == dt.date(2029, 12, 1))
    after = next(r for r in rows if r.date == dt.date(2030, 2, 1))
    assert after.principal + after.interest > before.principal + before.interest


def test_daily_interest_for_a_car_loan():
    t = L.Terms(
        principal=D(25000), start=dt.date(2026, 1, 15), months=60, rate=D("7.3"), method="daily"
    )
    p = L.split_for(t, [], [], dt.date(2026, 2, 15), D("500"))
    assert p.interest == (D(25000) * D("0.073") * 31 / 365).quantize(D("0.01"))


def test_a_heloc_pays_interest_only_while_drawing():
    t = L.Terms(principal=D(0), start=dt.date(2026, 1, 1), months=240, rate=D(8), drawMonths=120)
    draws = [(dt.date(2026, 2, 1), D(30000))]
    _, rows = L.summary(t, [], draws, dt.date(2026, 3, 15))
    assert rows[0].principal == 0 and rows[0].interest == D("200.00")
    late = next(r for r in rows if r.date == dt.date(2036, 2, 1))
    assert late.principal > 0


def test_payments_through_the_api(server, frozen):
    make_user(server, "alice")
    c = sign_in(server, "alice")
    bank = new_account(c, name="Checking")
    add(c, bank["id"], "10000.00", "2026-09-01")
    loan = new_account(c, name="Home", type="mortgage", institution="Rocket")
    v = saved(terms(c, loan["id"], principal="300000", startDate="2026-01-01", termMonths=360,
                    rate="6", escrowTax="300", escrowInsurance="100"))  # fmt: skip
    assert v["terms"]["computedPayment"] == "1798.65" and v["balance"] == "300000.00"
    # A payment from the checking account: both halves, split by the schedule.
    r = c.post(
        f"/ui/api/accounts/{loan['id']}/loan/payments",
        json={"date": "2026-02-01", "amount": "2198.65", "fromAccountId": bank["id"]},
    )
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["balance"] == "299701.35" and v["interestPaid"] == "1500.00"
    # The loan counts in net worth as what is owed.
    acct = c.get(f"/ui/api/accounts/{loan['id']}").json()
    assert acct["balance"] == "-299701.35"
    assert c.get(f"/ui/api/accounts/{bank['id']}").json()["balance"] == "7801.35"
    # A bank transaction that looks like the payment is offered, and linked.
    t = add(c, bank["id"], "-2198.65", "2026-10-01", payee="ROCKET MORTGAGE")
    cands = c.get(f"/ui/api/accounts/{loan['id']}/loan/candidates").json()["items"]
    assert [x["transactionId"] for x in cands] == [t["id"]]
    r = c.post(
        f"/ui/api/accounts/{loan['id']}/loan/payments",
        json={"date": "2026-10-01", "amount": "2198.65", "transactionId": t["id"]},
    )
    assert r.status_code == 201
    assert c.get(f"/ui/api/accounts/{loan['id']}/loan/candidates").json()["items"] == []
    # A split typed from the servicer's statement must add up.
    r = c.post(
        f"/ui/api/accounts/{loan['id']}/loan/payments",
        json={"date": "2026-11-01", "amount": "2198.65", "principal": "10", "interest": "10"},
    )
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "split-does-not-add-up"


def test_the_servicers_balance_against_the_computed_one(server, frozen):
    make_user(server, "alice")
    c = sign_in(server, "alice")
    loan = new_account(c, name="Car", type="auto-loan")
    saved(terms(c, loan["id"], principal="20000", startDate="2026-01-01", termMonths=60, rate="5"))
    r = create(c, "Anchr", accountId=loan["id"], date="2026-10-01", balance="-19950.00")
    assert r.status_code == 200, r.text
    v = c.get(f"/ui/api/accounts/{loan['id']}/loan").json()
    assert v["servicer"]["difference"] == "-50.00"


def test_terms_are_checked(server, frozen):
    make_user(server, "alice")
    c = sign_in(server, "alice")
    loan = new_account(c, name="Car", type="auto-loan")
    r = terms(c, loan["id"], principal="-1", startDate="2026-01-01", termMonths=0, rate="99")
    assert {e["field"] for e in r.json()["errors"]} == {"principal", "termMonths", "rate"}


def test_a_rate_as_the_note_states_it(server, frozen):
    # B6: three places for the rate (6.875%), four for an ARM's reset; more are refused.
    make_user(server, "alice")
    c = sign_in(server, "alice")
    loan = new_account(c, name="Home", type="mortgage")
    home = {"principal": "300000", "startDate": "2026-01-01", "termMonths": 360}
    reset = [{"date": "2031-01-01", "rate": "7.3125"}]
    v = saved(terms(c, loan["id"], **home, rate="6.875", resets=reset))
    assert v["terms"]["rate"] == "6.875" and v["terms"]["resets"][0]["rate"] == "7.3125"
    assert v["rate"] == "6.875" and v["terms"]["computedPayment"] == "1970.79"
    r = terms(c, loan["id"], rate="6.8755")
    assert r.status_code == 422 and "rate" in r.text


# ---- The payoff planner (S6.10) ----


def test_extra_each_month_pays_off_sooner_and_saves_interest():
    t = mortgage_terms()
    r = P.plan_outcomes(t, [], [], dt.date(2025, 1, 15), P.Plan(monthly=D(300)), 7.0)
    assert r.schedule.payoffDate == dt.date(2055, 1, 1)
    assert r.plan.payoffDate < dt.date(2049, 1, 1)
    assert r.schedule.interest - r.plan.interest > 80000
    assert r.invested.contributed > 0 and r.invested.value > r.invested.contributed


def test_biweekly_is_a_thirteenth_payment_a_year():
    t = mortgage_terms()
    r = P.plan_outcomes(t, [], [], dt.date(2025, 1, 15), P.Plan(biweekly=True), 7.0)
    extra = next(x for x in r.plan.rows if not x.past).overpayment
    assert extra == (D("1798.65") / 12).quantize(D("0.01"))
    assert 4 <= (r.schedule.payoffDate.year - r.plan.payoffDate.year) <= 7


def test_a_lump_sum_shortens_or_recasts():
    t = mortgage_terms()
    plan = P.Plan(lumps=[(dt.date(2026, 6, 15), D(50000))], recast=True, recastFee=D(250))
    r = P.plan_outcomes(t, [], [], dt.date(2025, 1, 15), plan, 7.0)
    # Shortened: the payment stays and the loan ends years sooner.
    assert r.plan.paymentAfter == r.plan.payment and r.plan.payoffDate < dt.date(2047, 1, 1)
    # Recast: the payment drops and the end stays.
    assert r.recast.paymentAfter < r.recast.payment - 250
    assert r.recast.payoffDate == dt.date(2055, 1, 1) and r.recast.fees == D(250)
    assert r.schedule.interest - r.plan.interest > r.schedule.interest - r.recast.interest


def test_rounding_up_each_payment():
    t = mortgage_terms(escrowTax=D(300))
    r = P.plan_outcomes(t, [], [], dt.date(2025, 1, 15), P.Plan(roundTo=D(100)), 7.0)
    first = next(x for x in r.plan.rows if not x.past)
    assert first.payment == D(2100)


def test_the_planner_and_plans_through_the_api(server, frozen):
    make_user(server, "alice")
    c = sign_in(server, "alice")
    loan = new_account(c, name="Home", type="mortgage")
    saved(
        terms(c, loan["id"], principal="300000", startDate="2026-01-01", termMonths=360, rate="6")
    )
    r = c.post(f"/ui/api/accounts/{loan['id']}/loan/payoff", json={"monthly": "300"})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["plan"]["monthsSaved"] > 60 and float(v["plan"]["interestSaved"]) > 80000
    assert v["invested"]["assetClass"] == "usStocks" and v["invested"]["rate"] == 7.0
    assert v["recast"] is None and v["planRows"][0]["overpayment"] == "300.00"
    bad = c.post(f"/ui/api/accounts/{loan['id']}/loan/payoff", json={"monthly": "-1"})
    assert bad.status_code == 422 and bad.json()["errors"][0]["field"] == "monthly"
    # Saved, then followed: overpaying less than the plan is behind it.
    r = c.post(
        f"/ui/api/accounts/{loan['id']}/loan/plans",
        json={"name": "Extra $300", "inputs": {"monthly": "300"}},
    )
    assert r.status_code == 201, r.text
    plan = r.json()
    assert plan["headline"].startswith("Paid off ")
    r = c.post(
        f"/ui/api/accounts/{loan['id']}/loan/plans/{plan['id']}/follow",
        json={"following": True},
    )
    assert r.json()["following"] and r.json()["followingSince"] == "2026-10-13"
    clock.fix(dt.datetime(2026, 12, 20, 12, tzinfo=dt.UTC))
    c = sign_in(server, "alice")
    c.post(
        f"/ui/api/accounts/{loan['id']}/loan/payments",
        json={"date": "2026-11-01", "amount": "1898.65"},
    )
    f = c.get(f"/ui/api/accounts/{loan['id']}/loan").json()["following"]
    assert f["name"] == "Extra $300" and f["expected"] == "600.00"
    assert f["actual"] == "100.00" and f["ahead"] == "-500.00"
    # Another followed replaces it.
    other = c.post(
        f"/ui/api/accounts/{loan['id']}/loan/plans",
        json={"name": "Biweekly", "inputs": {"biweekly": True}},
    ).json()
    c.post(
        f"/ui/api/accounts/{loan['id']}/loan/plans/{other['id']}/follow",
        json={"following": True},
    )
    rows = {
        p["name"]: p for p in c.get(f"/ui/api/accounts/{loan['id']}/loan/plans").json()["items"]
    }
    assert rows["Biweekly"]["following"] and not rows["Extra $300"]["following"]
    assert remove(c, "Pyoff", rows["Biweekly"]).status_code == 200


def test_rounding_up_counts_pmi_only_while_it_is_due():
    # B21, S1.9.5: once PMI ends, the rounded payment rounds what is paid without it.
    t = mortgage_terms(escrowTax=D(300), pmi=D(90), originalValue=D(360000))
    r = P.plan_outcomes(t, [], [], dt.date(2025, 1, 15), P.Plan(roundTo=D(100)), 7.0)
    ahead = [x for x in r.plan.rows if not x.past]
    assert all(x.payment % D(100) == 0 for x in ahead[:-1]), "every payment a round 100"
    with_pmi = next(x for x in ahead if x.pmi)
    without = next(x for x in ahead if not x.pmi)
    assert with_pmi.payment == D(2200) and without.payment == D(2100), "PMI's 90 no longer in it"
