"""Moves and leave-outs (requirements S7.11, S7.3.5)."""

import datetime as dt

import pytest
from test_accounts import add
from test_budgets import month, plan, row, setup_budget

from moolakata import clock

T0 = dt.datetime(2026, 10, 20, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def moves_on(c, b):
    v = c.get(f"/ui/api/budgets/{b['id']}").json()["version"]
    r = c.patch(f"/ui/api/budgets/{b['id']}", json={"moves": True}, headers={"If-Match": str(v)})
    assert r.status_code == 200, r.text


def move(c, b, **body):
    return c.post(f"/ui/api/budgets/{b['id']}/moves", json=body)


def test_a_move_covers_one_category_from_another_for_a_month(server, frozen):
    c, acct, cat, b = setup_budget(server)
    food, fun, kids = cat["Food"], cat["Entertainment"], cat["Childcare"]
    lines = [
        {"categoryId": food, "amount": "300.00"},
        {"categoryId": fun, "amount": "200.00"},
        {"categoryId": kids, "amount": "100.00", "rollover": True},
    ]
    plan(c, b, "2026-09-01", lines)
    add(c, acct["id"], "-340.00", "2026-10-04", payee="Kroger", categoryId=cat["Food › Groceries"])
    r = move(c, b, month="2026-10-01", fromCategoryId=fun, toCategoryId=food, amount="40.00")
    assert r.status_code == 422 and r.json()["code"] == "moves-off"
    moves_on(c, b)
    r = move(
        c,
        b,
        month="2026-10-01",
        fromCategoryId=fun,
        toCategoryId=food,
        amount="40.00",
        note="Emma's dinner",
    )
    assert r.status_code == 201, r.text
    made = r.json()
    v = month(c, b, "2026-10")
    f, e = row(v, "Food"), row(v, "Entertainment")
    assert (f["planned"], f["moved"], f["state"]) == ("340.00", "40.00", "near")
    assert (e["planned"], e["moved"]) == ("160.00", "-40.00")
    assert [(m["fromLabel"], m["toLabel"], m["note"]) for m in v["moves"]] == [
        ("Entertainment", "Food", "Emma's dinner")
    ]
    # A move in September carries on where the line rolls over.
    assert (
        move(
            c, b, month="2026-09-01", fromCategoryId=fun, toCategoryId=kids, amount="50"
        ).status_code
        == 201
    )
    assert row(month(c, b, "2026-10"), "Childcare")["carried"] == "150.00"
    # Deleting a move undoes it.
    r = c.delete(
        f"/ui/api/budgets/{b['id']}/moves/{made['id']}", headers={"If-Match": str(made["version"])}
    )
    assert r.status_code == 200, r.text
    assert row(month(c, b, "2026-10"), "Food")["planned"] == "300.00"
    # To Budget is an envelope budget's alone.
    r = move(c, b, month="2026-10-01", toCategoryId=food, amount="10")
    assert r.status_code == 422 and r.json()["code"] == "move-invalid"


def test_a_transaction_left_out_of_one_budget(server, frozen):
    c, acct, cat, b = setup_budget(server)
    car = add(
        c, acct["id"], "-18000.00", "2026-10-02", payee="Honda", categoryId=cat["Transportation"]
    )
    add(
        c,
        acct["id"],
        "-40.00",
        "2026-10-03",
        payee="Shell",
        categoryId=cat["Transportation › Fuel"],
    )
    other = c.post("/ui/api/budgets", json={"name": "Mine", "accountIds": [acct["id"]]}).json()
    found = {
        x["name"]: x for x in c.get(f"/ui/api/transactions/{car['id']}/budgets").json()["items"]
    }
    mine, theirs = found["Household"], found["Mine"]
    assert (mine["name"], mine["countsAs"], mine["leftOut"]) == (
        "Household",
        "Transportation",
        False,
    )
    r = c.put(f"/ui/api/budgets/{b['id']}/leave-outs/{car['id']}", json={"leftOut": True})
    assert r.status_code == 200 and r.json()["leftOut"]
    assert month(c, b, "2026-10")["spent"] == "40.00"
    assert month(c, other, "2026-10")["spent"] == "18040.00"
    r = c.put(f"/ui/api/budgets/{b['id']}/leave-outs/{car['id']}", json={"leftOut": False})
    assert month(c, b, "2026-10")["spent"] == "18040.00"
    assert theirs["name"] == "Mine"
