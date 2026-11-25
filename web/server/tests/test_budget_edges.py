"""A budget's figures at the edges of their data (requirements S7.1–S7.14): a plan line naming
something since deleted, what a reviewed month says changed, a loan payment the schedule doesn't
place, a budget no longer shared, the estimate's leave-outs, and what the recurring and kept
months do with the odd case."""

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

import pytest
from conftest import make_user, sign_in
from edits import budget_accounts, change, loan_payment, make, remove, saved, share, terms
from test_accounts import add, new_account
from test_budgets import month, plan, row, save_plan, setup_budget
from test_reserves import put_plan, reserves_on

from moolakata import clock
from moolakata.budgets import recurring

T0 = dt.datetime(2026, 10, 20, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def _ok(r):
    assert r.status_code == 200, r.text
    return r


# ---------- a plan line naming something deleted ----------


def test_a_planned_category_is_never_deleted_from_under_its_line(server, frozen):
    """S7.2.3: a category a plan line names is in use, so it is merged, never deleted; the line
    keeps counting it."""
    c, acct, _, b = setup_budget(server)
    mine = make(c, "Cat", name="Boat", kind="expense").json()
    plan(c, b, "2026-10-01", [{"categoryId": mine["id"], "amount": "80.00"}])
    r = remove(c, "Cat", mine)
    assert r.status_code == 422, r.text
    assert r.json()["errors"][0]["code"] == "category-in-use"
    add(c, acct["id"], "-30.00", "2026-10-03", payee="Marina", categoryId=mine["id"])
    assert row(month(c, b, "2026-10"), "Boat")["actual"] == "30.00"


def test_a_savings_line_names_its_projection_only_while_it_is_there(server, frozen):
    """S7.2.1: the line shows its active projection's monthly contribution; once the projection
    is deleted, or another made active in its place, the line stands alone."""
    c, acct, cat, b = setup_budget(server)

    def projection(name, monthly):
        r = make(c, "Prjct", name=name, goal="savings",
                 builtOn={"kind": "accounts", "ids": [acct["id"]]},
                 inputs={"target": 150000, "date": "2030-01-01", "monthly": monthly,
                         "fees": 0.1})  # fmt: skip
        pid = _ok(r).json()["id"]
        _ok(c.post(f"/ui/api/projections/{pid}/activate"))
        return c.get(f"/ui/api/projections/{pid}").json()

    nest = projection("Nest egg", 650)
    line = {
        "categoryId": cat["Savings › Investing"],
        "amount": "500.00",
        "projectionId": nest["id"],
    }
    r = row(plan(c, b, "2026-10-01", [line]), "Savings › Investing")
    assert (r["projectionName"], r["projectionMonthly"]) == ("Nest egg", "650.00")
    saved(remove(c, "Prjct", nest))
    r = row(month(c, b, "2026-10"), "Savings › Investing")
    assert (r["planned"], r["projectionName"], r["projectionMonthly"]) == ("500.00", None, None)


def test_a_retirement_projection_puts_in_a_twelfth_of_its_yearly_contribution(server, frozen):
    """S7.2.1: a retirement projection's contribution is yearly; the line shows a month's."""
    c, _, cat, b = setup_budget(server)
    r = make(c, "Prjct", name="Retire at 62", goal="retirement",
             builtOn={"kind": "typed", "amount": "1000"},
             inputs={"people": [{"birthYear": 1980}],
                     "contribution": {"amount": 7800, "growth": 0}, "horizonAge": 95,
                     "fees": 0.1})  # fmt: skip
    pid = _ok(r).json()["id"]
    _ok(c.post(f"/ui/api/projections/{pid}/activate"))
    line = {"categoryId": cat["Savings › Retirement"], "amount": "600.00", "projectionId": pid}
    r = row(plan(c, b, "2026-10-01", [line]), "Savings › Retirement")
    assert (r["projectionName"], r["projectionMonthly"]) == ("Retire at 62", "650.00")


def test_a_reserve_held_in_an_account_since_deleted_is_held_nowhere(server, frozen):
    """S7.1.7, S7.10.4: a deleted account is a correction, counted in no month; a reserve held in
    it keeps its balance, held nowhere: Where the money is lists no account for it."""
    c, acct, cat, b = setup_budget(server)
    savings = new_account(c, name="Ally", type="savings", mask="2222")
    reserves_on(c, b)
    _ok(budget_accounts(c, b, [acct["id"], savings["id"]]))
    roof = cat["Housing › Maintenance"]
    line = {"categoryId": roof, "amount": "150", "target": "900", "heldInId": savings["id"]}
    _ok(put_plan(c, b, "2026-10-01", [line]))
    path = f"/ui/api/budgets/{b['id']}/where"
    assert [h["accountId"] for h in c.get(path, params={"month": "2026-10"}).json()["heldIn"]] == [
        savings["id"]
    ]
    saved(remove(c, "Acct", c.get(f"/ui/api/accounts/{savings['id']}").json(), confirm=True))
    assert c.get(path, params={"month": "2026-10"}).json()["heldIn"] == []
    r = row(month(c, b, "2026-10"), "Housing › Maintenance")
    assert (r["balance"], r["target"], r["heldInId"]) == ("150.00", "900.00", None)


# ---------- what a reviewed month says changed (S7.14) ----------


def test_a_reviewed_month_names_each_line_planned_since_dropped_or_changed(server, frozen):
    c, _, cat, b = setup_budget(server)
    food, fun, travel = cat["Food"], cat["Entertainment"], cat["Travel"]
    plan(c, b, "2026-09-01", [{"categoryId": food, "amount": "300.00"},
                              {"categoryId": fun, "amount": "100.00"}])  # fmt: skip
    base = f"/ui/api/budgets/{b['id']}/review"
    _ok(c.post(base, json={"month": "2026-09-01"}))
    _ok(save_plan(c, b, "2026-09-01", [{"categoryId": food, "amount": "350.00"},
                                       {"categoryId": travel, "amount": "50.00"}]))  # fmt: skip
    got = c.get(base, params={"month": "2026-09"}).json()["reviewed"]["changes"]
    assert sorted(got) == [
        "Entertainment: no longer planned",
        "Food: planned 300.00 then, 350.00 now",
        "Travel: planned since",
    ]


def test_a_reviewed_month_keeps_no_figures_for_one_it_is_no_longer_shared_with(server, frozen):
    """S7.14, S7.1.1: marked reviewed again after Bob's share ends, his figures are dropped and
    none kept for him; Jane's are hers still."""
    c, acct, cat, b = setup_budget(server)
    make_user(server, "bob")
    bob = sign_in(server, "bob")
    bob_id = bob.get("/ui/api/session").json()["user"]["id"]
    share(c, "budget", b["id"], users={bob_id: "read"})
    base = f"/ui/api/budgets/{b['id']}/review"
    _ok(c.post(base, json={"month": "2026-09-01"}))
    share(c, "budget", b["id"], users={bob_id: "none"})
    _ok(c.post(base, json={"month": "2026-09-01"}))
    add(c, acct["id"], "-20.00", "2026-09-10", payee="Kroger", categoryId=cat["Food"])
    got = c.get(base, params={"month": "2026-09"}).json()["reviewed"]
    assert got["changes"] == [
        "Food: spent 0.00 then, 20.00 now, outside the plan",
        "Spent: 0.00 then, 20.00 now",
    ]
    assert bob.get(base, params={"month": "2026-09"}).status_code == 404


def test_the_review_names_what_one_reserve_account_owes_another(server, frozen):
    """S7.14, S7.10.4: Ally paid $200 of a repair whose reserve Marcus holds: the review's loose
    ends give the $200 to move from Marcus to Ally."""
    c, acct, cat, b = setup_budget(server)
    reserves_on(c, b)
    ally = new_account(c, name="Ally", type="savings", mask="2222")
    marcus = new_account(c, name="Marcus", type="savings", mask="3333")
    _ok(budget_accounts(c, b, [acct["id"], ally["id"], marcus["id"]]))
    roof, repair = cat["Housing › Maintenance"], cat["Transportation › Car maintenance"]
    _ok(save_plan(c, b, "2026-09-01", [
        {"categoryId": roof, "amount": "300", "target": "5000", "heldInId": ally["id"]},
        {"categoryId": repair, "amount": "400", "target": "5000", "heldInId": marcus["id"]},
    ]))  # fmt: skip
    for to, amount in ((ally, "300.00"), (marcus, "400.00")):
        add(c, acct["id"], f"-{amount}", "2026-09-01", payee="Transfer out")
        add(c, to["id"], amount, "2026-09-01", payee="Transfer in", kind="deposit")
    add(c, ally["id"], "-200.00", "2026-09-05", payee="Midas", categoryId=repair)
    got = c.get(f"/ui/api/budgets/{b['id']}/review", params={"month": "2026-09"}).json()
    assert [(x["accountName"], x["toMove"], x["fromName"]) for x in got["toMove"]] == [
        ("Ally", "200.00", "Marcus")
    ]


# ---------- a budget no longer shared (S7.12) ----------


def test_a_budget_followed_no_longer_once_its_share_ends(server, frozen):
    """S7.12, S7.6: once Jane's share ends, the budget Bob followed is his active one no more:
    his dashboard has no budget card, and its alerts no longer reach him."""
    from moolakata import alerts

    c, acct, _, b = setup_budget(server)
    make_user(server, "bob")
    bob = sign_in(server, "bob")
    bob_id = bob.get("/ui/api/session").json()["user"]["id"]
    share(c, "budget", b["id"], users={bob_id: "read"})
    share(c, "account", acct["id"], users={bob_id: "read"})
    saved(change(bob, "User", bob.get("/ui/api/profile").json(), activeBudgetId=b["id"]))
    for m in (7, 8, 9, 10):
        add(c, acct["id"], "2000.00", f"2026-{m:02d}-01", payee="Acme Payroll")
    for m in (7, 8, 9):
        add(c, acct["id"], "-1000.00", f"2026-{m:02d}-25", payee="Oak Street Apts")
    add(c, acct["id"], "-5900.00", "2026-10-05", payee="Car repair")

    def dips(who):
        alerts.evaluate(server)
        return [x["title"] for x in who.get("/ui/api/alerts").json()["open"]
                if x["kind"] == "cash-short"]  # fmt: skip

    assert bob.get("/ui/api/dashboard").json()["budget"] is not None
    assert dips(bob) == ["Checking dips below $0 on the 25th"]
    share(c, "budget", b["id"], users={bob_id: "none"})
    assert bob.get("/ui/api/dashboard").json()["budget"] is None
    assert dips(bob) == []
    assert dips(c) == ["Checking dips below $0 on the 25th"]


# ---------- a loan payment the schedule doesn't place (S7.3.3) ----------


def _loan(c, principal):
    loan = new_account(c, name="Car", type="auto-loan", institution="Ally")
    saved(terms(c, loan["id"], principal=principal, startDate="2026-09-01", termMonths=12,
                rate="6"))  # fmt: skip
    return loan


def test_a_loan_payment_beyond_the_balance_counts_whole(server, frozen):
    """S7.3.3: a $1,500 payment on a $1,000 loan counts all $1,500 in the month, what pays the
    loan off and the rest alike."""
    c, acct, _, b = setup_budget(server)
    loan = _loan(c, "1000")
    saved(loan_payment(c, loan["id"], "2026-10-01", "1500.00", from_account=acct["id"]))
    v = month(c, b, "2026-10")
    assert Decimal(v["spent"]) + Decimal(v["saved"]) == Decimal("1500.00")


def test_a_payment_to_a_loan_with_no_terms_yet_counts_whole(server, frozen):
    """S7.3.3: a payment to a loan whose terms aren't set yet has no schedule to split it by:
    the month counts the whole of it, never nothing."""
    from edits import new_id

    c, acct, cat, b = setup_budget(server)
    loan = new_account(c, name="Car", type="auto-loan", institution="Ally")
    plan(c, b, "2026-10-01", [{"categoryId": cat["Loan payments"], "amount": "400.00"}])
    bank = new_id("Txn")
    day = {"date": "2026-10-01", "kind": "transfer"}
    ops = [{"op": "create", "entity": "Txn", "id": bank,
            "fields": {**day, "accountId": acct["id"], "amount": "-386.66", "payee": "Car"}},
           {"op": "create", "entity": "Txn", "id": new_id("Txn"),
            "fields": {**day, "accountId": loan["id"], "amount": "386.66", "payee": "Payment",
                       "transferWithId": bank}}]  # fmt: skip
    _ok(c.post("/ui/api/save", json={"ops": ops}))
    v = month(c, b, "2026-10")
    assert row(v, "Loan payments")["actual"] == "386.66"
    assert Decimal(v["spent"]) + Decimal(v["saved"]) == Decimal("386.66")
    assert v["moved"] == []


# ---------- the estimate's leave-outs (S7.1.5) ----------


def test_an_estimate_leaves_out_transfers_and_a_category_refunded_more_than_spent(server, frozen):
    c, acct, cat, b = setup_budget(server)
    between = make(c, "Cat", name="Between mine", kind="transfer").json()
    # Gifts are planned by the gift plans, never estimated (S7.3.6).
    add(c, acct["id"], "-75.00", "2026-07-08", payee="Toy store", categoryId=cat["Gifts"])
    for m in range(4, 10):
        add(c, acct["id"], "-310.00", f"2026-{m:02d}-05", payee="Kroger",
            categoryId=cat["Food › Groceries"])  # fmt: skip
        add(c, acct["id"], "-50.00", f"2026-{m:02d}-06", payee="Shuffle",
            categoryId=between["id"])  # fmt: skip
    add(c, acct["id"], "-20.00", "2026-05-07", payee="Store", categoryId=cat["Travel"])
    add(c, acct["id"], "90.00", "2026-06-07", payee="Refund", categoryId=cat["Travel"])
    r = _ok(c.get(f"/ui/api/budgets/{b['id']}/estimate", params={"months": 6}))
    assert [x["label"] for x in r.json()["items"]] == ["Food › Groceries"]


def test_gifts_planned_by_occasion_add_up_each_occasions_budget(server, frozen):
    """S7.3.6: a gift plan without a yearly budget plans its occasions' budgets."""
    c, _, cat, b = setup_budget(server)
    _ok(make(c, "GfPln", name="Emma Doe", sex="female",
             occasions=[{"kind": "holiday", "holiday": "christmas", "budget": "150"},
                        {"kind": "custom", "name": "First day of school", "month": 9,
                         "day": 1, "budget": "50"}]))  # fmt: skip
    plan(c, b, "2026-10-01", [{"categoryId": cat["Food"], "amount": "300.00"}])
    gifts = row(month(c, b, "2026-10"), "Gifts")
    assert (gifts["cadence"], gifts["planned"]) == ("year", "200.00")


# ---------- recurring and kept months, the odd case ----------


def _txns(*amounts, start=dt.date(2026, 1, 5)):
    return [
        SimpleNamespace(
            id=f"t{i}",
            date=start + dt.timedelta(days=30 * i),
            amount=Decimal(a),
            payee="Gym",
            accountId="a1",
            categoryId=None,
            transferId=None,
            pending=False,
            deleted=False,
        )
        for i, a in enumerate(amounts)
    ]


def test_payments_too_uneven_are_no_series():
    """S7.5: monthly payments that vary beyond the steady spread are no series."""
    assert recurring.detect(_txns("-10", "-90", "-30", "-200"), dt.date(2026, 5, 1)) == []
    assert len(recurring.detect(_txns("-30", "-30", "-31", "-30"), dt.date(2026, 5, 1))) == 1


def test_kept_months_are_dropped_oldest_first_past_the_limit(monkeypatch):
    from moolakata.budgets import cache

    monkeypatch.setattr(cache, "KEEP", 2)
    monkeypatch.setattr(cache, "_months", type(cache._months)())
    monkeypatch.setattr(cache, "_database", lambda s: 1)
    monkeypatch.setattr(cache.data_version, "read", lambda s: 1)
    monkeypatch.setattr(cache.data_version, "read_only", lambda s: True)
    for k in ("a", "b", "c"):
        assert cache.month(None, (k,), lambda k=k: k.upper()) == k.upper()
    assert list(cache._months.values()) == ["B", "C"]
