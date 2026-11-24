"""A budget's method, options and plan (requirements S7.1.3–S7.1.6, S7.2.1, S7.3.6)."""

import datetime as dt

import pytest
from edits import budget_accounts, edit, giving_plan, make, new_id, saved
from test_accounts import add, new_account
from test_budgets import month, plan, row, save_plan, setup_budget

from moolakata import clock

T0 = dt.datetime(2026, 10, 20, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def change(c, b, **body):
    return edit(c, "Bdgt", f"/ui/api/budgets/{b['id']}", **body)


def test_a_method_and_options_chosen_when_made(server, frozen):
    c, acct, _, b = setup_budget(server)
    assert (b["method"], b["reserves"], b["moves"], b["startMonth"]) == (
        "tracking",
        False,
        False,
        "2026-10-01",
    )
    r = make(c, "Bdgt", name="Try", method="zero")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "method"
    r = make(c, "Bdgt", name="Envelopes", method="envelope", accountIds=[acct["id"]])
    env = r.json()
    assert env["method"] == "envelope" and env["moves"]
    assert change(c, env, moves=False).status_code == 422
    assert saved(change(c, b, reserves=True))["reserves"]


def test_where_money_comes_from_is_worked_out(server, frozen):
    """A card's paying account is learned from its payments; where money for a savings
    account moves from, from its transfers in; either can be chosen (S7.1.6)."""
    c, acct, _, b = setup_budget(server)
    other = new_account(c, name="John's checking", mask="5555")
    card = new_account(c, name="Visa", type="credit-card", mask="1111")
    savings = new_account(c, name="Ally", type="savings", mask="2222")
    add(c, acct["id"], "3000.00", "2026-09-01", payee="Payroll")
    for day in ("2026-08-03", "2026-09-03"):
        add(c, other["id"], "-400.00", day, payee="Card payment")
        add(c, card["id"], "400.00", day, payee="Thank you", kind="deposit")
    add(c, acct["id"], "-250.00", "2026-09-10", payee="To Ally")
    add(c, savings["id"], "250.00", "2026-09-10", payee="From checking", kind="deposit")
    ids = [acct["id"], other["id"], card["id"], savings["id"]]
    assert budget_accounts(c, b, ids).status_code == 200

    def roles():
        got = c.get(f"/ui/api/budgets/{b['id']}").json()["roles"]
        return {x["accountId"]: x for x in got}

    assert roles()[card["id"]]["paidFromId"] == other["id"]
    assert roles()[card["id"]]["paidFromLearned"]
    assert roles()[savings["id"]]["movedFromId"] == acct["id"]
    r = budget_accounts(c, b, ids, roles={savings["id"]: {"movedFromId": other["id"]}})
    assert r.status_code == 200, r.text
    assert roles()[savings["id"]]["movedFromId"] == other["id"]
    assert not roles()[savings["id"]]["movedFromProposed"]
    bad = budget_accounts(c, b, ids, roles={savings["id"]: {"movedFromId": "Acct_nope"}})
    assert bad.status_code == 422


def test_gifts_and_giving_are_planned_by_their_plans(server, frozen):
    c, acct, cat, b = setup_budget(server)
    r = make(c, "GfPln", name="Lisa Doe", sex="female", giftBudget="600")
    assert r.status_code == 200, r.text
    r = giving_plan(c, 2026, targetKind="amount", amount="1200")
    assert r.status_code == 200, r.text
    add(c, acct["id"], "-80.00", "2026-03-04", payee="Toy store", categoryId=cat["Gifts"])
    v = month(c, b, "2026-10")
    gifts, giving = row(v, "Gifts"), row(v, "Giving")
    assert (gifts["planned"], gifts["actual"], gifts["cadence"], gifts["fromPlan"]) == (
        "600.00",
        "80.00",
        "year",
        "gifts",
    )
    assert giving["planned"] == "1200.00" and giving["fromPlan"] == "giving"
    r = save_plan(c, b, "2026-10-01", [{"categoryId": cat["Gifts"], "amount": "50"}])
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "planned-elsewhere"


def test_a_plan_budgeted_per_occasion_counts_its_birthday_and_wedding(server, frozen):
    """S7.3.6, S7.7.1: with no yearly budget, the Gifts line plans the year's occasion
    budgets, the birthday's and the wedding anniversary's among them; a yearly budget, even
    of nothing, is the plan's whole year."""
    from test_people import me, relate

    c, _, _, b = setup_budget(server)
    christmas = {"kind": "holiday", "holiday": "christmas", "budget": "40"}
    bob = make(c, "GfPln", name="Bob Lee", sex="male", birthMonth=5, birthDay=1,
               birthdayBudget="60", weddingBudget="90", occasions=[christmas]).json()  # fmt: skip
    relate(c, me(c), bob["personId"], "spouse", fromDate="2009-06-14")
    assert row(month(c, b, "2026-10"), "Gifts")["planned"] == "190.00"
    saved(edit(c, "GfPln", f"/ui/api/gift-plans/{bob['id']}", giftBudget="0"))
    assert row(month(c, b, "2026-10"), "Gifts")["planned"] == "0.00"


def test_one_who_writes_the_budget_cant_type_what_the_owners_plans_set(server, frozen):
    """S7.3.6, S7.1.1: Gifts and Giving come from the owner's gift and giving plans, never
    typed, for one the budget is shared with at Write too, though those plans aren't shared
    with them."""
    from conftest import make_user, sign_in
    from edits import share

    c, _, cat, b = setup_budget(server)
    assert make(c, "GfPln", name="Lisa Doe", sex="female", giftBudget="600").status_code == 200
    assert giving_plan(c, 2026, targetKind="amount", amount="1200").status_code == 200
    bob_id = make_user(server, "bob").id
    bob = sign_in(server, "bob")
    assert share(c, "budget", b["id"], users={bob_id: "write"}).status_code == 200
    for name in ("Gifts", "Giving"):
        r = save_plan(bob, b, "2026-10-01", [{"categoryId": cat[name], "amount": "50"}])
        assert r.status_code == 422, (name, r.text)
        assert r.json()["errors"][0]["code"] == "planned-elsewhere"


def test_a_category_under_giving_counts_in_the_giving_line(server, frozen):
    """S7.3.6, S7.1.2: a donation filed under Giving › Church counts against the giving plan's
    Giving line, and nowhere outside the plan."""
    c, acct, cat, b = setup_budget(server)
    assert giving_plan(c, 2026, targetKind="amount", amount="1200").status_code == 200
    church = make(c, "Cat", name="Church", kind="expense", parentId=cat["Giving"]).json()
    add(c, acct["id"], "-500.00", "2026-10-04", payee="St Mary's", categoryId=church["id"])
    v = month(c, b, "2026-10")
    assert (row(v, "Giving")["actual"], row(v, "Giving")["remaining"]) == ("500.00", "700.00")
    assert v["unplanned"] == []


def test_a_kept_month_follows_a_category_moved_to_another_parent(server, frozen, admin_client):
    """S7.3.10: a month kept once worked out is worked out again when a category it counts
    moves: Vet, under Health, leaves Health's line for outside the plan."""
    from edits import change as save_change

    c, acct, cat, b = setup_budget(server)
    plan(c, b, "2026-10-01", [{"categoryId": cat["Health"], "amount": "300.00"}])
    vet = make(c, "Cat", name="Vet", kind="expense", parentId=cat["Health"]).json()
    add(c, acct["id"], "-120.00", "2026-10-04", payee="Paws Clinic", categoryId=vet["id"])
    assert row(month(c, b, "2026-10"), "Health")["actual"] == "120.00"
    pets = make(c, "Cat", name="Pets", kind="expense").json()
    assert saved(save_change(admin_client, "Cat", vet, parentId=pets["id"]))
    v = month(c, b, "2026-10")
    assert row(v, "Health")["actual"] == "0.00"
    assert [(x["label"], x["spent"]) for x in v["unplanned"]] == [("Pets › Vet", "120.00")]


def test_a_savings_line_shows_its_projections_monthly(server, frozen):
    c, acct, cat, b = setup_budget(server)
    r = make(
        c,
        "Prjct",
        name="Nest egg",
        goal="savings",
        builtOn={"kind": "accounts", "ids": [acct["id"]]},
        inputs={"target": 150000, "date": "2030-01-01", "monthly": 650},
    )
    pid = r.json()["id"]
    c.post(f"/ui/api/projections/{pid}/activate")
    line = {"categoryId": cat["Savings › Investing"], "amount": "500.00", "projectionId": pid}
    v = plan(c, b, "2026-10-01", [line])
    r = row(v, "Savings › Investing")
    assert (r["projectionName"], r["projectionMonthly"]) == ("Nest egg", "650.00")
    # One the budget is shared with, not the projection, sees the line's figures, not it.
    from conftest import make_user, sign_in
    from edits import share

    make_user(server, "bob")
    bob = sign_in(server, "bob")
    bob_id = bob.get("/ui/api/session").json()["user"]["id"]
    share(c, "budget", b["id"], users={bob_id: "read"})
    theirs = row(month(bob, b, "2026-10"), "Savings › Investing")
    assert (theirs["planned"], theirs["projectionName"], theirs["projectionMonthly"]) == (
        "500.00",
        None,
        None,
    )


def test_an_estimate_adds_up_what_recurs_in_a_category(server, frozen):
    """One line per category: its yearly and quarterly bills summed, plus the average of the rest
    of its spending, each bill named; a reserve toward the bills, never for income (S7.1.5,
    S7.10)."""
    c, acct, cat, b = setup_budget(server)
    home = cat["Housing › Insurance"]
    for y in (2024, 2025, 2026):
        add(c, acct["id"], "-1140.00", f"{y}-08-20", payee="Geico", categoryId=home)
        add(c, acct["id"], "-2400.00", f"{y}-01-10", payee="Allstate", categoryId=home)
        add(c, acct["id"], "5000.00", f"{y}-03-15", payee="Acme bonus",
            categoryId=cat["Income › Other income"])  # fmt: skip
    for m in range(4, 10):
        add(c, acct["id"], "-300.00", f"2026-{m:02d}-05", payee="Acme Health", categoryId=home)

    def proposed():
        r = c.get(f"/ui/api/budgets/{b['id']}/estimate", params={"months": 6})
        assert r.status_code == 200, r.text
        return {x["label"]: x for x in r.json()["items"]}

    got = proposed()["Housing › Insurance"]
    assert (got["amount"], got["cadence"], got["target"]) == ("7140.00", "year", None)
    assert got["detail"] == (
        "recurring: Allstate $2,400 a year, Geico $1,140 a year, and $300 a month besides"
    )
    change(c, b, reserves=True)
    got = proposed()
    ins, bonus = got["Housing › Insurance"], got["Income › Other income"]
    assert (ins["amount"], ins["cadence"], ins["target"]) == ("595.00", "month", "3540.00")
    assert (bonus["amount"], bonus["cadence"], bonus["target"]) == ("5000.00", "year", None)


def test_an_estimate_takes_a_split_bills_parts_out_of_each_categorys_rest(server, frozen):
    """S7.1.5: Allstate's $2,400 a quarter is Insurance's bill; June's was split $2,000
    Insurance and $400 Maintenance. Each part is taken out of its own category's rest, as a
    whole payment is, so neither counts it again: Insurance has nothing besides the bill, and
    Maintenance nothing to propose."""
    c, acct, cat, b = setup_budget(server)
    home, repairs = cat["Housing › Insurance"], cat["Housing › Maintenance"]
    for day in ("2025-09-10", "2025-12-10", "2026-03-10", "2026-09-10"):
        add(c, acct["id"], "-2400.00", day, payee="Allstate", categoryId=home)
    tid = new_id("Txn")
    fields = {"accountId": acct["id"], "date": "2026-06-10", "amount": "-2400.00",
              "payee": "Allstate"}  # fmt: skip
    ops = [{"op": "create", "entity": "Txn", "id": tid, "fields": fields}] + [
        {"op": "create", "entity": "Split", "id": new_id("Split"),
         "fields": {"transactionId": tid, "amount": amount, "categoryId": category}}
        for amount, category in (("-2000.00", home), ("-400.00", repairs))
    ]  # fmt: skip
    r = c.post("/ui/api/save", json={"ops": ops})
    assert r.status_code == 200, r.text
    r = c.get(f"/ui/api/budgets/{b['id']}/estimate", params={"months": 6})
    assert r.status_code == 200, r.text
    got = {x["label"]: x for x in r.json()["items"]}
    ins = got["Housing › Insurance"]
    assert (ins["amount"], ins["cadence"], ins["detail"]) == (
        "9600.00",
        "year",
        "recurring: Allstate $2,400 a quarter",
    )
    assert "Housing › Maintenance" not in got


def test_a_plan_estimated_from_history(server, frozen):
    c, acct, cat, b = setup_budget(server)
    for m in range(4, 10):
        add(
            c,
            acct["id"],
            "-310.00",
            f"2026-{m:02d}-05",
            payee="Kroger",
            categoryId=cat["Food › Groceries"],
        )
    add(c, acct["id"], "-900.00", "2026-07-15", payee="Delta", categoryId=cat["Travel"])
    for y in (2024, 2025, 2026):
        add(
            c,
            acct["id"],
            "-1140.00",
            f"{y}-08-20",
            payee="Geico",
            categoryId=cat["Transportation › Car insurance"],
        )
    r = c.get(f"/ui/api/budgets/{b['id']}/estimate", params={"months": 6})
    assert r.status_code == 200, r.text
    got = {x["label"]: x for x in r.json()["items"]}
    food = got["Food › Groceries"]
    assert (food["amount"], food["cadence"], food["source"]) == ("310.00", "month", "history")
    assert (got["Travel"]["amount"], got["Travel"]["cadence"]) == ("1800.00", "year")
    car = got["Transportation › Car insurance"]
    assert (car["amount"], car["cadence"], car["source"]) == ("1140.00", "year", "recurring")
    # With reserves, a yearly cost is proposed as a reserve: a twelfth a month toward it.
    change(c, b, reserves=True)
    r = c.get(f"/ui/api/budgets/{b['id']}/estimate", params={"months": 6})
    car = {x["label"]: x for x in r.json()["items"]}["Transportation › Car insurance"]
    assert (car["amount"], car["cadence"], car["target"]) == ("95.00", "month", "1140.00")
