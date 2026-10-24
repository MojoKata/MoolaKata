"""The active budget and scenarios (requirements S7.12, S12.2.1)."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from test_accounts import add
from test_budgets import month, plan, row, setup_budget

from moolakata import clock

T0 = dt.datetime(2026, 10, 20, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def test_one_active_budget_and_scenarios_beside_it(server, frozen):
    c, acct, cat, b = setup_budget(server)
    assert b["active"]  # a user's first budget
    food = cat["Food"]
    plan(c, b, "2026-10-01", [{"categoryId": food, "amount": "300.00"}])
    add(c, acct["id"], "-120.00", "2026-10-04", payee="Kroger", categoryId=cat["Food › Groceries"])
    r = c.post(
        f"/ui/api/budgets/{b['id']}/copy",
        json={"name": "Household, envelope", "method": "envelope"},
    )
    assert r.status_code == 201, r.text
    copy = r.json()
    assert (copy["method"], copy["moves"], copy["active"], copy["accountIds"]) == (
        "envelope",
        True,
        False,
        [acct["id"]],
    )
    assert row(month(c, copy, "2026-10"), "Food")["planned"] == "300.00"
    # Compare, side by side.
    r = c.get(
        f"/ui/api/budgets/{b['id']}/compare", params={"other": copy["id"], "month": "2026-10"}
    )
    assert r.status_code == 200, r.text
    (f,) = r.json()["items"] if "items" in r.json() else r.json()["rows"]
    assert (f["available"], f["spent"], f["otherAvailable"]) == ("300.00", "120.00", "300.00")
    # The Dashboard follows the active budget; Make active swaps them, rewriting nothing.
    assert c.get("/ui/api/dashboard").json()["budget"]["name"] == "Household"
    r = c.post(f"/ui/api/budgets/{copy['id']}/active")
    assert r.status_code == 200 and r.json()["active"]
    assert c.get("/ui/api/dashboard").json()["budget"]["name"] == "Household, envelope"
    listed = {x["name"]: x["active"] for x in c.get("/ui/api/budgets").json()["items"]}
    assert listed == {"Household": False, "Household, envelope": True}
    assert row(month(c, b, "2026-10"), "Food")["planned"] == "300.00"
    # Active is each user's own choice; deleting it leaves none active.
    v = c.get(f"/ui/api/budgets/{copy['id']}").json()["version"]
    c.delete(f"/ui/api/budgets/{copy['id']}", headers={"If-Match": str(v)})
    assert c.get("/ui/api/dashboard").json()["budget"] is None
    make_user(server, "bob")
    bob = sign_in(server, "bob")
    assert bob.get("/ui/api/dashboard").json()["budget"] is None
