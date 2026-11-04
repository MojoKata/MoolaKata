"""Loans (requirements S1.9)."""

import datetime as dt
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import change, create, loan_payment, make, remove, saved, terms
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
    kw = {"start": dt.date(2025, 1, 1), **kw}
    return L.Terms(principal=D(300000), months=360, rate=D(6), **kw)


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
    # No payment recorded yet: Automatic reads as assumed as scheduled, Feb to Oct paid.
    assert v["terms"]["computedPayment"] == "1798.65" and v["paymentsResolved"] == "assumed"
    assert [r["status"] for r in v["rows"][:10]] == ["assumed"] * 9 + ["ahead"]
    assert v["balance"] == v["rows"][8]["balance"] and v["missed"] == 0
    # A payment from the checking account: both halves, split by the schedule.
    r = loan_payment(c, loan["id"], "2026-02-01", "2198.65", from_account=bank["id"])
    assert r.status_code == 200, r.text
    v = c.get(f"/ui/api/accounts/{loan['id']}/loan").json()
    assert v["balance"] == "299701.35" and v["interestPaid"] == "1500.00"
    # The loan counts in net worth as what is owed.
    acct = c.get(f"/ui/api/accounts/{loan['id']}").json()
    assert acct["balance"] == "-299701.35"
    assert c.get(f"/ui/api/accounts/{bank['id']}").json()["balance"] == "7801.35"
    # A bank transaction that looks like the payment is offered, and linked.
    t = add(c, bank["id"], "-2198.65", "2026-10-01", payee="ROCKET MORTGAGE")
    cands = c.get(f"/ui/api/accounts/{loan['id']}/loan/candidates").json()["items"]
    assert [x["transactionId"] for x in cands] == [t["id"]]
    r = loan_payment(c, loan["id"], "2026-10-01", "2198.65", transaction=t["id"])
    assert r.status_code == 200, r.text
    assert c.get(f"/ui/api/accounts/{loan['id']}/loan/candidates").json()["items"] == []
    paid = c.get(f"/ui/api/transactions/{t['id']}").json()
    assert paid["transferAccountName"] == "Home"
    # A bank transaction already paired is no other payment's half.
    r = loan_payment(c, loan["id"], "2026-10-01", "2198.65", transaction=t["id"])
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "transfer-taken"
    # A split typed from the servicer's statement must add up.
    r = loan_payment(c, loan["id"], "2026-11-01", "2198.65", parts={"principal": "10",
                                                                     "interest": "10"})  # fmt: skip
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "splits-unbalanced"


