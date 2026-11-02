"""Each transaction counts against one line at most (requirements S7.1.2, S7.13.1): its
category's own, else its parent's, else none. A parent line covers only children without a
line of their own, in both methods, so no spending is counted twice."""

import datetime as dt
import random
from decimal import Decimal

import pytest
from conftest import make_user, sign_in
from edits import make
from test_accounts import add, new_account
from test_budgets import cats, month, plan, row, setup_budget

from moolakata import clock

T0 = dt.datetime(2026, 10, 20, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def _envelopes(server, accounts=("checking",)):
    make_user(server, "alice")
    c = sign_in(server, "alice")
    chk = new_account(c, openingBalance="0.00", openingDate="2026-09-30")
    made = {"checking": chk}
    if "card" in accounts:
        made["card"] = new_account(c, name="Visa", type="credit-card", mask="1111")
    ids = [made[k]["id"] for k in accounts]
    b = make(c, "Bdgt", name="Envelopes", method="envelope", accountIds=ids).json()
    return c, made, cats(c), b


def test_an_envelope_parent_and_child_both_planned_take_spending_once(server, frozen):
    """The claim (CR3-41): Food $300 and Food › Groceries $200 planned; a $150 Kroger charge
    comes out of Groceries alone, and To Budget doesn't move."""
    c, acct, cat, b = _envelopes(server)
    add(c, acct["checking"]["id"], "1000.00", "2026-10-01", payee="Payroll",
        categoryId=cat["Income › Salary"])  # fmt: skip
    both = [{"categoryId": cat["Food"], "amount": "300.00"},
            {"categoryId": cat["Food › Groceries"], "amount": "200.00"}]  # fmt: skip
    plan(c, b, "2026-10-01", both)
    assert month(c, b, "2026-10")["toBudget"] == "500.00"
    add(c, acct["checking"]["id"], "-150.00", "2026-10-03", payee="Kroger",
        categoryId=cat["Food › Groceries"])  # fmt: skip
    v = month(c, b, "2026-10")
    assert v["toBudget"] == "500.00"
    assert (row(v, "Food")["remaining"], row(v, "Food › Groceries")["remaining"]) == (
        "300.00",
        "50.00",
    )


def test_a_tracking_parent_line_counts_only_children_without_a_line(server, frozen):
    c, acct, cat, b = setup_budget(server)
    both = [{"categoryId": cat["Food"], "amount": "300.00"},
            {"categoryId": cat["Food › Groceries"], "amount": "200.00"}]  # fmt: skip
    plan(c, b, "2026-10-01", both)
    add(c, acct["id"], "-150.00", "2026-10-03", payee="Kroger", categoryId=cat["Food › Groceries"])
    add(c, acct["id"], "-40.00", "2026-10-04", payee="Chipotle",
        categoryId=cat["Food › Dining out"])  # fmt: skip
    v = month(c, b, "2026-10")
    assert row(v, "Food")["actual"] == "40.00"
    assert row(v, "Food › Groceries")["actual"] == "150.00"
    assert v["spent"] == "190.00"


def _generated(rnd, cat):
    """A plan over Food and its children, and the month's spending, drawn at random."""
    tops = ["Food", "Entertainment", "Transportation"]
    children = [k for k in cat if any(k.startswith(t + " › ") for t in tops)]
    planned = rnd.sample(tops + children, rnd.randint(1, 5))
    lines = [{"categoryId": cat[k], "amount": f"{rnd.randint(50, 400)}.00"} for k in planned]
    spends = [(rnd.choice(tops + children), rnd.randint(1, 120)) for _ in range(10)]
    return lines, spends


@pytest.mark.parametrize("seed", range(5))
def test_the_rows_and_unplanned_spending_add_up_to_the_month(server, frozen, seed):
    """Generated: whatever lines a tracking plan has among parents and children, the rows'
    spending and what is unplanned add up to the month's spending, once."""
    rnd = random.Random(seed)
    c, acct, cat, b = setup_budget(server)
    lines, spends = _generated(rnd, cat)
    plan(c, b, "2026-10-01", lines)
    for k, amount in spends:
        add(c, acct["id"], f"-{amount}.00", f"2026-10-{rnd.randint(1, 20):02d}", payee="Shop",
            categoryId=cat[k])  # fmt: skip
    v = month(c, b, "2026-10")
    rows = sum(Decimal(r["actual"]) for r in v["rows"] if r["kind"] == "expense")
    unplanned = sum(Decimal(x["spent"]) for x in v["unplanned"])
    assert rows + unplanned == Decimal(v["spent"]) == sum(Decimal(a) for _, a in spends)


@pytest.mark.parametrize("seed", range(5))
def test_spending_from_an_envelope_never_moves_to_budget(server, frozen, seed):
    """Generated (S7.13.1): To Budget is the cash less what the categories hold, so spending
    paid in cash from an envelope, which takes the same amount from both, never moves it,
    whatever lines the plan has among parents and children; only spending no envelope holds
    comes out of it. And the envelopes' spending is the month's, once."""
    rnd = random.Random(seed)
    c, acct, cat, b = _envelopes(server)
    add(c, acct["checking"]["id"], "3000.00", "2026-10-01", payee="Payroll",
        categoryId=cat["Income › Salary"])  # fmt: skip
    lines, spends = _generated(rnd, cat)
    plan(c, b, "2026-10-01", lines)
    before = month(c, b, "2026-10")["toBudget"]
    for k, amount in spends:
        add(c, acct["checking"]["id"], f"-{amount}.00", f"2026-10-{rnd.randint(2, 20):02d}",
            payee="Shop", categoryId=cat[k])  # fmt: skip
    v = month(c, b, "2026-10")
    rows = sum(Decimal(r["actual"]) for r in v["rows"] if r["kind"] == "expense")
    unplanned = sum(Decimal(x["spent"]) for x in v["unplanned"])
    assert rows + unplanned == Decimal(v["spent"])
    # Only spending no envelope holds comes out of To Budget.
    assert Decimal(before) - Decimal(v["toBudget"]) == unplanned
