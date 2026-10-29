"""A budget's method, options and plan (requirements S7.1.3–S7.1.6, S7.2.1, S7.3.6)."""

import datetime as dt

import pytest
from edits import edit, giving_plan, saved
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
    r = c.post("/ui/api/budgets", json={"name": "Try", "method": "zero"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "method"
    r = c.post(
        "/ui/api/budgets",
        json={"name": "Envelopes", "method": "envelope", "accountIds": [acct["id"]]},
    )
    env = r.json()
    assert env["method"] == "envelope" and env["moves"]
    assert change(c, env, moves=False).status_code == 422
    assert saved(change(c, b, reserves=True))["reserves"]


def test_where_money_comes_from_is_worked_out(server, frozen):
    """A card's paying account is learned from its payments; where money for a savings
    account moves from, from its transfers in; either can be chosen (S7.1.6)."""
    c, acct, _, b = setup_budget(server)
    other = new_account(c, name="Bob's checking", mask="5555")
    card = new_account(c, name="Visa", type="credit-card", mask="1111")
    savings = new_account(c, name="Ally", type="savings", mask="2222")
    add(c, acct["id"], "3000.00", "2026-09-01", payee="Payroll")
    for day in ("2026-08-03", "2026-09-03"):
        add(c, other["id"], "-400.00", day, payee="Card payment")
        add(c, card["id"], "400.00", day, payee="Thank you", kind="deposit")
    add(c, acct["id"], "-250.00", "2026-09-10", payee="To Ally")
    add(c, savings["id"], "250.00", "2026-09-10", payee="From checking", kind="deposit")
    ids = [acct["id"], other["id"], card["id"], savings["id"]]
    roles = {x["accountId"]: x for x in saved(change(c, b, accountIds=ids))["roles"]}
    assert roles[card["id"]]["paidFromId"] == other["id"] and roles[card["id"]]["paidFromLearned"]
    assert roles[savings["id"]]["movedFromId"] == acct["id"]
    r = change(c, b, roles=[{"accountId": savings["id"], "movedFromId": other["id"]}])
    roles = {x["accountId"]: x for x in saved(r)["roles"]}
    assert roles[savings["id"]]["movedFromId"] == other["id"]
    assert not roles[savings["id"]]["movedFromProposed"]
    bad = change(c, b, roles=[{"accountId": savings["id"], "movedFromId": "Acct_nope"}])
    assert bad.status_code == 422


def test_gifts_and_giving_are_planned_by_their_plans(server, frozen):
    c, acct, cat, b = setup_budget(server)
    r = c.post(
        "/ui/api/people", json={"name": "Emma Griffin", "sex": "female", "giftBudget": "600"}
    )
    assert r.status_code == 201, r.text
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


def test_a_savings_line_shows_its_projections_monthly(server, frozen):
    c, acct, cat, b = setup_budget(server)
    r = c.post(
        "/ui/api/projections",
        json={
            "name": "Nest egg",
            "goal": "savings",
            "builtOn": {"kind": "accounts", "ids": [acct["id"]]},
            "inputs": {"target": 150000, "date": "2030-01-01", "monthly": 650},
        },
    )
    pid = r.json()["id"]
    c.post(f"/ui/api/projections/{pid}/activate")
    line = {"categoryId": cat["Savings › Investing"], "amount": "500.00", "projectionId": pid}
    v = plan(c, b, "2026-10-01", [line])
    r = row(v, "Savings › Investing")
    assert (r["projectionName"], r["projectionMonthly"]) == ("Nest egg", "650.00")


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
