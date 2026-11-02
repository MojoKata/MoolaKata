"""Taking a category out of the plan is a state of its own, never an amount (requirements
S7.1.2, S7.10.3): a line of $0 stays in the plan, puts nothing in and keeps what it holds;
taking out a line that holds money asks first and names it."""

import datetime as dt
import random
from decimal import Decimal

import pytest
from edits import edit, make, saved
from test_accounts import new_account
from test_budgets import cats, month, row, save_plan, setup_budget

from moolakata import clock

T0 = dt.datetime(2026, 12, 20, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def _ok(r):
    assert r.status_code == 200, r.text


def test_a_reserve_set_to_put_in_nothing_keeps_its_balance(server, frozen):
    """The claim (CR3-46): Emergency fund at $500 a month since August holds $2,000; set to $0
    in December to pause it, it stays, holds its $2,000, and nothing is asked."""
    c, _, cat, b = setup_budget(server)
    saved(edit(c, "Bdgt", f"/ui/api/budgets/{b['id']}", reserves=True))
    fund = cat["Savings › Emergency fund"]
    _ok(save_plan(c, b, "2026-08-01", [{"categoryId": fund, "amount": "500", "target": "10000"}]))
    assert row(month(c, b, "2026-11"), "Savings › Emergency fund")["balance"] == "2000.00"
    _ok(save_plan(c, b, "2026-12-01", [{"categoryId": fund, "amount": "0", "target": "10000"}]))
    r = row(month(c, b, "2026-12"), "Savings › Emergency fund")
    assert (r["balance"], r["putIn"]) == ("2000.00", "0.00")


def test_a_rollover_line_set_to_nothing_keeps_its_remainder(server, frozen):
    c, _, cat, b = setup_budget(server)
    fun = cat["Entertainment"]
    _ok(save_plan(c, b, "2026-08-01", [{"categoryId": fun, "amount": "100", "rollover": True}]))
    _ok(save_plan(c, b, "2026-10-01", [{"categoryId": fun, "amount": "0", "rollover": True}]))
    r = row(month(c, b, "2026-10"), "Entertainment")
    assert (r["carried"], r["remaining"]) == ("200.00", "200.00")


def test_an_envelope_set_to_nothing_keeps_its_balance(server, frozen):
    c, _, cat, _ = setup_budget(server)
    env = make(c, "Bdgt", name="Envelopes", method="envelope",
               accountIds=[new_account(c, name="Joint", mask="9999")["id"]]).json()  # fmt: skip
    fun = cat["Entertainment"]
    _ok(save_plan(c, env, "2026-12-01", [{"categoryId": fun, "amount": "100"}]))
    _ok(save_plan(c, env, "2027-01-01", [{"categoryId": fun, "amount": "0"}]))
    assert row(month(c, env, "2027-01"), "Entertainment")["remaining"] == "100.00"


def test_taking_out_a_line_that_holds_money_asks_and_names_it(server, frozen):
    c, _, cat, b = setup_budget(server)
    fun = cat["Entertainment"]
    _ok(save_plan(c, b, "2026-08-01", [{"categoryId": fun, "amount": "100", "rollover": True}]))
    r = save_plan(c, b, "2026-10-01", [])
    assert r.status_code == 409 and r.json()["asks"][0]["code"] == "balance-dropped"
    assert "200.00" in r.json()["asks"][0]["message"]
    _ok(save_plan(c, b, "2026-10-01", [], confirm=True))
    assert [x for x in month(c, b, "2026-10")["rows"] if x["label"] == "Entertainment"] == []


def test_a_line_already_taken_out_is_planned_again_from_a_later_month(server, frozen):
    c, _, cat, b = setup_budget(server)
    fun = cat["Entertainment"]
    _ok(save_plan(c, b, "2026-08-01", [{"categoryId": fun, "amount": "100"}]))
    _ok(save_plan(c, b, "2026-09-01", []))
    _ok(save_plan(c, b, "2026-11-01", [{"categoryId": fun, "amount": "80"}]))
    assert row(month(c, b, "2026-11"), "Entertainment")["planned"] == "80.00"
    assert [x for x in month(c, b, "2026-10")["rows"] if x["label"] == "Entertainment"] == []


@pytest.mark.parametrize("seed", range(5))
def test_a_balance_carries_on_through_any_amount(server, frozen, seed):
    """Generated: a rollover line and a reserve, their amounts changed from month to month at
    random, $0 among them; each month begins with what the month before left, so no balance
    goes anywhere unasked."""
    rnd = random.Random(seed)
    c, _, cat, b = setup_budget(server)
    saved(edit(c, "Bdgt", f"/ui/api/budgets/{b['id']}", reserves=True))
    fun, fund = cat["Entertainment"], cat["Savings › Emergency fund"]
    months = ["2026-08", "2026-09", "2026-10", "2026-11", "2026-12"]
    for m in months:
        amounts = [rnd.choice(["0", "0", "50", "120"]) for _ in range(2)]
        lines = [
            {"categoryId": fun, "amount": amounts[0], "rollover": True},
            {"categoryId": fund, "amount": amounts[1], "target": "300"},
        ]
        _ok(save_plan(c, b, m + "-01", lines))
    labels = ("Entertainment", "Savings › Emergency fund")
    before = {k: Decimal(0) for k in labels}
    for m in months:
        v = month(c, b, m)
        for k in labels:
            r = row(v, k)
            assert Decimal(r["carried"]) == before[k], (m, k)
            before[k] = Decimal(r["remaining"])
    assert cats(c)  # the categories still read