def test_the_servicers_balance_against_the_computed_one(server, frozen):
    make_user(server, "alice")
    c = sign_in(server, "alice")
    loan = new_account(c, name="Car", type="auto-loan")
    saved(terms(c, loan["id"], principal="20000", startDate="2026-01-01", termMonths=60, rate="5",
                paymentsMode="recorded"))  # fmt: skip
    # Before the first payment day: the balance is the principal, whatever the setting reads.
    r = create(c, "Anchr", accountId=loan["id"], date="2026-01-15", balance="-19950.00")
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
    r = make(c, "Pyoff", accountId=loan["id"], name="Extra $300", inputs={"monthly": "300"})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["headline"].startswith("Paid off ")
    r = c.post(
        f"/ui/api/accounts/{loan['id']}/loan/plans/{plan['id']}/follow",
        json={"following": True},
    )
    assert r.json()["following"] and r.json()["followingSince"] == "2026-10-13"
    clock.fix(dt.datetime(2026, 12, 20, 12, tzinfo=dt.UTC))
    c = sign_in(server, "alice")
    saved(loan_payment(c, loan["id"], "2026-11-01", "1898.65"))
    f = c.get(f"/ui/api/accounts/{loan['id']}/loan").json()["following"]
    assert f["name"] == "Extra $300" and f["expected"] == "600.00"
    assert f["actual"] == "100.00" and f["ahead"] == "-500.00"
    # Another followed replaces it.
    other = make(
        c, "Pyoff", accountId=loan["id"], name="Biweekly", inputs={"biweekly": True}
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


def test_a_helocs_payment_while_drawing_is_the_interest_due(server, frozen):
    """CR3-21: in the draw period the payment is the schedule's next row, interest alone, so
    the screen, the dialog and the bank transactions offered read $200, not $0."""
    make_user(server, "alice")
    c = sign_in(server, "alice")
    bank = new_account(c, name="Checking")
    add(c, bank["id"], "10000.00", "2026-09-01")
    line = new_account(c, name="Line", type="heloc")
    saved(terms(c, line["id"], principal="0", startDate="2026-01-01", termMonths=240, rate="8",
                drawMonths=120))  # fmt: skip
    add(c, line["id"], "-30000.00", "2026-02-01", payee="Draw", kind="withdrawal")
    v = c.get(f"/ui/api/accounts/{line['id']}/loan").json()
    nxt = next(x for x in v["rows"] if not x["past"])
    assert v["payment"] == v["total"] == nxt["payment"] == "200.00"
    assert v["interestOnlyUntil"] == "2036-01-01"
    t = add(c, bank["id"], "-200.00", "2026-10-01", payee="UMB HELOC")
    cands = c.get(f"/ui/api/accounts/{line['id']}/loan/candidates").json()["items"]
    assert [x["transactionId"] for x in cands] == [t["id"]]


def test_the_payment_is_the_schedules_next_row_for_every_shape():
    """CR3-21: whatever the terms, the summary's payment is the next row's principal and
    interest, and its total the row's payment."""
    today = dt.date(2026, 10, 13)
    shapes = [
        mortgage_terms(
            escrowTax=D(300), escrowInsurance=D(100), pmi=D(90), originalValue=D(360000)
        ),
        L.Terms(
            principal=D(20000), start=dt.date(2026, 1, 1), months=60, rate=D(5), method="daily"
        ),
        L.Terms(principal=D(0), start=dt.date(2026, 1, 1), months=240, rate=D(8), drawMonths=120),
        L.Terms(
            principal=D(50000), start=dt.date(2014, 1, 1), months=240, rate=D(8), drawMonths=120
        ),
        mortgage_terms(recasts=[(dt.date(2026, 3, 1), D(250))]),
        mortgage_terms(resets=[(dt.date(2026, 1, 1), D("7.25"))]),
        L.Terms(principal=D(1000), start=dt.date(2026, 1, 1), months=10, rate=D(6)),
    ]
    for t in shapes:
        draws = [(dt.date(2026, 2, 1), D(30000))] if t.drawMonths and not t.principal else []
        sm, rows = L.summary(t, [], draws, today)
        nxt = next((r for r in rows if not r.past), None)
        assert nxt is not None, t
        assert (sm.payment, sm.total) == (nxt.principal + nxt.interest, nxt.payment), t


def _a_loan_and_checking(server):
    make_user(server, "alice")
    c = sign_in(server, "alice")
    bank = new_account(c, name="Checking")
    add(c, bank["id"], "10000.00", "2026-09-01")
    loan = new_account(c, name="Home", type="mortgage")
    saved(terms(c, loan["id"], principal="300000", startDate="2026-01-01", termMonths=360,
                rate="6"))  # fmt: skip
    return c, bank, loan


def _unpair(server, txn_id):
    from moolakata.store.entities.accounts import Transaction
    from moolakata.store.repos import ledger as repo

    with server.db.tx(unscoped="test") as s:
        repo.unlink_transfer(s, s.get(Transaction, txn_id))


def _rows(c, account_id):
    rows = c.get("/ui/api/transactions", params={"pageSize": 1000}).json()["items"]
    return [r for r in rows if r["accountId"] == account_id]


def test_a_payment_recorded_on_the_loan_alone_pairs_with_its_bank_half(server, frozen):
    """CR3-22: a payment recorded with *None*, then its bank debit: *Looks like a payment*
    offers to pair the two, and pairing makes no second payment."""
    c, bank, loan = _a_loan_and_checking(server)
    r = loan_payment(c, loan["id"], "2026-10-01", "1798.65")
    assert r.status_code == 200, r.text
    # The first payment recorded: Feb to Sep before it count as paid as scheduled (S1.9.3), so
    # nine payments are made by the schedule.
    v = c.get(f"/ui/api/accounts/{loan['id']}/loan").json()
    assert [x["status"] for x in v["rows"][:10]] == ["assumed"] * 8 + ["paid", "ahead"]
    assert v["balance"] == "297257.77" and v["missed"] == 0
    debit = add(c, bank["id"], "-1798.65", "2026-10-02", payee="ROCKET MORTGAGE")
    # The save pairs them itself (S1.7); a path that doesn't (an unlinked pair, a file posted
    # in the background) leaves both halves unpaired, as here.
    _unpair(server, debit["id"])
    cands = c.get(f"/ui/api/accounts/{loan['id']}/loan/candidates").json()["items"]
    assert [x["transactionId"] for x in cands] == [debit["id"]]
    pay = cands[0]["pairWith"]
    assert pay and pay["date"] == "2026-10-01"
    r = change(c, "Txn", pay, kind="transfer", transferWithId=debit["id"])
    assert r.status_code == 200, r.text
    assert c.get(f"/ui/api/accounts/{loan['id']}/loan/candidates").json()["items"] == []
    loan_rows = _rows(c, loan["id"])
    assert len(loan_rows) == 1 and loan_rows[0]["transferAccountName"] == "Checking"
    assert c.get(f"/ui/api/accounts/{loan['id']}/loan").json()["balance"] == "297257.77"


def test_a_debit_beside_a_payment_of_another_amount_isnt_offered(server, frozen):
    """CR3-22: a debit within days of an unpaired payment of a different amount is most likely
    that payment; linking it would count it twice."""
    c, bank, loan = _a_loan_and_checking(server)
    assert loan_payment(c, loan["id"], "2026-10-01", "1798.65").status_code == 200
    add(c, bank["id"], "-1800.00", "2026-10-03", payee="ROCKET MORTGAGE")
    assert c.get(f"/ui/api/accounts/{loan['id']}/loan/candidates").json()["items"] == []
    late = add(c, bank["id"], "-1800.00", "2026-10-09", payee="ROCKET MORTGAGE")
    cands = c.get(f"/ui/api/accounts/{loan['id']}/loan/candidates").json()["items"]
    assert [(x["transactionId"], x["pairWith"]) for x in cands] == [(late["id"], None)]


def test_recording_from_an_account_that_holds_the_debit_finds_it(server, frozen):
    """CR3-22: the dialog's *From account* when the bank's half was imported first: the
    halves lookup finds it, and the payment pairs with it, making no second bank row."""
    c, bank, loan = _a_loan_and_checking(server)
    debit = add(c, bank["id"], "-1798.65", "2026-10-01", payee="ROCKET MORTGAGE")
    found = c.get(f"/ui/api/accounts/{loan['id']}/loan/halves",
                  params={"account": bank["id"], "date": "2026-10-02",
                          "amount": "1798.65"}).json()["items"]  # fmt: skip
    assert [x["transactionId"] for x in found] == [debit["id"]]
    r = loan_payment(c, loan["id"], "2026-10-02", "1798.65", transaction=debit["id"])
    assert r.status_code == 200, r.text
    assert len(_rows(c, bank["id"])) == 2  # the opening deposit and the one debit
    assert c.get(f"/ui/api/accounts/{loan['id']}/loan/halves",
                 params={"account": bank["id"], "date": "2026-10-02",
                         "amount": "1798.65"}).json()["items"] == []  # fmt: skip


def test_a_statement_after_a_payment_recorded_from_checking_adds_nothing(server, frozen):
    """CR3-395: the bank's file brings the half the payment dialog made, under its own payee
    and a day later: matched, not added again."""
    from test_accounts import upload
    from worlds import halves

    c, bank, loan = _a_loan_and_checking(server)
    assert loan_payment(c, loan["id"], "2026-10-01", "1798.65",
                        from_account=bank["id"]).status_code == 200  # fmt: skip
    job = upload(c, bank["id"], "oct.ofx", halves.ofx(dt.date(2026, 10, 2), D("1798.65"), "p1"))
    assert job["result"]["added"] == 0 and job["result"]["matched"] == 1
    debits = [r for r in _rows(c, bank["id"]) if D(r["amount"]) < 0]
    assert len(debits) == 1 and debits[0]["transferAccountName"] == "Home"


def test_a_plans_extra_on_each_payment_day():
    """S1.9.5: the monthly extra inside its from/until days (both counted), the yearly one in
    its month, a lump sum with the first payment on or after it, and rounding up that counts
    the escrow and PMI only while it is due (to 78% of the original value)."""
    import datetime as dt
    from decimal import Decimal as D

    from moolakata.loans import Terms
    from moolakata.loans.payoff import Plan, _Extras

    d = dt.date
    t = Terms(D(200000), d(2026, 1, 1), 360, D(6), escrowTax=D("150.40"),
              escrowInsurance=D("49.60"), pmi=D(80), originalValue=D(250000))  # fmt: skip
    plan = Plan(monthly=D(100), monthlyFrom=d(2026, 3, 1), monthlyUntil=d(2026, 5, 1),
                yearly=D(1000), yearlyMonth=6, lumps=[(d(2026, 4, 15), D(5000))])  # fmt: skip
    x = _Extras(plan, t)
    got = [x(d(2026, m, 1), D(1000)) for m in range(2, 8)]
    #        Feb  Mar  Apr  May          Jun (yearly)  Jul
    assert got == [0, 100, 100, D(5100), D(1000), 0]
    up = _Extras(Plan(roundTo=D(100)), t)
    # 1,000 + 200 escrow + 80 PMI = 1,280: 20 more makes 1,300. Owing 78% of the 250,000
    # the home was worth (195,000) or less, no PMI: 1,200 is already a multiple.
    assert up(d(2026, 2, 1), D(1000)) == 20
    assert up(d(2026, 2, 1), D(1000), owed=D("195000.01")) == 20
    assert up(d(2026, 2, 1), D(1000), owed=D(195000)) == 0
    assert _Extras(Plan(biweekly=True), t)(d(2026, 2, 1), D(1200)) == 100


# ---- A payment day with none recorded: the Payments setting (S1.9.3) ----


def _monthly_pays(t, upto: int, skip=(), amount=None):
    """The scheduled payment recorded on payment days 1 to `upto`, but those in `skip`."""
    amount = amount or L.scheduled_payment(t) + t.escrow
    pays = []
    for i in range(1, upto + 1):
        if i not in skip:
            pays.append(L.split_for(t, pays, [], L.add_months(t.start, i), amount))
    return pays


def test_assumed_a_loan_with_no_payments_follows_its_schedule_to_the_end():
    """CR3-413: a 2024 loan with none recorded no longer owes what it borrowed and ends with a
    balloon; each day passed counts as paid as the schedule says, and it pays off on time."""
    t = mortgage_terms(start=dt.date(2024, 3, 1), escrowTax=D(300))
    today = dt.date(2026, 10, 13)
    sm, rows = L.summary(t, [], [], today, "assumed")
    past = [r for r in rows if r.past]
    assert [r.status for r in past] == ["assumed"] * 31 and past[-1].date == dt.date(2026, 10, 1)
    # The same as paying the scheduled amount on each of those days.
    paid = _monthly_pays(t, 31)
    assert sm.balance == L.balance_on(t, paid, [], today) == past[-1].balance
    assert sm.interestPaid == sum(p.interest for p in paid) and sm.missed == 0
    assert sm.nextDate == dt.date(2026, 11, 1) and sm.payoffDate == t.end
    regular = L.scheduled_payment(t) + t.escrow
    assert abs(rows[-1].payment - regular) < 5, "no balloon at the end"
    assert all(r.overpayment == 0 for r in rows)


def test_recorded_here_a_day_is_missed_once_its_grace_has_passed():
    t = mortgage_terms(start=dt.date(2026, 1, 1), escrowTax=D(300))
    pays = _monthly_pays(t, 8)  # Feb to Sep paid; Oct 1 not
    owed = L.balance_on(t, pays, [])
    # Fifteen days after it, the day is still in its grace: the payment due next.
    sm, rows = L.summary(t, pays, [], dt.date(2026, 10, 16), "recorded")
    assert sm.missed == 0 and sm.overdue == 0 and sm.nextDate == dt.date(2026, 10, 1)
    assert not [r for r in rows if r.status == "missed"]
    # The day after, it is missed: what was due, nothing paid, the balance as it was.
    sm, rows = L.summary(t, pays, [], dt.date(2026, 10, 17), "recorded")
    missed = [r for r in rows if r.status == "missed"]
    assert [r.date for r in missed] == [dt.date(2026, 10, 1)] and missed[0].past
    m = missed[0]
    assert m.interest == L.cents(owed * D("0.005")) and m.escrow == D(300)
    assert m.principal + m.interest == L.scheduled_payment(t) and m.balance == owed
    assert sm.balance == owed and sm.missed == 1 and sm.overdue == m.payment
    assert sm.nextDate == dt.date(2026, 11, 1)
    # Assumed as scheduled, the same day counts as paid: nothing missed, the balance lower.
    a, arows = L.summary(t, pays, [], dt.date(2026, 10, 17), "assumed")
    assert a.missed == 0 and a.balance < owed
    assert [r.status for r in arows if r.past][-2:] == ["paid", "assumed"]


def test_missed_months_no_longer_vanish_and_their_payments_are_overdue():
    """CR3-413: recorded here, the months after the last payment are each a missed row with
    what was due, and the schedule ahead starts from the next payment day, not a month after
    the last payment with one month's interest."""
    t = mortgage_terms(start=dt.date(2026, 1, 1), escrowTax=D(300), pmi=D(90))
    pays = _monthly_pays(t, 3)  # Feb, Mar, Apr
    sm, rows = L.summary(t, pays, [], dt.date(2026, 10, 13), "recorded")
    days = [r.date for r in rows[:10]]
    assert days == [L.add_months(t.start, i) for i in range(1, 11)], "no month left out"
    assert [r.status for r in rows[:10]] == ["paid"] * 3 + ["missed"] * 5 + ["ahead"] * 2
    missed = rows[3:8]
    assert sm.missed == 5 and sm.overdue == sum(r.payment for r in missed)
    assert all(r.pmi == 90 and r.escrow == 300 and r.balance == sm.balance for r in missed)
    # Oct 1 is still in its grace: due next, from the balance as it was.
    assert sm.nextDate == dt.date(2026, 10, 1) and rows[8].interest == missed[0].interest


def test_a_late_payment_pays_the_oldest_day_missed():
    t = mortgage_terms(start=dt.date(2026, 1, 1))
    pi = L.scheduled_payment(t)
    feb = L.split_for(t, [], [], dt.date(2026, 2, 1), pi)
    late = L.split_for(t, [feb], [], dt.date(2026, 3, 25), pi)  # March's, after its grace
    sm, _ = L.summary(t, [feb, late], [], dt.date(2026, 4, 10), "recorded")
    assert sm.missed == 0 and sm.nextDate == dt.date(2026, 4, 1)
    sm, _ = L.summary(t, [feb, late], [], dt.date(2026, 4, 17), "recorded")
    assert sm.missed == 1 and sm.nextDate == dt.date(2026, 5, 1)
    # An extra payment in a month already paid pays no other day.
    extra = L.split_for(t, [feb], [], dt.date(2026, 2, 10), D(5000))
    sm, _ = L.summary(t, [feb, extra], [], dt.date(2026, 3, 20), "recorded")
    assert sm.missed == 1 and sm.nextDate == dt.date(2026, 4, 1)


def test_a_daily_interest_loans_missed_and_assumed_days():
    t = L.Terms(
        principal=D(25000), start=dt.date(2026, 1, 15), months=60, rate=D("7.3"), method="daily"
    )
    feb = L.split_for(t, [], [], dt.date(2026, 2, 15), D(500))
    owed = D(25000) - feb.principal
    sm, rows = L.summary(t, [feb], [], dt.date(2026, 4, 5), "recorded")
    # Mar 15 missed: its interest is the days since the last payment; the next row's accrues
    # from Mar 15, the missed month's interest owed with it and not added to the balance.
    m = next(r for r in rows if r.status == "missed")
    assert m.date == dt.date(2026, 3, 15) and m.balance == owed
    assert m.interest == L.cents(owed * D("0.073") * 28 / 365)
    nxt = next(r for r in rows if not r.past)
    assert nxt.date == dt.date(2026, 4, 15) and nxt.interest == L.cents(
        owed * D("0.073") * 31 / 365
    )
    assert sm.overdue == m.payment == m.principal + m.interest
    # Assumed, Mar 15 is paid as the schedule says, its interest the same days.
    a, arows = L.summary(t, [feb], [], dt.date(2026, 4, 5), "assumed")
    assumed = next(r for r in arows if r.status == "assumed")
    assert assumed.interest == m.interest and a.balance == owed - assumed.principal


def test_settling_twice_adds_nothing_and_a_payment_recorded_takes_the_assumed_ones_place():
    t = mortgage_terms(start=dt.date(2026, 1, 1))
    today = dt.date(2026, 10, 13)
    once = L.settle(t, [], [], today, today)
    assert len(once) == 9 and L.settle(t, once, [], today, today) == once
    pi = L.scheduled_payment(t)
    # Recorded for Jun 3, whatever the setting: June's assumed payment goes, and those before
    # stay (assumed; recorded here, the days before the first payment recorded are too), so
    # the split is from the balance after May: June's own.
    p = L.split_new(t, once, [], dt.date(2026, 6, 3), pi)
    assert (p.interest, p.principal) == (once[4].interest, once[4].principal)
    assert p.interest < L.split_for(t, [], [], dt.date(2026, 6, 3), pi).interest
    # Settled with it, it is the one on June's day, the days before it still assumed.
    p.transactionId = "Txn_june"
    for mode in ("assumed", "recorded"):
        after = L.settle(t, [p], [], today, L.assumed_before(t, [p], today, mode))
        assert [x.date.month for x in after if x.assumed] == (
            [2, 3, 4, 5, 7, 8, 9, 10] if mode == "assumed" else [2, 3, 4, 5]
        )


def test_automatic_reads_as_recorded_once_a_payment_or_a_connection_says_so():
    assert L.automatic(False, False) == "assumed"
    assert L.automatic(True, False) == L.automatic(False, True) == "recorded"


def test_the_payments_setting_through_the_api(server, frozen):
    make_user(server, "alice")
    c = sign_in(server, "alice")
    loan = new_account(c, name="Home", type="mortgage")
    home = {"principal": "300000", "startDate": "2026-01-01", "termMonths": 360, "rate": "6"}
    v = saved(terms(c, loan["id"], **home, escrowTax="300"))
    assert v["terms"]["paymentsMode"] is None
    assert (v["paymentsResolved"], v["paymentsAutomatic"]) == ("assumed", "assumed")
    assert v["missed"] == 0 and {r["status"] for r in v["rows"] if r["past"]} == {"assumed"}
    # Recorded here with nothing recorded yet: the record hasn't started, so nothing is
    # missed; the days before a first payment count as paid as scheduled (S1.9.3).
    v = saved(terms(c, loan["id"], paymentsMode="recorded"))
    assert v["terms"]["paymentsMode"] == "recorded" and v["paymentsResolved"] == "recorded"
    assert v["paymentsAutomatic"] == "assumed"
    assert v["missed"] == 0 and {r["status"] for r in v["rows"] if r["past"]} == {"assumed"}
    assert v["nextDate"] == "2026-11-01" and v["overdue"] == "0.00"
    assert v["balance"] == [r for r in v["rows"] if r["past"]][-1]["balance"]
    r = terms(c, loan["id"], paymentsMode="sometimes")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "paymentsMode"
    # Back to Automatic, then a payment recorded: Automatic reads as recorded here.
    saved(terms(c, loan["id"], paymentsMode=None))
    saved(loan_payment(c, loan["id"], "2026-02-01", "2098.65"))
    v = c.get(f"/ui/api/accounts/{loan['id']}/loan").json()
    assert (v["paymentsResolved"], v["paymentsAutomatic"]) == ("recorded", "recorded")
    # The record starts with February's: March to September are missed, $2,098.65 each
    # overdue, and October, in its grace, is due next.
    assert v["balance"] == "299701.35" and v["missed"] == 7 and v["overdue"] == "14690.55"
    assert [r["status"] for r in v["rows"][:9]] == ["paid"] + ["missed"] * 7 + ["ahead"]
    assert v["nextDate"] == "2026-10-01"
    # The loan counts in net worth as the balance the setting reads.
    assert c.get(f"/ui/api/accounts/{loan['id']}").json()["balance"] == "-299701.35"
    v = saved(terms(c, loan["id"], paymentsMode="assumed"))
    assert v["missed"] == 0 and D(v["balance"]) < D("299701.35")
    assert D(c.get(f"/ui/api/accounts/{loan['id']}").json()["balance"]) == -D(v["balance"])


def test_recorded_here_counts_from_the_first_payment_recorded():
    """S1.9.3: the days before the first payment recorded count as paid as scheduled; only
    the gaps after it are missed; with none recorded, none is missed."""
    t = mortgage_terms(start=dt.date(2024, 3, 1))
    today = dt.date(2026, 10, 13)
    sm, rows = L.summary(t, [], [], today, "recorded")
    assert sm.missed == 0 and {r.status for r in rows if r.past} == {"assumed"}
    assert sm.nextDate == dt.date(2026, 11, 1)
    # Recorded from Jun 2026, with July left out.
    assumed = L.settle(t, [], [], dt.date(2026, 6, 1), dt.date(2026, 6, 1))
    pays = list(assumed)
    for m in (6, 8, 9):
        pays.append(L.split_for(t, pays, [], dt.date(2026, m, 1), L.scheduled_payment(t)))
    recorded = [p for p in pays if not p.assumed]
    sm, rows = L.summary(t, recorded, [], today, "recorded")
    past = [r for r in rows if r.past]
    # One behind: August's payment paid July, the oldest missed, and September's August, so
    # September's day is the one missed.
    assert [r.status for r in past] == ["assumed"] * 26 + ["paid"] * 3 + ["missed"]
    assert past[-1].date == dt.date(2026, 9, 1) and sm.missed == 1
    assert sm.overdue == past[-1].payment and sm.nextDate == dt.date(2026, 10, 1)


def test_a_heloc_not_yet_drawn_has_nothing_a_late_payment_goes_back_to():
    """Days with nothing owed before the first payment recorded are settled: a payment pays
    its own day, not an undrawn month's."""
    t = L.Terms(principal=D(0), start=dt.date(2026, 1, 1), months=240, rate=D(8), drawMonths=120)
    draws = [(dt.date(2026, 4, 10), D(30000))]
    may = L.split_for(t, [], draws, dt.date(2026, 5, 1), D(200))
    june = L.split_for(t, [may], draws, dt.date(2026, 6, 1), D(200))
    sm, rows = L.summary(t, [may, june], draws, dt.date(2026, 7, 10), "recorded")
    assert sm.missed == 0 and sm.nextDate == dt.date(2026, 7, 1)
    assert [r.status for r in rows if r.past] == ["paid", "paid"]
