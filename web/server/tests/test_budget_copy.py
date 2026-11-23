"""Copy as scenario (requirements S7.12.4): the same accounts and plan from this month, in the
method chosen, with this month's moves when asked."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import budget_accounts, share
from test_accounts import new_account
from test_budgets import setup_budget
from test_reserves import put_plan, reserves_on

from moolakata import clock

T0 = dt.datetime(2026, 12, 20, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def copy(c, b, method="tracking", with_moves=False) -> dict:
    r = c.post(f"/ui/api/budgets/{b['id']}/copy",
               json={"name": "Scenario", "method": method, "withMoves": with_moves})  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


def plan_lines(c, b) -> dict[str, dict]:
    v = c.get(f"/ui/api/budgets/{b['id']}/plan", params={"month": "2026-12"}).json()
    return {x["categoryId"]: x for x in v["lines"]}


def test_a_reserve_held_in_an_account_the_copy_does_not_count_is_held_nowhere(server, frozen):
    """A reserve is held in one of the budget's accounts (S7.10.4): a copier who can't see that
    account gets the reserve, target kept, held nowhere (*in the budget's accounts*)."""
    c, acct, cat, b = setup_budget(server)
    ally = new_account(c, name="Ally", type="savings", mask="2222")
    assert budget_accounts(c, b, [acct["id"], ally["id"]]).status_code == 200
    reserves_on(c, b)
    repair = cat["Transportation › Car maintenance"]
    line = {"categoryId": repair, "amount": "100", "target": "500", "heldInId": ally["id"]}
    assert put_plan(c, b, "2026-12-01", [line]).status_code == 200
    # Its owner's copy counts Ally: the reserve stays held there.
    assert plan_lines(c, copy(c, b))[repair]["heldInId"] == ally["id"]
    make_user(server, "john")
    john = sign_in(server, "john")
    john_id = john.get("/ui/api/session").json()["user"]["id"]
    share(c, "budget", b["id"], users={john_id: "read"})
    share(c, "account", acct["id"], users={john_id: "read"})
    theirs = copy(john, b)
    got = plan_lines(john, theirs)[repair]
    assert (str(got["target"]), got["heldInId"]) == ("500.00", None)
