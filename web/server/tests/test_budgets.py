"""Budgets (requirements S7.1–S7.5)."""

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

import pytest
from conftest import make_user, sign_in
from test_accounts import add, new_account

from moolakata import clock
from moolakata.budgets import recurring

T0 = dt.datetime(2026, 10, 20, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def cats(c) -> dict[str, str]:
    return {x["path"]: x["id"] for x in c.get("/ui/api/categories").json()["items"]}


def setup_budget(server):
    make_user(server, "alice")
    c = sign_in(server, "alice")
    acct = new_account(c)
    cat = cats(c)
    r = c.post("/ui/api/budgets", json={"name": "Household", "accountIds": [acct["id"]]})
    assert r.status_code == 201, r.text
    return c, acct, cat, r.json()


def plan(c, budget, month, lines):
    r = c.put(f"/ui/api/budgets/{budget['id']}/plan", json={"month": month, "lines": lines})
    assert r.status_code == 200, r.text
    return r.json()


def month(c, budget, m):
    r = c.get(f"/ui/api/budgets/{budget['id']}/month", params={"month": m})
    assert r.status_code == 200, r.text
    return r.json()


def row(view, label):
    return next(r for r in view["rows"] if r["label"] == label)


def test_planned_actual_and_remaining(server, frozen):
    c, acct, cat, b = setup_budget(server)
    food, groceries = cat["Food"], cat["Food › Groceries"]
    plan(
        c,
        b,
        "2026-10-01",
        [
            {"categoryId": food, "amount": "600.00"},
            {"categoryId": cat["Income › Salary"], "amount": "5000.00"},
        ],
    )
    add(c, acct["id"], "-250.00", "2026-10-03", payee="Kroger", categoryId=groceries)
    add(
        c,
        acct["id"],
        "-300.00",
        "2026-10-10",
        payee="Chipotle",
        categoryId=cat["Food › Dining out"],
    )
    add(
        c,
        acct["id"],
        "5100.00",
        "2026-10-01",
        payee="Acme Payroll",
        categoryId=cat["Income › Salary"],
    )
    add(
        c,
        acct["id"],
        "-80.00",
        "2026-10-11",
        payee="Shell",
        categoryId=cat["Transportation › Fuel"],
    )
    add(c, acct["id"], "-12.00", "2026-10-12", payee="Mystery")
    v = month(c, b, "2026-10")
    f = row(v, "Food")
    assert (f["planned"], f["actual"], f["remaining"], f["state"]) == (
        "600.00",
        "550.00",
        "50.00",
        "near",
    )
    assert row(v, "Income › Salary")["actual"] == "5100.00"
    assert v["income"] == "5100.00" and v["spent"] == "630.00"
    assert v["plannedSpending"] == "600.00" and v["expectedIncome"] == "5000.00"
    assert [(u["label"], u["spent"]) for u in v["unplanned"]] == [
        ("Transportation › Fuel", "80.00")
    ]
    assert v["uncategorised"] == 1 and v["daysLeft"] == 12


def test_a_plan_change_keeps_past_months(server, frozen):
    c, _, cat, b = setup_budget(server)
    food = cat["Food"]
    plan(c, b, "2026-08-01", [{"categoryId": food, "amount": "500.00"}])
    plan(c, b, "2026-10-01", [{"categoryId": food, "amount": "650.00"}])
    assert row(month(c, b, "2026-09"), "Food")["planned"] == "500.00"
    assert row(month(c, b, "2026-10"), "Food")["planned"] == "650.00"
    # Taken out of the plan from November.
    plan(c, b, "2026-11-01", [])
    assert month(c, b, "2026-11")["rows"] == []
    assert row(month(c, b, "2026-10"), "Food")["planned"] == "650.00"


def test_rollover_carries_the_remainder(server, frozen):
    c, acct, cat, b = setup_budget(server)
    food = cat["Food"]
    plan(c, b, "2026-08-01", [{"categoryId": food, "amount": "500.00", "rollover": True}])
    add(c, acct["id"], "-400.00", "2026-08-05", categoryId=food)  # 100 left
    add(c, acct["id"], "-700.00", "2026-09-05", categoryId=food)  # 600 available, 100 over
    oct_ = row(month(c, b, "2026-10"), "Food")
    assert oct_["carried"] == "-100.00" and oct_["planned"] == "400.00"


def test_a_yearly_line_compares_with_the_year_to_date(server, frozen):
    c, acct, cat, b = setup_budget(server)
    travel = cat["Travel"]
    plan(c, b, "2026-01-01", [{"categoryId": travel, "amount": "3000.00", "cadence": "year"}])
    add(c, acct["id"], "-1200.00", "2026-03-05", categoryId=travel)
    add(c, acct["id"], "-2000.00", "2026-10-05", categoryId=travel)
    t = row(month(c, b, "2026-10"), "Travel")
    assert (t["actual"], t["state"], t["cadence"]) == ("3200.00", "over", "year")


def test_matched_transfers_and_splits(server, frozen):
    c, acct, cat, b = setup_budget(server)
    plan(c, b, "2026-10-01", [{"categoryId": cat["Food"], "amount": "300.00"}])
    r = c.post(
        "/ui/api/transactions",
        json={
            "accountId": acct["id"],
            "date": "2026-10-04",
            "amount": "-100.00",
            "payee": "Target",
            "splits": [
                {"amount": "-60.00", "categoryId": cat["Food › Groceries"]},
                {"amount": "-40.00", "categoryId": cat["Personal › Clothing"]},
            ],
        },
    )
    assert r.status_code == 201, r.text
    assert row(month(c, b, "2026-10"), "Food")["actual"] == "60.00"


def test_plan_checks_its_lines(server, frozen):
    c, _, cat, b = setup_budget(server)
    r = c.put(
        f"/ui/api/budgets/{b['id']}/plan",
        json={
            "month": "2026-10-01",
            "lines": [
                {"categoryId": cat["Food"], "amount": "-5.00"},
                {"categoryId": "Cat_nope", "amount": "5.00"},
            ],
        },
    )
    assert r.status_code == 422
    assert {e["field"] for e in r.json()["errors"]} == {"lines.0.amount", "lines.1.categoryId"}


def test_a_household_budget_is_shared_with_a_group(server, frozen, admin_client):
    c, _, cat, b = setup_budget(server)
    make_user(server, "bob")
    bob = sign_in(server, "bob")
    assert bob.get(f"/ui/api/budgets/{b['id']}/month").status_code == 404
    groups = admin_client.post(
        "/ui/api/groups",
        json={
            "name": "Household",
            "memberIds": [
                u["id"]
                for u in admin_client.get("/ui/api/users").json()["items"]
                if u["username"] in ("alice", "bob")
            ],
        },
    ).json()
    r = c.put(
        f"/ui/api/shares/budget/{b['id']}",
        json={"users": {}, "groups": {groups["id"]: "write"}},
    )
    assert r.status_code == 200, r.text
    assert [x["name"] for x in bob.get("/ui/api/budgets").json()["items"]] == ["Household"]
    # Write: the plan, not the accounts or the budget itself.
    plan(bob, b, "2026-10-01", [{"categoryId": cat["Food"], "amount": "400.00"}])
    r = bob.patch(
        f"/ui/api/budgets/{b['id']}", json={"accountIds": []}, headers={"If-Match": '"1"'}
    )
    assert r.status_code == 403
    assert bob.delete(f"/ui/api/budgets/{b['id']}").status_code == 403


def test_cash_flow_and_trends(server, frozen):
    c, acct, cat, b = setup_budget(server)
    plan(c, b, "2026-08-01", [{"categoryId": cat["Food"], "amount": "500.00"}])
    add(c, acct["id"], "4000.00", "2026-10-01", categoryId=cat["Income › Salary"])
    add(c, acct["id"], "-1500.00", "2026-10-02", categoryId=cat["Housing › Rent"])
    add(c, acct["id"], "-450.00", "2026-10-03", categoryId=cat["Food › Groceries"])
    f = c.get(f"/ui/api/budgets/{b['id']}/cash-flow", params={"month": "2026-10"}).json()
    assert f["sources"] == [{"name": "Salary", "amount": "4000.00"}]
    assert f["uses"] == [
        {"name": "Saved", "amount": "2050.00"},
        {"name": "Housing", "amount": "1500.00"},
        {"name": "Food", "amount": "450.00"},
    ]
    t = c.get(
        f"/ui/api/budgets/{b['id']}/trends",
        params={"month": "2026-10", "category": cat["Food"], "months": 3},
    ).json()["items"]
    assert [(p["month"], p["planned"], p["actual"]) for p in t] == [
        ("2026-08-01", "500.00", "0.00"),
        ("2026-09-01", "500.00", "0.00"),
        ("2026-10-01", "500.00", "450.00"),
    ]


def _t(day, amount, payee, account="a"):
    return SimpleNamespace(
        date=day, amount=Decimal(amount), payee=payee, accountId=account, transferId=None
    )


def test_recurring_finds_series_and_flags_missed_and_changed():
    d = dt.date
    txns = [
        *[_t(d(2026, m, 5), "-15.49", f"NETFLIX.COM {m}88") for m in range(4, 11)],
        *[_t(d(2026, m, 1), "-175.00", "City Utilities") for m in range(5, 10)],
        _t(d(2026, 10, 1), "-189.00", "City Utilities"),
        *[
            _t(d(2026, 1, 2) + dt.timedelta(days=14 * i), "4820.00", "Acme Payroll")
            for i in range(20)
        ],
        *[_t(d(2026, m, 3), "-11.99", "Spotify") for m in range(5, 9)],
        *[_t(d(2026, m, 18), f"-{90 + 17 * m}.00", "Power & Water") for m in range(3, 10)],
        *[
            _t(d(2026, m, day), "2860.00", "Bluebird Payroll")
            for m in range(4, 11)
            for day in (1, 15)
        ],
        _t(d(2026, 3, 9), "-40.00", "Hardware store"),
        _t(d(2026, 6, 20), "-12.00", "Hardware store"),
        _t(d(2026, 9, 1), "-95.00", "Hardware store"),
    ]
    found = {x.payee.split()[0]: x for x in recurring.detect(txns, d(2026, 10, 20))}
    assert set(found) == {"NETFLIX.COM", "City", "Acme", "Spotify", "Power", "Bluebird"}
    assert not found["Power"].changed, "a bill that varies isn't flagged"
    assert found["Bluebird"].every == "twice a month"
    assert found["NETFLIX.COM"].every == "month" and not found["NETFLIX.COM"].missed
    assert found["City"].changed and found["City"].next == d(2026, 10, 31)
    assert found["Acme"].every == "2 weeks" and found["Acme"].usual == Decimal("4820.00")
    assert found["Spotify"].missed


def test_a_shared_budget_names_only_the_accounts_shared_with_its_viewer(server, frozen):
    # S7.1.1, S11.3.1: a receiver sees the owner's recurring payments, but the account behind
    # one is named only to someone it is shared with too.
    c, acct, _, b = setup_budget(server)
    for m in (7, 8, 9, 10):
        add(c, acct["id"], "-15.49", f"2026-{m:02d}-05", payee="Netflix")
    make_user(server, "bob")
    bob = sign_in(server, "bob")
    bob_id = bob.get("/ui/api/session").json()["user"]["id"]
    c.put(f"/ui/api/shares/budget/{b['id']}", json={"users": {bob_id: "read"}})
    (mine,) = [
        r for r in c.get(f"/ui/api/budgets/{b['id']}/recurring").json()["items"] if r["payee"]
    ]
    (theirs,) = bob.get(f"/ui/api/budgets/{b['id']}/recurring").json()["items"]
    assert mine["accountId"] == acct["id"] and mine["accountName"] == acct["name"]
    assert theirs["accountId"] is None and theirs["accountName"] == "an account not shared"
    c.put(f"/ui/api/shares/account/{acct['id']}", json={"users": {bob_id: "read"}})
    (theirs,) = bob.get(f"/ui/api/budgets/{b['id']}/recurring").json()["items"]
    assert theirs["accountName"] == acct["name"]


def test_a_matched_loan_payment_counts_at_the_bank_split_by_the_schedule(server, frozen):
    """A mortgage payment from a budget's checking account is a matched transfer to the loan,
    and counts by its parts: interest, escrow and the rest as spending, principal as saved
    (S1.9.7, S7.3.3)."""
    c, acct, cat, b = setup_budget(server)
    loan = new_account(c, name="Home", type="mortgage", institution="Rocket")
    r = c.put(
        f"/ui/api/accounts/{loan['id']}/loan",
        json={
            "principal": "300000",
            "startDate": "2026-09-01",
            "termMonths": 360,
            "rate": "6",
            "escrowTax": "300",
            "escrowInsurance": "100",
        },
    )
    assert r.status_code == 200, r.text
    r = c.post(
        f"/ui/api/accounts/{loan['id']}/loan/payments",
        json={"date": "2026-10-01", "amount": "2198.65", "fromAccountId": acct["id"]},
    )
    assert r.status_code == 201, r.text
    plan(c, b, "2026-10-01", [{"categoryId": cat["Loan payments"], "amount": "2200.00"}])
    v = month(c, b, "2026-10")
    lp = row(v, "Loan payments")
    assert lp["actual"] == "2198.65"
    assert v["spent"] == "1900.00" and v["saved"] == "298.65"


def test_a_loan_counted_whole_and_the_choice_checked(server, frozen):
    c, acct, cat, b = setup_budget(server)
    loan = new_account(c, name="Car", type="auto-loan", institution="Ally")
    terms = {"principal": "20000", "startDate": "2026-09-01", "termMonths": 60, "rate": "6"}
    bad = c.put(f"/ui/api/accounts/{loan['id']}/loan", json=terms | {"budgetCounting": "half"})
    assert bad.status_code == 422 and bad.json()["errors"][0]["field"] == "budgetCounting"
    whole = terms | {"budgetCounting": "whole", "budgetCategoryId": cat["Transportation"]}
    r = c.put(f"/ui/api/accounts/{loan['id']}/loan", json=whole)
    assert r.status_code == 200, r.text
    assert r.json()["terms"]["budgetCounting"] == "whole"
    c.post(
        f"/ui/api/accounts/{loan['id']}/loan/payments",
        json={"date": "2026-10-01", "amount": "386.66", "fromAccountId": acct["id"]},
    )
    v = month(c, b, "2026-10")
    assert v["spent"] == "386.66" and v["saved"] == "0.00"
    assert [(u["label"], u["spent"]) for u in v["unplanned"]] == [("Transportation", "386.66")]


def test_money_leaving_or_entering_the_budget(server, frozen):
    """A transfer between two of the budget's accounts counts nowhere; one to an account the
    budget doesn't count counts by its category, or waits to be sorted (S7.3.2)."""
    c, acct, cat, b = setup_budget(server)
    savings = new_account(c, name="Savings", type="savings", mask="2222")
    brokerage = new_account(c, name="Brokerage", type="brokerage", mask="3333")
    r = c.patch(
        f"/ui/api/budgets/{b['id']}",
        json={"accountIds": [acct["id"], savings["id"]]},
        headers={"If-Match": str(b["version"])},
    )
    assert r.status_code == 200, r.text
    # Inside the budget: nothing moved in or out.
    add(c, acct["id"], "-200.00", "2026-10-02", payee="To savings")
    add(c, savings["id"], "200.00", "2026-10-02", payee="From checking", kind="deposit")
    # Out to the brokerage: no category yet, then filed as savings.
    out = add(c, acct["id"], "-500.00", "2026-10-05", payee="To Fidelity")
    inn = add(c, brokerage["id"], "500.00", "2026-10-05", payee="From checking", kind="deposit")
    assert inn["transferId"] == out["id"]
    # In from the brokerage, filed as income.
    back = add(
        c,
        acct["id"],
        "150.00",
        "2026-10-20",
        payee="From Fidelity",
        categoryId=cat["Income › Other income"],
    )
    pair = add(c, brokerage["id"], "-150.00", "2026-10-20", payee="To checking", kind="withdrawal")
    assert pair["transferId"] == back["id"]
    v = month(c, b, "2026-10")
    assert v["spent"] == "0.00" and v["saved"] == "0.00" and v["income"] == "150.00"
    assert [(m["otherAccountName"], m["amount"]) for m in v["moved"]] == [("Brokerage", "-500.00")]
    r = c.patch(
        f"/ui/api/transactions/{out['id']}",
        json={"categoryId": cat["Savings › Investing"]},
        headers={"If-Match": str(c.get(f"/ui/api/transactions/{out['id']}").json()["version"])},
    )
    assert r.status_code == 200, r.text
    v = month(c, b, "2026-10")
    assert v["saved"] == "500.00" and v["moved"] == []
    # The accounts named when the budget is edited: two or more transfers in a year.
    add(c, acct["id"], "-75.00", "2026-10-12", payee="To Fidelity")
    add(c, brokerage["id"], "75.00", "2026-10-12", payee="From checking", kind="deposit")
    named = c.get("/ui/api/budgets/left-out", params={"accountIds": [acct["id"], savings["id"]]})
    assert named.status_code == 200, named.text
    assert [(x["name"], x["transfers"]) for x in named.json()["items"]] == [("Brokerage", 2)]


def test_a_refund_lowers_spending_in_the_month_it_lands(server, frozen):
    c, acct, cat, b = setup_budget(server)
    plan(c, b, "2026-09-01", [{"categoryId": cat["Food"], "amount": "300.00"}])
    add(c, acct["id"], "-120.00", "2026-09-28", payee="Kroger", categoryId=cat["Food › Groceries"])
    add(c, acct["id"], "-90.00", "2026-10-03", payee="Kroger", categoryId=cat["Food › Groceries"])
    add(
        c,
        acct["id"],
        "40.00",
        "2026-10-06",
        payee="Kroger refund",
        categoryId=cat["Food › Groceries"],
    )
    assert row(month(c, b, "2026-09"), "Food")["actual"] == "120.00"
    assert row(month(c, b, "2026-10"), "Food")["actual"] == "50.00"


def test_cash_and_payment_apps(server, frozen):
    """Cash on hand and payment apps are banking accounts (S1.1); cash taken out pairs with the
    cash account's deposit, and counts as Cash when that account is outside the budget
    (S7.3.2). Cash expects no statements and has no Reconcile tab (S1.11)."""
    c, acct, cat, b = setup_budget(server)
    cash = new_account(c, name="Wallet cash", type="cash", institution="", mask="")
    venmo = new_account(c, name="Venmo", type="payment-app", institution="Venmo", mask="")
    assert cash["group"] == venmo["group"] == "banking"
    assert cash["statementIntervalDefault"] == "none" and not cash["reconcilable"]
    assert venmo["reconcilable"]
    out = add(c, acct["id"], "-60.00", "2026-10-07", payee="ATM")
    dep = add(c, cash["id"], "60.00", "2026-10-07", payee="From the ATM", kind="deposit")
    assert dep["transferId"] == out["id"]
    # Money sent to the app, filed by its category on the bank's side.
    add(
        c, acct["id"], "-45.00", "2026-10-09", payee="To Venmo", categoryId=cat["Food › Dining out"]
    )
    add(c, venmo["id"], "45.00", "2026-10-09", payee="From checking", kind="deposit")
    v = month(c, b, "2026-10")
    assert [(u["label"], u["spent"]) for u in v["unplanned"]] == [
        ("Cash", "60.00"),
        ("Food › Dining out", "45.00"),
    ]
    assert v["moved"] == []
