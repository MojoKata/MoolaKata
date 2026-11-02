"""One reading of a line's month (requirements S7.3.11), and what reads it: Compare over a
range of months (S7.12.3) and the month's Spent card (S7.3.12). The identity itself is held on
every month the budget tests read (`test_budgets.month`)."""

import datetime as dt
import random
from decimal import Decimal

import pytest
from edits import edit, make, saved
from test_accounts import add
from test_budgets import month, row, save_plan, setup_budget

from moolakata import clock

T0 = dt.datetime(2026, 3, 20, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def _ok(r):
    assert r.status_code == 200, r.text


def _compare(c, b, other, m):
    r = c.get(f"/ui/api/budgets/{b['id']}/compare",
              params={"other": other["id"], "month": m, "span": "year"})  # fmt: skip
    assert r.status_code == 200, r.text
    return {x["label"]: x for x in r.json()["rows"] if x["available"] is not None}


def test_a_range_counts_a_carry_once(server, frozen):
    """The claim (CR3-40): $100 a month with rollover, nothing spent, January to March: $300
    was made available, not 100 + 200 + 300."""
    c, acct, cat, b = setup_budget(server)
    other = make(c, "Bdgt", name="Other", accountIds=[acct["id"]]).json()
    fun = cat["Entertainment"]
    _ok(save_plan(c, b, "2026-01-01", [{"categoryId": fun, "amount": "100", "rollover": True}]))
    got = _compare(c, b, other, "2026-03")["Entertainment"]
    assert (got["available"], got["spent"]) == ("300.00", "0.00")


@pytest.mark.parametrize("seed", range(5))
def test_a_carrying_lines_range_leaves_what_its_last_month_does(server, frozen, seed):
    """Generated: for a rollover line and a reserve with random plans and spending, what the
    range leaves (available less spent) is what its last month leaves; for a line without
    rollover, the range makes available the months' own plans."""
    rnd = random.Random(seed)
    c, acct, cat, b = setup_budget(server)
    saved(edit(c, "Bdgt", f"/ui/api/budgets/{b['id']}", reserves=True))
    other = make(c, "Bdgt", name="Other", accountIds=[acct["id"]]).json()
    fun, fund, food = cat["Entertainment"], cat["Savings › Emergency fund"], cat["Food"]
    plans = {}
    for m in ("2026-01", "2026-02", "2026-03"):
        amounts = [rnd.choice(["0", "40", "100"]) for _ in range(3)]
        plans[m] = Decimal(amounts[2])
        _ok(save_plan(c, b, m + "-01", [
            {"categoryId": fun, "amount": amounts[0], "rollover": True},
            {"categoryId": fund, "amount": amounts[1], "target": "250"},
            {"categoryId": food, "amount": amounts[2]},
        ]))  # fmt: skip
        for k in (fun, fund, food):
            if rnd.random() < 0.6:
                add(c, acct["id"], f"-{rnd.randint(1, 90)}.00", f"{m}-{rnd.randint(1, 28):02d}",
                    payee="Shop", categoryId=k)  # fmt: skip
    got = _compare(c, b, other, "2026-03")
    march = month(c, b, "2026-03")
    for label in ("Entertainment", "Savings › Emergency fund"):
        left = Decimal(got[label]["available"]) - Decimal(got[label]["spent"])
        assert left == Decimal(row(march, label)["remaining"]), label
    assert Decimal(got["Food"]["available"]) == sum(plans.values())


def test_a_repair_a_reserve_covers_is_never_over(server, frozen):
    """S7.3.12, S7.10.2: the Spent card counts a reserve's balance as available, so a repair it
    covers leaves the month on plan."""
    c, acct, cat, b = setup_budget(server)
    saved(edit(c, "Bdgt", f"/ui/api/budgets/{b['id']}", reserves=True))
    repair = cat["Transportation › Car maintenance"]
    _ok(save_plan(c, b, "2026-01-01", [{"categoryId": repair, "amount": "300", "target": "900"}]))
    add(c, acct["id"], "-700.00", "2026-03-05", payee="Midas", categoryId=repair)
    v = month(c, b, "2026-03")
    assert (v["available"], v["left"]) == ("900.00", "200.00")


def test_spending_against_a_yearly_line_is_named_beside(server, frozen):
    c, acct, cat, b = setup_budget(server)
    _ok(save_plan(c, b, "2026-01-01", [{"categoryId": cat["Food"], "amount": "500"},
                                       {"categoryId": cat["Travel"], "amount": "2400",
                                        "cadence": "year"}]))  # fmt: skip
    add(c, acct["id"], "-120.00", "2026-03-04", payee="Kroger", categoryId=cat["Food"])
    add(c, acct["id"], "-900.00", "2026-03-06", payee="Delta", categoryId=cat["Travel"])
    v = month(c, b, "2026-03")
    assert (v["available"], v["left"], v["yearlySpent"]) == ("500.00", "380.00", "900.00")
