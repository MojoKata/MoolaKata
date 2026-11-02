"""A budget's plan edited through a dialog's draft (requirements S7.1.2, S12.15, S13.8.11):
the lines read as stored, and saved from a month on, earlier months keeping theirs (CR3-2)."""

import datetime as dt

import pytest
from edits import edit, make, saved
from test_accounts import add
from test_budgets import month, plan, row, setup_budget
from test_reserves import reserves_on
from test_save import made_at

from moolakata import clock

T0 = dt.datetime(2026, 12, 20, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def lines(c, b, m):
    r = c.get(f"/ui/api/budgets/{b['id']}/plan", params={"month": m})
    assert r.status_code == 200, r.text
    return {x["categoryId"]: x for x in r.json()["lines"]}


def save(c, ops, confirm=()):
    return c.post("/ui/api/save", json={"ops": ops, "confirm": list(confirm)})


def update(line, **fields):
    return {"op": "update", "entity": "BdgLn", "id": line["id"], "version": line["version"],
            "fields": fields}  # fmt: skip


def test_the_plan_is_read_as_stored_not_as_the_months_figures(server, frozen):
    """CR3-2: a move and a carried remainder change the month's figures, never the plan."""
    c, acct, cat, b = setup_budget(server)
    dining, fun = cat["Food › Dining out"], cat["Entertainment"]
    plan(c, b, "2026-11-01", [{"categoryId": dining, "amount": "300.00", "rollover": True},
                              {"categoryId": fun, "amount": "200.00"}])  # fmt: skip
    add(c, acct["id"], "-100.00", "2026-11-05", payee="Bistro", categoryId=dining)
    saved(edit(c, "Bdgt", f"/ui/api/budgets/{b['id']}", moves=True))
    r = make(
        c,
        "BdgMv",
        budgetId=b["id"],
        month="2026-12-01",
        fromCategoryId=fun,
        toCategoryId=dining,
        amount="40.00",
    )
    assert r.status_code == 200, r.text
    figures = row(month(c, b, "2026-12"), "Food › Dining out")
    assert figures["planned"] != "300.00", "the month's figures carry and move"
    got = lines(c, b, "2026-12")
    assert got[dining]["amount"] == "300.00" and got[dining]["fromMonth"] == "2026-11-01"
    assert got[fun]["amount"] == "200.00"


def test_a_line_changed_from_a_later_month_keeps_the_earlier_months(server, frozen):
    c, _, cat, b = setup_budget(server)
    dining = cat["Food › Dining out"]
    plan(c, b, "2026-10-01", [{"categoryId": dining, "amount": "300.00"}])
    line = lines(c, b, "2026-12")[dining]
    r = save(c, [update(line, amount="350.00", fromMonth="2026-12-01")])
    assert r.status_code == 200, r.text
    assert lines(c, b, "2026-11")[dining]["amount"] == "300.00"
    dec = lines(c, b, "2026-12")[dining]
    assert dec["amount"] == "350.00" and dec["fromMonth"] == "2026-12-01"
    # Changed again in its own month: in place.
    r = save(c, [update(dec, amount="360.00", fromMonth="2026-12-01")])
    assert r.status_code == 200, r.text
    again = lines(c, b, "2026-12")[dining]
    assert again["id"] == dec["id"] and again["amount"] == "360.00"
    # Set to nothing: in the plan still, putting nothing in (S7.1.2).
    r = save(c, [update(again, amount="0.00", fromMonth="2027-01-01")])
    assert r.status_code == 200, r.text
    assert lines(c, b, "2027-01")[dining]["amount"] == "0.00"
    # Taken out: out of the plan from then.
    zero = lines(c, b, "2027-01")[dining]
    r = save(c, [update(zero, out=True, fromMonth="2027-02-01")])
    assert r.status_code == 200, r.text
    assert dining not in lines(c, b, "2027-02") and dining in lines(c, b, "2027-01")


def test_a_line_changed_from_a_month_planned_meanwhile_is_stale(server, frozen):
    """A dialog read the line in force; another change planned the category from a later
    month since. Changing the line read from that month would overwrite it unseen: 412."""
    c, _, cat, b = setup_budget(server)
    dining = cat["Food › Dining out"]
    plan(c, b, "2026-10-01", [{"categoryId": dining, "amount": "300.00"}])
    read = lines(c, b, "2026-12")[dining]
    r = save(c, [update(read, amount="333.00", fromMonth="2026-12-01")])
    assert r.status_code == 200, r.text
    r = save(c, [update(read, amount="150.00", fromMonth="2026-12-01")])
    assert r.status_code == 412, r.text
    assert r.json()["current"][0]["current"]["amount"] == "333.00"
    assert lines(c, b, "2026-12")[dining]["amount"] == "333.00"


def test_a_yearly_line_saved_unchanged_but_its_month_stays_yearly(server, frozen):
    """CR3-2's envelope case: a yearly line is a year's amount, not a twelfth."""
    c, acct, cat, _ = setup_budget(server)
    r = make(c, "Bdgt", name="Envelopes", method="envelope", accountIds=[acct["id"]])
    b = r.json()
    fun = cat["Entertainment"]
    plan(c, b, "2026-12-01", [{"categoryId": fun, "amount": "1200.00", "cadence": "year"}])
    line = lines(c, b, "2026-12")[fun]
    assert (line["amount"], line["cadence"]) == ("1200.00", "year")
    r = save(c, [update(line, rollover=False, fromMonth="2026-12-01")])
    assert r.status_code == 200, r.text
    assert lines(c, b, "2026-12")[fun]["amount"] == "1200.00"


def test_a_new_line_and_one_twice(server, frozen):
    c, _, cat, b = setup_budget(server)
    dining = cat["Food › Dining out"]
    new = made_at("BdgLn", clock.now())
    fields = {"budgetId": b["id"], "categoryId": dining, "fromMonth": "2026-12-01",
              "amount": "250.00"}  # fmt: skip
    r = save(c, [{"op": "create", "entity": "BdgLn", "id": new, "fields": fields}])
    assert r.status_code == 200, r.text
    assert lines(c, b, "2026-12")[dining]["id"] == new
    other = made_at("BdgLn", clock.now())
    r = save(c, [{"op": "create", "entity": "BdgLn", "id": other, "fields": fields}])
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "category-twice"
    r = save(c, [{"op": "delete", "entity": "BdgLn", "id": new, "version": 1}])
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "plan-line-delete"


def test_a_reserve_that_stops_while_it_holds_money_is_asked_by_name(server, frozen):
    c, _, cat, b = setup_budget(server)
    repair = cat["Transportation › Car maintenance"]
    reserves_on(c, b)
    plan(c, b, "2026-10-01", [{"categoryId": repair, "amount": "100", "target": "500"}])
    line = lines(c, b, "2026-12")[repair]
    ops = [update(line, target=None, fromMonth="2026-12-01")]
    r = save(c, ops)
    assert r.status_code == 409 and r.json()["code"] == "confirm-needed"
    (ask,) = r.json()["asks"]
    assert ask["code"] == "balance-dropped" and ask["id"] == line["id"]
    assert "200.00" in ask["message"]
    r = save(c, ops, confirm=[{"code": "balance-dropped", "id": line["id"]}])
    assert r.status_code == 200, r.text
    assert row(month(c, b, "2026-12"), "Transportation › Car maintenance")["target"] is None


def test_a_line_checked_as_the_plans_own_route_checks_it(server, frozen):
    c, _, cat, b = setup_budget(server)
    dining = cat["Food › Dining out"]
    plan(c, b, "2026-12-01", [{"categoryId": dining, "amount": "300.00"}])
    line = lines(c, b, "2026-12")[dining]
    r = save(c, [update(line, amount="-5.00", target="100.00", fromMonth="2026-12-01")])
    assert r.status_code == 422
    got = {(e["id"], e["field"], e["code"]) for e in r.json()["errors"]}
    assert (line["id"], "amount", "amount-negative") in got
    assert (line["id"], "target", "target-invalid") in got
    r = save(c, [update(line, amount="1.00", fromMonth="2026-11-01")])
    assert r.json()["errors"][0]["code"] == "month-earlier"
