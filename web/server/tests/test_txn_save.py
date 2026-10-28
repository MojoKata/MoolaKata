"""A transaction and its splits saved as the transaction dialog's draft saves them (requirements
S2.6, S2.9, S7.3.5, S12.15, S13.8.11)."""

import datetime as dt

import pytest
from edits import asked, change, remove, saved
from test_budgets import setup_budget
from test_save import made_at

from moolakata import clock

T0 = dt.datetime(2026, 10, 24, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def new(prefix: str) -> str:
    return made_at(prefix, clock.now())


def save(c, ops, confirm=()):
    return c.post("/ui/api/save", json={"ops": ops, "confirm": list(confirm)})


def made(c, acct, cat, parts):
    """A bill of $100 made in one save with its parts, as a new transaction's dialog sends it."""
    txn = new("Txn")
    ops = [{"op": "create", "entity": "Txn", "id": txn,
            "fields": {"accountId": acct["id"], "date": "2026-10-02", "kind": "withdrawal",
                       "amount": "-100.00", "payee": "Hotel"}}]  # fmt: skip
    for amount, extra in parts:
        ops.append({"op": "create", "entity": "Split", "id": new("Split"),
                    "fields": {"transactionId": txn, "amount": amount,
                               "categoryId": cat["Travel"], **extra}})  # fmt: skip
    return save(c, ops), txn


def test_a_new_transaction_and_its_parts_in_one_save(server, frozen):
    c, acct, cat, _ = setup_budget(server)
    r, txn = made(c, acct, cat, [("-60.00", {}), ("-40.00", {"memo": "minibar"})])
    assert r.status_code == 200, r.text
    t = c.get(f"/ui/api/transactions/{txn}").json()
    assert sorted(str(x["amount"]) for x in t["splits"]) == ["-40.00", "-60.00"]
    assert t["categoryId"] is None
    assert {x["memo"] for x in t["splits"]} == {None, "minibar"}


def test_parts_that_dont_add_up_save_nothing(server, frozen):
    c, acct, cat, _ = setup_budget(server)
    r, txn = made(c, acct, cat, [("-60.00", {}), ("-30.00", {})])
    assert r.status_code == 422, r.text
    (err,) = r.json()["errors"]
    assert (err["field"], err["code"], err["id"]) == ("splits", "splits-unbalanced", txn)
    assert c.get(f"/ui/api/transactions/{txn}").status_code == 404


def test_a_part_changed_or_taken_away_keeps_the_others_and_their_paybacks(server, frozen):
    """CR3-29: a part changed in place keeps its id, so a payback paired with it stays."""
    c, acct, cat, b = setup_budget(server)
    owing = {"reimbursable": "20.00", "owedBy": "Acme"}
    r, txn = made(c, acct, cat, [("-50.00", {}), ("-30.00", {}), ("-20.00", owing)])
    assert r.status_code == 200, r.text
    t = c.get(f"/ui/api/transactions/{txn}").json()
    by = {str(x["amount"]): x for x in t["splits"]}
    first, second, owed = by["-50.00"], by["-30.00"], by["-20.00"]
    deposit = c.post(
        "/ui/api/transactions",
        json={"accountId": acct["id"], "date": "2026-10-09", "amount": "20.00", "kind": "deposit",
              "payee": "Acme"},
    ).json()  # fmt: skip
    r = c.post(
        "/ui/api/reimbursements",
        json={"spendingId": txn, "splitId": owed["id"], "paybackId": deposit["id"],
              "amount": "20.00"},
    )  # fmt: skip
    assert r.status_code == 201, r.text
    ops = [
        {"op": "update", "entity": "Split", "id": first["id"], "version": first["version"],
         "fields": {"amount": "-80.00"}},
        {"op": "delete", "entity": "Split", "id": second["id"], "version": second["version"]},
        {"op": "update", "entity": "Txn", "id": txn, "version": t["version"],
         "fields": {"memo": "two nights"}},
    ]  # fmt: skip
    r = save(c, ops)
    assert r.status_code == 200, r.text
    t = c.get(f"/ui/api/transactions/{txn}").json()
    assert {x["id"] for x in t["splits"]} == {first["id"], owed["id"]}
    assert t["paidBack"] == "20.00"
    items = c.get(f"/ui/api/budgets/{b['id']}/reimbursements").json()["items"]
    assert items == [], "the part paid back is not awaited again"


def test_deleting_a_transaction_in_a_reconciled_period_asks_first(server, frozen):
    c, acct, cat, _ = setup_budget(server)
    r, txn = made(c, acct, cat, [])
    t = c.get(f"/ui/api/transactions/{txn}").json()
    t = saved(change(c, "Txn", t, cleared=True))
    rec = c.post(
        f"/ui/api/accounts/{acct['id']}/reconciliations",
        json={"statementDate": "2026-10-31", "statementBalance": "-100.00"},
    ).json()
    r = c.patch(
        f"/ui/api/reconciliations/{rec['id']}",
        json={"finish": True},
        headers={"If-Match": str(rec["version"])},
    )
    assert r.status_code == 200, r.text
    t = c.get(f"/ui/api/transactions/{txn}").json()
    r = remove(c, "Txn", t)
    assert asked(r) == ["reconciled-period"]
    assert "statement of Oct 31, 2026" in r.json()["asks"][0]["message"]
    assert remove(c, "Txn", t, confirm=True).status_code == 200
    assert c.get(f"/ui/api/transactions/{txn}").status_code == 404


def test_a_transaction_keeps_its_account(server, frozen):
    c, acct, cat, _ = setup_budget(server)
    other = c.post("/ui/api/accounts", json={"name": "Savings", "type": "savings"}).json()
    _, txn = made(c, acct, cat, [])
    t = c.get(f"/ui/api/transactions/{txn}").json()
    r = change(c, "Txn", t, accountId=other["id"])
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "accountId"


def test_left_out_of_a_budget_from_the_transactions_draft(server, frozen):
    c, acct, cat, b = setup_budget(server)
    _, txn = made(c, acct, cat, [])
    t = c.get(f"/ui/api/transactions/{txn}").json()
    assert t["leftOutOf"] == []
    t = saved(change(c, "Txn", t, leftOutOf={"add": [b["id"]], "remove": []}))
    assert t["leftOutOf"] == [b["id"]]
    (row,) = c.get(f"/ui/api/transactions/{txn}/budgets").json()["items"]
    assert row["leftOut"]
    other = c.post("/ui/api/budgets", json={"name": "Other", "accountIds": []}).json()
    r = change(c, "Txn", t, leftOutOf={"add": [other["id"]], "remove": []})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "not-in-budget"
