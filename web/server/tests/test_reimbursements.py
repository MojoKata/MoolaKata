"""Reimbursable spending (requirements S2.9, S7.3.4)."""

import datetime as dt
from decimal import Decimal

import pytest
from conftest import make_user, sign_in
from edits import change, make, remove, saved, share
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
    # The part changed in place keeps its payback: nothing more is awaited.
    assert awaiting(c, b) == []
    t = c.get(f"/ui/api/transactions/{bill['id']}").json()
    assert [x["id"] for x in t["splits"]] == [x["id"] for x in bill["splits"]]
    saved(change(c, "Txn", t, memo="water and power"))
    assert awaiting(c, b) == [], "an edit of the transaction leaves its parts alone"


def test_a_receiver_awaits_what_an_account_they_cant_see_awaits_unnamed(server, frozen):
    """S7.1.1, S2.9: John reads Jane's budget and her Checking, not her Ally: what Ally awaits
    counts for him all the same, as one row of *an account not shared* with no payee, date,
    age or id, and nothing to pair."""
    c, acct, cat, _ = setup_budget(server)
    make_user(server, "john")
    john = sign_in(server, "john")
    john_id = john.get("/ui/api/session").json()["user"]["id"]
    ally = new_account(c, name="Ally", type="savings", mask="2222")
    b = make(c, "Bdgt", name="Both", accountIds=[acct["id"], ally["id"]]).json()
    add(c, acct["id"], "-412.60", "2026-10-02", payee="Delta Air Lines",
        categoryId=cat["Travel"], reimbursable="412.60", owedBy="Acme Corp")  # fmt: skip
    hidden = [
        add(
            c,
            ally["id"],
            "-100.00",
            "2026-10-03",
            payee="Dentist",
            reimbursable="100.00",
            owedBy="Insurer",
        ),
        add(c, ally["id"], "-50.00", "2026-10-04", payee="Pharmacy", reimbursable="50.00"),
    ]
    share(c, "budget", b["id"], users={john_id: "read"})
    share(c, "account", acct["id"], users={john_id: "read"})
    mine = awaiting(c, b)
    r = john.get(f"/ui/api/budgets/{b['id']}/reimbursements")
    assert r.status_code == 200, r.text
    theirs = r.json()["items"]
    assert sum(Decimal(x["awaited"]) for x in mine) == sum(Decimal(x["awaited"]) for x in theirs)
    seen, (other,) = theirs[:1], theirs[1:]
    assert seen[0]["payee"] == "Delta Air Lines" and seen[0]["accountName"] == acct["name"]
    assert other == {
        "spendingId": None, "splitId": None, "date": None, "payee": None,
        "accountName": "an account not shared", "category": None, "owedBy": None,
        "reimbursable": "150.00", "paidBack": "0.00", "awaited": "150.00", "ageDays": None,
        "offers": [],
    }  # fmt: skip
    for secret in (
        ally["id"],
        "Ally",
        "Dentist",
        "Pharmacy",
        "Insurer",
        *(t["id"] for t in hidden),
    ):
        assert secret not in r.text, secret


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
    make_user(server, "john")
    john = sign_in(server, "john")
    mine = new_account(john, name="John's checking")
    theirs = add(john, mine["id"], "20.00", "2026-10-05")
    r = make(john, "Rmbrs", spendingId=lunch["id"], paybackId=theirs["id"], amount="10.00")
    assert r.status_code in (403, 404)
