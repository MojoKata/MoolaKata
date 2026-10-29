"""Reimbursable spending (requirements S2.9, S7.3.4)."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import change, make, remove, saved
from test_accounts import add, new_account
from test_budgets import month, setup_budget

from moolakata import clock

T0 = dt.datetime(2026, 10, 24, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def awaiting(c, b):
    r = c.get(f"/ui/api/budgets/{b['id']}/reimbursements")
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_awaited_spending_isnt_counted_and_a_payback_isnt_income(server, frozen):
    c, acct, cat, b = setup_budget(server)
    flight = add(
        c,
        acct["id"],
        "-412.60",
        "2026-10-02",
        payee="Delta Air Lines",
        categoryId=cat["Travel"],
        reimbursable="412.60",
        owedBy="Acme Corp",
    )
    assert flight["reimbursable"] == "412.60" and flight["owedBy"] == "Acme Corp"
    payroll = add(
        c,
        acct["id"],
        "4820.00",
        "2026-10-15",
        payee="Acme Payroll",
        categoryId=cat["Income › Salary"],
    )
    back = add(
        c,
        acct["id"],
        "412.60",
        "2026-10-09",
        payee="ACME CORP EXPENSE RPT",
        categoryId=cat["Income › Other income"],
    )
    v = month(c, b, "2026-10")
    assert v["spent"] == "0.00" and v["income"] == "5232.60"
    (item,) = awaiting(c, b)
    assert (item["payee"], item["awaited"], item["ageDays"], item["owedBy"]) == (
        "Delta Air Lines",
        "412.60",
        22,
        "Acme Corp",
    )
    # The deposit of the amount awaited is offered first.
    assert [o["transactionId"] for o in item["offers"]][:2] == [back["id"], payroll["id"]]
    r = make(c, "Rmbrs", spendingId=flight["id"], paybackId=back["id"], amount="412.60")
    assert r.status_code == 200, r.text
    assert awaiting(c, b) == []
    v = month(c, b, "2026-10")
    assert v["spent"] == "0.00" and v["income"] == "4820.00"
    assert c.get(f"/ui/api/transactions/{flight['id']}").json()["paidBack"] == "412.60"
    # Unpaired again: awaited again, and the deposit is income again.
    pairing = r.json()
    r = remove(c, "Rmbrs", pairing)
    assert r.status_code == 200, r.text
    assert month(c, b, "2026-10")["income"] == "5232.60"


def test_a_split_part_paid_back_and_the_rest_counted_again(server, frozen):
    c, acct, cat, b = setup_budget(server)
    util = cat["Housing › Utilities"]
    r = make(
        c,
        "Txn",
        accountId=acct["id"],
        date="2026-10-06",
        amount="-175.00",
        payee="City Utilities",
        splits=[
            {"amount": "-87.50", "categoryId": util},
            {"amount": "-87.50", "categoryId": util, "reimbursable": "87.50", "owedBy": "Sam"},
        ],
    )
    assert r.status_code == 200, r.text
    bill = r.json()
    half = next(x for x in bill["splits"] if x["reimbursable"])
    venmo = add(c, acct["id"], "50.00", "2026-10-10", payee="Venmo from Sam")
    assert month(c, b, "2026-10")["spent"] == "87.50"
    r = make(
        c, "Rmbrs", spendingId=bill["id"], splitId=half["id"], paybackId=venmo["id"], amount="50.00"
    )
    assert r.status_code == 200, r.text
    (item,) = awaiting(c, b)
    assert item["awaited"] == "37.50" and item["splitId"] == half["id"]
    # Sam won't pay the rest: lowered to what was paid back, the rest counts again.
    t = c.get(f"/ui/api/transactions/{bill['id']}").json()
    part = next(x for x in t["splits"] if x["reimbursable"])
    saved(change(c, "Split", part, reimbursable="50.00"))
    assert month(c, b, "2026-10")["spent"] == "125.00"
    # The part changed in place keeps its payback (CR3-29): nothing more is awaited.
    assert awaiting(c, b) == []
    t = c.get(f"/ui/api/transactions/{bill['id']}").json()
    assert [x["id"] for x in t["splits"]] == [x["id"] for x in bill["splits"]]
    saved(change(c, "Txn", t, memo="water and power"))
    assert awaiting(c, b) == [], "an edit of the transaction leaves its parts alone"


def test_marks_and_pairings_are_checked(server, frozen):
    c, acct, _, _ = setup_budget(server)
    bad = make(
        c, "Txn", accountId=acct["id"], date="2026-10-03", amount="-20.00", reimbursable="25.00"
    )
    assert bad.status_code == 422 and bad.json()["errors"][0]["field"] == "reimbursable"
    bad = make(
        c, "Txn", accountId=acct["id"], date="2026-10-03", amount="20.00", reimbursable="5.00"
    )
    assert bad.status_code == 422
    lunch = add(c, acct["id"], "-20.00", "2026-10-03", reimbursable="20.00")
    plain = add(c, acct["id"], "-30.00", "2026-10-03")
    deposit = add(c, acct["id"], "15.00", "2026-10-04")
    r = make(c, "Rmbrs", spendingId=plain["id"], paybackId=deposit["id"], amount="10.00")
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "not-reimbursable"
    r = make(c, "Rmbrs", spendingId=lunch["id"], paybackId=deposit["id"], amount="16.00")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "amount"
    r = make(c, "Rmbrs", spendingId=lunch["id"], paybackId=plain["id"], amount="10.00")
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "not-a-deposit"
    # Someone else can't pair with the account's spending.
    make_user(server, "bob")
    bob = sign_in(server, "bob")
    mine = new_account(bob, name="Bob's checking")
    theirs = add(bob, mine["id"], "20.00", "2026-10-05")
    r = make(bob, "Rmbrs", spendingId=lunch["id"], paybackId=theirs["id"], amount="10.00")
    assert r.status_code in (403, 404)
