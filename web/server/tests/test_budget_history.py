"""A budget's past months read history as it was (requirements R3.10, S7.1.7, S7.3.2): what
is done after a month never changes it, but for a correction. Closing an account, or taking it
out of the budget, keeps it in the months before; deleting an account is a correction, and its
transactions leave every month; a transfer is judged by the account its other half is in,
whatever the viewer can see."""

import datetime as dt
import random

import pytest
from conftest import make_user, sign_in
from edits import budget_accounts, drop, edit, loan_payment, share, terms
from test_accounts import add, new_account
from test_budgets import month, setup_budget

from moolakata import clock

T0 = dt.datetime(2026, 12, 20, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def _figures(c, b, m):
    v = month(c, b, m)
    return (v["spent"], v["saved"], v["income"], [(x["amount"]) for x in v["moved"]])


def test_a_transfer_out_keeps_counting_when_the_other_account_is_deleted(server, frozen):
    """The claim (CR3-45): October's $300 to Ally, filed as savings, stays saved once Ally is
    deleted: the half in Checking is real, money left the budget."""
    c, acct, cat, b = setup_budget(server)
    ally = new_account(c, name="Ally", type="savings", mask="2222")
    add(c, acct["id"], "-300.00", "2026-10-05", payee="To Ally",
        categoryId=cat["Savings › Emergency fund"])  # fmt: skip
    add(c, ally["id"], "300.00", "2026-10-05", payee="From checking", kind="deposit")
    assert month(c, b, "2026-10")["saved"] == "300.00"
    assert drop(c, "Acct", f"/ui/api/accounts/{ally['id']}", confirm=True).status_code == 200
    assert month(c, b, "2026-10")["saved"] == "300.00"


def test_an_uncategorised_transfer_to_a_deleted_account_is_listed_as_moved(server, frozen):
    c, acct, _, b = setup_budget(server)
    ally = new_account(c, name="Ally", type="savings", mask="2222")
    add(c, acct["id"], "-300.00", "2026-10-05", payee="To Ally")
    add(c, ally["id"], "300.00", "2026-10-05", payee="From checking", kind="deposit")
    drop(c, "Acct", f"/ui/api/accounts/{ally['id']}", confirm=True)
    (moved,) = month(c, b, "2026-10")["moved"]
    assert moved["amount"] == "-300.00" and moved["otherAccountName"] == "a deleted account"


def test_a_closed_account_counts_up_to_the_month_it_closed(server, frozen):
    c, acct, cat, b = setup_budget(server)
    card = new_account(c, name="Visa", type="credit-card", mask="1111")
    assert budget_accounts(c, b, [acct["id"], card["id"]]).status_code == 200
    add(c, card["id"], "-80.00", "2026-09-03", payee="Kroger", categoryId=cat["Food › Groceries"])
    add(c, card["id"], "-20.00", "2026-11-03", payee="Late fee", categoryId=cat["Food › Groceries"])
    before = _figures(c, b, "2026-09")
    r = edit(c, "Acct", f"/ui/api/accounts/{card['id']}", closedOn="2026-10-15")
    assert r.status_code == 200, r.text
    assert _figures(c, b, "2026-09") == before
    assert month(c, b, "2026-11")["spent"] == "0.00"  # after the month it closed


def test_deleting_an_account_is_a_correction(server, frozen):
    """Its transactions leave every month, past ones included, and a reviewed month says so."""
    c, acct, cat, b = setup_budget(server)
    card = new_account(c, name="Visa", type="credit-card", mask="1111")
    assert budget_accounts(c, b, [acct["id"], card["id"]]).status_code == 200
    add(c, card["id"], "-80.00", "2026-09-03", payee="Kroger", categoryId=cat["Food › Groceries"])
    r = c.post(f"/ui/api/budgets/{b['id']}/review", json={"month": "2026-09-01"})
    assert r.status_code == 200, r.text
    assert drop(c, "Acct", f"/ui/api/accounts/{card['id']}", confirm=True).status_code == 200
    assert month(c, b, "2026-09")["spent"] == "0.00"
    review = c.get(f"/ui/api/budgets/{b['id']}/review", params={"month": "2026-09"}).json()
    assert review["reviewed"]["changes"]


def test_an_account_taken_out_stays_in_the_months_before(server, frozen):
    c, acct, cat, b = setup_budget(server)
    card = new_account(c, name="Visa", type="credit-card", mask="1111")
    assert budget_accounts(c, b, [acct["id"], card["id"]]).status_code == 200
    add(c, card["id"], "-80.00", "2026-09-03", payee="Kroger", categoryId=cat["Food › Groceries"])
    add(c, card["id"], "-40.00", "2026-10-03", payee="Kroger", categoryId=cat["Food › Groceries"])
    assert budget_accounts(c, b, [acct["id"]], month="2026-10").status_code == 200
    assert month(c, b, "2026-09")["spent"] == "80.00"
    assert month(c, b, "2026-10")["spent"] == "0.00"
    rows = c.get(f"/ui/api/budgets/{b['id']}/accounts").json()["items"]
    assert [(x["accountId"], x["untilMonth"]) for x in rows if x["accountId"] == card["id"]] == [
        (card["id"], "2026-09-01")
    ]
    # Counted again from December: a record of its own, the gap kept.
    assert budget_accounts(c, b, [acct["id"], card["id"]], month="2026-12").status_code == 200
    assert month(c, b, "2026-10")["spent"] == "0.00"
    rows = c.get(f"/ui/api/budgets/{b['id']}/accounts").json()["items"]
    spans = sorted((x["fromMonth"] or "", x["untilMonth"] or "") for x in rows
                   if x["accountId"] == card["id"])  # fmt: skip
    assert spans == [("", "2026-09-01"), ("2026-12-01", "")]


def test_two_records_of_one_account_never_share_a_month(server, frozen):
    c, acct, _, b = setup_budget(server)
    r = budget_accounts(c, b, [acct["id"]], month="2026-12")  # counted already: nothing to do
    assert r.status_code == 200
    from edits import new_id

    fields = {"budgetId": b["id"], "accountId": acct["id"], "fromMonth": "2026-12-01"}
    op = {"op": "create", "entity": "BdgAc", "id": new_id("BdgAc"), "fields": fields}
    r = c.post("/ui/api/save", json={"ops": [op]})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "months-overlap"


def test_a_receiver_counts_a_transfer_to_an_account_they_cant_see(server, frozen):
    """Bob reads Checking but not Alice's Ally: the $300 left the budget all the same (S7.1.1),
    and the account is named to him only as not shared."""
    c, acct, cat, b = setup_budget(server)
    make_user(server, "bob")
    bob = sign_in(server, "bob")
    bob_id = bob.get("/ui/api/session").json()["user"]["id"]
    ally = new_account(c, name="Ally", type="savings", mask="2222")
    add(c, acct["id"], "-300.00", "2026-10-05", payee="To Ally",
        categoryId=cat["Savings › Emergency fund"])  # fmt: skip
    add(c, ally["id"], "300.00", "2026-10-05", payee="From checking", kind="deposit")
    add(c, acct["id"], "-50.00", "2026-10-06", payee="To Ally")
    add(c, ally["id"], "50.00", "2026-10-06", payee="From checking", kind="deposit")
    share(c, "budget", b["id"], users={bob_id: "read"})
    share(c, "account", acct["id"], users={bob_id: "read"})
    mine, theirs = month(c, b, "2026-10"), month(bob, b, "2026-10")
    assert mine["saved"] == theirs["saved"] == "300.00"
    assert [(x["amount"], x["otherAccountName"]) for x in theirs["moved"]] == [
        ("-50.00", "an account not shared")
    ]


def test_a_receiver_counts_a_payment_to_a_loan_they_cant_see_whole(server, frozen):
    """The split would show the loan's interest and principal, so a receiver who can't read
    the loan sees the payment whole (S7.1.1, S1.9.7)."""
    c, acct, _, b = setup_budget(server)
    make_user(server, "bob")
    bob = sign_in(server, "bob")
    bob_id = bob.get("/ui/api/session").json()["user"]["id"]
    loan = new_account(c, name="Home", type="mortgage", institution="Rocket")
    assert terms(c, loan["id"], principal="300000", startDate="2026-09-01", termMonths=360,
                 rate="6", escrowTax="300", escrowInsurance="100").status_code == 200  # fmt: skip
    r = loan_payment(c, loan["id"], "2026-10-01", "2198.65", from_account=acct["id"])
    assert r.status_code == 200, r.text
    share(c, "budget", b["id"], users={bob_id: "read"})
    share(c, "account", acct["id"], users={bob_id: "read"})
    mine, theirs = month(c, b, "2026-10"), month(bob, b, "2026-10")
    assert (mine["spent"], mine["saved"]) == ("1900.00", "298.65")
    assert (theirs["spent"], theirs["saved"]) == ("2198.65", "0.00")


@pytest.mark.parametrize("seed", range(6))
def test_nothing_done_after_a_month_changes_it(server, frozen, seed):
    """Generated: a history over three accounts in and out of the budget, then events after
    September (an account closed, taken out, a cash account deleted, an outside account
    deleted); September's figures never move."""
    rnd = random.Random(seed)
    c, acct, cat, b = setup_budget(server)
    card = new_account(c, name="Visa", type="credit-card", mask="1111")
    outside = new_account(c, name="Ally", type="savings", mask="2222")
    cash = new_account(c, name="Wallet", type="cash")
    assert budget_accounts(c, b, [acct["id"], card["id"]]).status_code == 200
    spend = [cat["Food › Groceries"], cat["Savings › Emergency fund"], None]
    for _ in range(8):
        day = f"2026-09-{rnd.randint(1, 28):02d}"
        amount = f"-{rnd.randint(1, 300)}.00"
        kind = rnd.choice(["spend", "card", "out", "cash"])
        if kind == "spend":
            add(c, acct["id"], amount, day, payee="Shop", categoryId=rnd.choice(spend))
        elif kind == "card":
            add(c, card["id"], amount, day, payee="Shop", categoryId=spend[0])
        else:
            other = outside if kind == "out" else cash
            add(c, acct["id"], amount, day, payee="Out", categoryId=rnd.choice(spend))
            add(c, other["id"], amount[1:], day, payee="In", kind="deposit")
    before = _figures(c, b, "2026-09")
    events = [
        lambda: edit(c, "Acct", f"/ui/api/accounts/{card['id']}", closedOn="2026-11-02"),
        lambda: budget_accounts(c, b, [acct["id"]], month="2026-10"),
        lambda: drop(c, "Acct", f"/ui/api/accounts/{outside['id']}", confirm=True),
        lambda: drop(c, "Acct", f"/ui/api/accounts/{cash['id']}", confirm=True),
    ]
    rnd.shuffle(events)
    for event in events:
        r = event()
        assert r.status_code == 200, r.text
        assert _figures(c, b, "2026-09") == before
