"""Envelope budgets (requirements S7.13): To Budget, card payment lines, owed not backed, and
what an overspent envelope does at the month's end."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import make
from test_accounts import add, new_account
from test_budgets import cats, month, plan, row

from moolakata import clock

T0 = dt.datetime(2026, 10, 20, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def test_to_budget_card_lines_and_owed_not_backed(server, frozen):
    make_user(server, "alice")
    c = sign_in(server, "alice")
    chk = new_account(c)
    card = new_account(c, name="Visa", type="credit-card", mask="1111")
    cat = cats(c)
    r = make(c, "Bdgt", name="Envelopes", method="envelope", accountIds=[chk["id"], card["id"]])
    b = r.json()
    food, fun = cat["Food"], cat["Entertainment"]
    add(c, chk["id"], "3000.00", "2026-10-01", payee="Payroll", categoryId=cat["Income › Salary"])
    plan(
        c,
        b,
        "2026-10-01",
        [
            {"categoryId": food, "amount": "500.00"},
            {"categoryId": fun, "amount": "200.00", "overspend": "next"},
        ],
    )

    def view():
        return month(c, b, "2026-10")

    v = view()
    assert (v["toBudget"], v["assigned"]) == ("2300.00", "700.00")
    # Cash spent comes out of the envelope and the cash alike: To Budget doesn't move.
    add(c, chk["id"], "-100.00", "2026-10-03", payee="Kroger", categoryId=cat["Food › Groceries"])
    assert view()["toBudget"] == "2300.00"
    # A charge to the card moves the money from the envelope to the card's payment line.
    add(
        c,
        card["id"],
        "-150.00",
        "2026-10-04",
        payee="Whole Foods",
        categoryId=cat["Food › Groceries"],
    )
    v = view()
    assert v["toBudget"] == "2300.00" and row(v, "Food")["remaining"] == "250.00"
    (line,) = v["cards"]
    assert (line["setAside"], line["owed"], line["notBacked"]) == ("150.00", "150.00", "0.00")
    # Beyond what the envelope held: the envelope stops at nothing, the rest is owed, not backed.
    add(c, card["id"], "-260.00", "2026-10-05", payee="Concert", categoryId=cat["Entertainment"])
    v = view()
    assert row(v, "Entertainment")["remaining"] == "0.00" and v["toBudget"] == "2300.00"
    (line,) = v["cards"]
    assert (line["setAside"], line["owed"], line["notBacked"]) == ("350.00", "410.00", "60.00")
    # A payment to the card takes from its line, cash and line alike.
    add(c, chk["id"], "-300.00", "2026-10-10", payee="Visa payment")
    add(c, card["id"], "300.00", "2026-10-10", payee="Thank you", kind="deposit")
    v = view()
    (line,) = v["cards"]
    assert (v["toBudget"], line["setAside"], line["notBacked"]) == ("2300.00", "50.00", "60.00")
    # A move from To Budget covers the debt, and another adds to an envelope.
    for body in ({"cardId": card["id"]}, {"toCategoryId": food}):
        r = make(
            c, "BdgMv", **{"budgetId": b["id"], **{"month": "2026-10-01", "amount": "60.00"} | body}
        )
        assert r.status_code == 200, r.text
    v = view()
    (line,) = v["cards"]
    assert (v["toBudget"], v["assignedByMoves"], line["notBacked"]) == ("2180.00", "120.00", "0.00")
    assert row(v, "Food")["remaining"] == "310.00"
    assert {m["toLabel"] for m in v["moves"]} == {"Food", "Visa's payment"}


def test_an_overspent_envelope_carried_or_taken_from_next_month(server, frozen):
    make_user(server, "alice")
    c = sign_in(server, "alice")
    chk = new_account(c)
    cat = cats(c)
    b = make(c, "Bdgt", name="Envelopes", method="envelope", accountIds=[chk["id"]]).json()
    food, fun = cat["Food"], cat["Entertainment"]
    add(c, chk["id"], "2000.00", "2026-10-01", payee="Payroll", categoryId=cat["Income › Salary"])
    plan(
        c,
        b,
        "2026-10-01",
        [
            {"categoryId": food, "amount": "300.00"},
            {"categoryId": fun, "amount": "100.00", "overspend": "next"},
        ],
    )
    add(c, chk["id"], "-340.00", "2026-10-03", payee="Kroger", categoryId=cat["Food › Groceries"])
    add(c, chk["id"], "-130.00", "2026-10-04", payee="Concert", categoryId=fun)
    oct_ = month(c, b, "2026-10")
    assert (
        row(oct_, "Food")["state"] == "over" and row(oct_, "Entertainment")["remaining"] == "-30.00"
    )
    nov = month(c, b, "2026-11")
    # Carried negative: November starts 40 short. Taken from next month: it starts at nothing.
    assert row(nov, "Food")["carried"] == "-40.00"
    assert row(nov, "Entertainment")["carried"] == "0.00"
    # So November's To Budget is what is left after the shortfall: 1530 cash, less 260 and 100.
    assert nov["toBudget"] == "1170.00"
    bad = make(c, "BdgMv", budgetId=b["id"], month="2026-10-01", amount="5", cardId=chk["id"])
    assert bad.status_code == 422
