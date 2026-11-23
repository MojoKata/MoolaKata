"""Envelope budgets (requirements S7.13): To Budget, card payment lines, owed not backed, and
what an overspent envelope does at the month's end."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import budget_accounts, make
from test_accounts import add, new_account
from test_budgets import cats, month, plan, row
from test_reserves import landed, put_plan, reserves_on

from moolakata import clock

T0 = dt.datetime(2026, 10, 20, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def test_to_budget_card_lines_and_owed_not_backed(server, frozen):
    make_user(server, "jane")
    c = sign_in(server, "jane")
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
    # The Spent card counts it as spent and names it (S7.3.12): every dollar of the month's
    # spending, $100 + $150 + $260, against $700 available.
    assert row(v, "Entertainment")["unbacked"] == "60.00"
    assert (v["available"], v["left"], v["unbacked"]) == ("700.00", "190.00", "60.00")
    card_ = c.get("/ui/api/dashboard").json()["budget"]
    assert (card_["spent"], card_["left"], card_["unbacked"]) == ("510.00", "190.00", "60.00")
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
    make_user(server, "jane")
    c = sign_in(server, "jane")
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


def test_landed_money_given_to_a_reserve_comes_out_of_to_budget(server, frozen):
    """Money given to a reserve is a move into it (S7.10.5): its envelope gains it and To
    Budget, whose cash it already raised, loses it; what is kept as the account's own moves
    nothing (S7.13.1)."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    chk = new_account(c)
    ally = new_account(c, name="Ally", type="savings", mask="2222")
    cat = cats(c)
    b = make(c, "Bdgt", name="Envelopes", method="envelope", accountIds=[chk["id"]]).json()
    assert budget_accounts(c, b, [chk["id"], ally["id"]]).status_code == 200
    reserves_on(c, b)
    repair = cat["Transportation › Car maintenance"]
    line = {"categoryId": repair, "amount": "100", "target": "1000", "heldInId": ally["id"]}
    assert put_plan(c, b, "2026-10-01", [line]).status_code == 200
    add(c, chk["id"], "3000.00", "2026-10-01", payee="Payroll", categoryId=cat["Income › Salary"])
    interest = add(c, ally["id"], "40.00", "2026-10-03", payee="Interest", kind="interest")
    v = month(c, b, "2026-10")
    label = "Transportation › Car maintenance"
    assert (v["toBudget"], row(v, label)["balance"]) == ("2940.00", "100.00")
    assert landed(c, b, interest, {repair: "30.00", None: "10.00"}).status_code == 200
    v = month(c, b, "2026-10")
    r = row(v, label)
    assert (v["toBudget"], v["assignedByMoves"]) == ("2910.00", "30.00")
    assert (r["moved"], r["balance"]) == ("30.00", "130.00")


def test_a_reserves_envelope_keeps_its_money_when_the_target_comes_off(server, frozen):
    """In an envelope budget the balance is money set aside: taking a reserve's target off
    asks, saying the money stays in the envelope, now an ordinary line (S7.10.3, S7.13.3)."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    chk = new_account(c)
    cat = cats(c)
    b = make(c, "Bdgt", name="Envelopes", method="envelope", accountIds=[chk["id"]]).json()
    reserves_on(c, b)
    add(c, chk["id"], "3000.00", "2026-10-01", payee="Payroll", categoryId=cat["Income › Salary"])
    repair = cat["Transportation › Car maintenance"]
    line = {"categoryId": repair, "amount": "100", "target": "1000"}
    assert put_plan(c, b, "2026-10-01", [line]).status_code == 200
    plain = {"categoryId": repair, "amount": "100"}
    r = put_plan(c, b, "2026-11-01", [plain])
    assert r.status_code == 409
    assert r.json()["asks"][0]["message"] == (
        "Transportation › Car maintenance holds 100.00: it stays in the envelope."
    )
    assert put_plan(c, b, "2026-11-01", [plain], confirm=True).status_code == 200
    r = row(month(c, b, "2026-11"), "Transportation › Car maintenance")
    assert (r["carried"], r["remaining"], r["target"]) == ("100.00", "200.00", None)
