"""Reserves and where their money is (requirements S7.10, S1.2)."""

import datetime as dt

import pytest
from edits import change, edit, saved
from test_accounts import add, new_account
from test_budgets import month, row, setup_budget

from moolakata import clock

T0 = dt.datetime(2026, 12, 20, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def put_plan(c, b, month_, lines, confirm=False):
    from test_budgets import save_plan

    return save_plan(c, b, month_, lines, confirm=confirm)


def reserves_on(c, b):
    v = c.get(f"/ui/api/budgets/{b['id']}").json()["version"]
    r = c.patch(f"/ui/api/budgets/{b['id']}", json={"reserves": True}, headers={"If-Match": str(v)})
    assert r.status_code == 200, r.text


def test_a_reserve_puts_in_up_to_its_target_and_spending_takes_from_it(server, frozen):
    c, acct, cat, b = setup_budget(server)
    repair = cat["Transportation › Car maintenance"]
    reserves_on(c, b)
    line = {"categoryId": repair, "amount": "100.00", "target": "300.00"}
    assert put_plan(c, b, "2026-08-01", [line]).status_code == 200
    add(c, acct["id"], "-250.00", "2026-10-12", payee="Midas", categoryId=repair)
    r = row(month(c, b, "2026-10"), "Transportation › Car maintenance")
    assert (r["carried"], r["putIn"], r["actual"], r["balance"], r["state"]) == (
        "200.00",
        "100.00",
        "250.00",
        "50.00",
        "under",
    )
    assert r["rollover"] and r["target"] == "300.00"
    r = row(month(c, b, "2026-12"), "Transportation › Car maintenance")
    assert (r["balance"], r["state"]) == ("250.00", "under")
    # Funded: it puts in only what reaches the target, then nothing.
    add(c, acct["id"], "50.00", "2026-12-05", payee="Refund", categoryId=repair)
    r = row(month(c, b, "2027-01"), "Transportation › Car maintenance")
    assert (r["putIn"], r["balance"], r["state"]) == ("0.00", "300.00", "funded")


def test_a_reserves_balance_is_kept_until_asked(server, frozen):
    c, _, cat, b = setup_budget(server)
    repair = cat["Transportation › Car maintenance"]
    bad = put_plan(c, b, "2026-10-01", [{"categoryId": repair, "amount": "100", "target": "500"}])
    assert bad.status_code == 422 and bad.json()["errors"][0]["field"] == "target"
    reserves_on(c, b)
    savings = new_account(c, name="Ally", type="savings", mask="2222")
    bad = put_plan(
        c,
        b,
        "2026-10-01",
        [{"categoryId": repair, "amount": "100", "target": "500", "heldInId": savings["id"]}],
    )
    assert bad.status_code == 422 and bad.json()["errors"][0]["field"] == "heldInId"
    assert (
        put_plan(
            c, b, "2026-10-01", [{"categoryId": repair, "amount": "100", "target": "500"}]
        ).status_code
        == 200
    )
    r = put_plan(c, b, "2026-12-01", [{"categoryId": repair, "amount": "100"}])
    assert r.status_code == 409 and r.json()["asks"][0]["code"] == "reserve-balance"
    assert "200.00" in r.json()["asks"][0]["message"]
    r = put_plan(c, b, "2026-12-01", [{"categoryId": repair, "amount": "100"}], confirm=True)
    assert r.status_code == 200
    assert row(month(c, b, "2026-12"), "Transportation › Car maintenance")["target"] is None


def test_where_the_money_is(server, frozen):
    c, acct, cat, b = setup_budget(server)
    savings = new_account(c, name="Ally", type="savings", mask="2222")
    card = new_account(c, name="Visa", type="credit-card", mask="1111")
    v = c.get(f"/ui/api/budgets/{b['id']}").json()
    r = c.patch(
        f"/ui/api/budgets/{b['id']}",
        json={"reserves": True, "accountIds": [acct["id"], savings["id"], card["id"]]},
        headers={"If-Match": str(v["version"])},
    )
    assert r.status_code == 200, r.text
    roof, repair = cat["Housing › Maintenance"], cat["Transportation › Car maintenance"]
    lines = [
        {"categoryId": roof, "amount": "150", "target": "5000", "heldInId": savings["id"]},
        {"categoryId": repair, "amount": "100", "target": "5000", "heldInId": savings["id"]},
    ]
    assert put_plan(c, b, "2026-11-01", lines).status_code == 200
    # November's 250 moved in; December's not yet. A repair in December paid by card.
    add(c, acct["id"], "-250.00", "2026-11-28", payee="To Ally")
    add(c, savings["id"], "250.00", "2026-11-28", payee="From checking", kind="deposit")
    add(c, card["id"], "-80.00", "2026-12-03", payee="Midas", categoryId=repair)
    for day in ("2026-11-05", "2026-12-05"):
        add(c, acct["id"], "-500.00", day, payee="Card payment")
        add(c, card["id"], "500.00", day, payee="Thank you", kind="deposit")
    interest = add(c, savings["id"], "4.20", "2026-12-01", payee="Interest", kind="interest")
    w = c.get(f"/ui/api/budgets/{b['id']}/where", params={"month": "2026-12"}).json()
    (h,) = w["heldIn"]
    assert (h["accountName"], h["total"], h["movedIn"], h["toMove"]) == (
        "Ally",
        "420.00",
        "250.00",
        "170.00",
    )
    assert h["movedFromName"] == "Checking"
    assert [(x["payee"], x["free"]) for x in h["unassigned"]] == [("Interest", "4.20")]
    (card_view,) = w["cards"]
    assert card_view["paidFromName"] == "Checking" and card_view["paid"] == "500.00"
    # The interest given to the reserves: they gain it, and nothing more is asked to move.
    r = c.post(
        f"/ui/api/budgets/{b['id']}/landed",
        json={"transactionId": interest["id"], "to": "spread", "amount": "4.20"},
    )
    assert r.status_code == 200, r.text
    (h,) = r.json()["heldIn"]
    assert (h["total"], h["given"], h["toMove"], h["unassigned"]) == (
        "424.20",
        "4.20",
        "170.00",
        [],
    )
    # Savings of the account's own, moved in by transfer, kept out of the reserves' figures.
    own = add(c, acct["id"], "-500.00", "2026-12-02", payee="To Ally, our savings")
    pair = add(c, savings["id"], "500.00", "2026-12-02", payee="From checking", kind="deposit")
    assert pair["transferId"] == own["id"]
    (h,) = c.get(f"/ui/api/budgets/{b['id']}/where", params={"month": "2026-12"}).json()["heldIn"]
    assert h["toMove"] == "-330.00"
    assert [(x["amount"], x["kept"]) for x in h["transfers"]] == [("500.00", False)]
    r = c.post(
        f"/ui/api/budgets/{b['id']}/landed",
        json={"transactionId": pair["id"], "to": "own", "amount": "500.00"},
    )
    assert r.status_code == 200, r.text
    (h,) = r.json()["heldIn"]
    assert h["toMove"] == "170.00" and h["transfers"][0]["kept"]
    bad = c.post(
        f"/ui/api/budgets/{b['id']}/landed",
        json={"transactionId": pair["id"], "to": "own", "amount": "1.00"},
    )
    assert bad.status_code == 422
    # A repair paid from checking: money goes back, and with one withdrawal already this
    # month, a second would go past the account's limit of one.
    v = c.get(f"/ui/api/accounts/{savings['id']}").json()
    assert saved(change(c, "Acct", v, withdrawalsAMonth=1))["withdrawalsAMonth"] == 1
    add(c, acct["id"], "-300.00", "2026-12-12", payee="Roofer", categoryId=roof)
    (h,) = c.get(f"/ui/api/budgets/{b['id']}/where", params={"month": "2026-12"}).json()["heldIn"]
    assert h["toMove"] == "-130.00" and h["withdrawals"] == 0 and not h["overLimit"]
    add(c, savings["id"], "-20.00", "2026-12-14", payee="Wire fee", kind="fee")
    (h,) = c.get(f"/ui/api/budgets/{b['id']}/where", params={"month": "2026-12"}).json()["heldIn"]
    assert h["withdrawals"] == 1 and h["overLimit"]
    bad = edit(c, "Acct", f"/ui/api/accounts/{acct['id']}", withdrawalsAMonth=3)
    assert bad.status_code == 422
