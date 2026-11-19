"""A transaction and its splits saved as the transaction dialog's draft saves them (requirements
S2.6, S2.9, S7.3.5, S12.15, S13.8.11)."""

import datetime as dt

import pytest
from edits import asked, change, make, new_id, reconcile, remove, saved
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
    """A part changed in place keeps its id, so a payback paired with it stays."""
    c, acct, cat, b = setup_budget(server)
    owing = {"reimbursable": "20.00", "owedBy": "Acme"}
    r, txn = made(c, acct, cat, [("-50.00", {}), ("-30.00", {}), ("-20.00", owing)])
    assert r.status_code == 200, r.text
    t = c.get(f"/ui/api/transactions/{txn}").json()
    by = {str(x["amount"]): x for x in t["splits"]}
    first, second, owed = by["-50.00"], by["-30.00"], by["-20.00"]
    deposit = make(
        c,
        "Txn",
        accountId=acct["id"],
        date="2026-10-09",
        amount="20.00",
        kind="deposit",
        payee="Acme",
    ).json()
    r = make(
        c, "Rmbrs", spendingId=txn, splitId=owed["id"], paybackId=deposit["id"], amount="20.00"
    )
    assert r.status_code == 200, r.text
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
    rec = reconcile(c, acct["id"], "2026-10-31", "-100.00")
    saved(change(c, "Recon", rec, finished=True))
    t = c.get(f"/ui/api/transactions/{txn}").json()
    r = remove(c, "Txn", t)
    assert asked(r) == ["reconciled-period"]
    assert "statement of Oct 31, 2026" in r.json()["asks"][0]["message"]
    assert remove(c, "Txn", t, confirm=True).status_code == 200
    assert c.get(f"/ui/api/transactions/{txn}").status_code == 404


def test_a_transaction_keeps_its_account(server, frozen):
    c, acct, cat, _ = setup_budget(server)
    other = make(c, "Acct", name="Savings", type="savings").json()
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
    other = make(c, "Bdgt", name="Other", accountIds=[]).json()
    r = change(c, "Txn", t, leftOutOf={"add": [other["id"]], "remove": []})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "not-in-budget"
    # Counted again, then left out once more: the same leave-out comes back.
    t = saved(change(c, "Txn", t, leftOutOf={"add": [], "remove": [b["id"]]}))
    assert t["leftOutOf"] == []
    t = saved(change(c, "Txn", t, leftOutOf={"add": [b["id"]], "remove": []}))
    assert t["leftOutOf"] == [b["id"]]
    # A budget the caller can't change, or none, is refused on the field.
    r = change(c, "Txn", t, leftOutOf={"add": [new_id("Bdgt")], "remove": []})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "budget-unknown"


def test_a_split_transaction_deleted_takes_its_parts(server, frozen):
    """The dialog sends the transaction's delete alone; its parts go with it (S13.8.11.3)."""
    c, acct, cat, _ = setup_budget(server)
    _, txn = made(c, acct, cat, [("-60.00", {}), ("-40.00", {})])
    t = c.get(f"/ui/api/transactions/{txn}").json()
    assert remove(c, "Txn", t).status_code == 200
    assert c.get(f"/ui/api/transactions/{txn}").status_code == 404


def _stored(server, kind):
    """Each activity of a kind, as stored: its actor, subject, owner and detail."""
    from moolakata.store.entities.core import Activity

    with server.db.read(unscoped="test") as s:
        return [(x.actorId, x.subjectKind, x.subjectId, x.ownerId, x.detail)
                for x in s.query(Activity).filter_by(kind=kind)]  # fmt: skip


def _errors(r):
    assert r.status_code == 422, r.text
    return [(e["field"], e["code"], e["message"]) for e in r.json()["errors"]]


def test_a_transaction_is_deleted_by_who_writes_its_account_and_logged_for_its_owner(
    server, frozen
):
    """S10.3: a read share deletes nothing; one who writes the account deletes, and the
    owner's activity says so (S10.8), counting one."""
    from edits import share
    from test_accounts import add, new_account
    from test_sharing import setup

    from moolakata.store.entities.accounts import Transaction

    u, c = setup(server)
    jane, john = c["jane"], c["john"]
    a = new_account(jane)
    t = add(jane, a["id"], "-10.00", "2026-10-02", payee="Shop")
    saved(share(jane, "account", a["id"], users={u["john"].id: "read"}))
    r = remove(john, "Txn", t)
    assert (r.status_code, r.json()["errors"][0]["code"]) == (403, "share-read-only"), r.text
    saved(share(jane, "account", a["id"], users={u["john"].id: "write"}))
    assert remove(john, "Txn", t).status_code == 200
    with server.db.read(unscoped="test") as s:
        assert s.get(Transaction, t["id"]).deletedById == u["john"].id
    assert _stored(server, "transaction.deleted") == [
        (u["john"].id, "account", a["id"], u["jane"].id, '{"count": 1}')
    ]


def test_left_out_by_one_who_writes_the_budget_and_counted_again(server, frozen):
    """S7.3.5: one who only reads the account leaves its transaction out of a budget they
    write, never of one they read; each budget refused says why, and each change is the
    budget owner's activity."""
    from edits import share
    from test_accounts import add, new_account
    from test_sharing import setup

    from moolakata.store.entities.budgets import BudgetLeaveOut

    u, c = setup(server)
    jane, john = c["jane"], c["john"]
    a = new_account(jane)
    t = add(jane, a["id"], "-10.00", "2026-10-02", payee="Shop")
    b = make(jane, "Bdgt", name="Household", accountIds=[a["id"]]).json()
    seen = make(jane, "Bdgt", name="Seen", accountIds=[a["id"]]).json()
    saved(share(jane, "account", a["id"], users={u["john"].id: "read"}))
    saved(share(jane, "budget", b["id"], users={u["john"].id: "write"}))
    saved(share(jane, "budget", seen["id"], users={u["john"].id: "read"}))
    t = john.get(f"/ui/api/transactions/{t['id']}").json()
    unknown = ("leftOutOf", "budget-unknown", "Not a budget you can change.")
    r = change(john, "Txn", t, leftOutOf={"add": [seen["id"]], "remove": []})
    assert _errors(r) == [unknown]
    r = change(john, "Txn", t, leftOutOf={"add": [new_id("Bdgt"), new_id("Bdgt")], "remove": []})
    assert _errors(r) == [unknown, unknown]
    others = [make(john, "Bdgt", name=n, accountIds=[]).json()["id"] for n in ("Other", "Third")]
    r = change(john, "Txn", t, leftOutOf={"add": others, "remove": []})
    assert sorted(_errors(r)) == [
        ("leftOutOf", "not-in-budget", "Other doesn't count it."),
        ("leftOutOf", "not-in-budget", "Third doesn't count it."),
    ]
    t = saved(change(john, "Txn", t, leftOutOf={"add": [b["id"]], "remove": []}))
    t = saved(change(john, "Txn", t, leftOutOf={"add": [], "remove": [b["id"]]}))
    assert t["leftOutOf"] == []
    with server.db.read(unscoped="test") as s:
        assert s.get(BudgetLeaveOut, (b["id"], t["id"])).deletedById == u["john"].id
    logged = (u["john"].id, "budget", b["id"], u["jane"].id, "{}")
    assert _stored(server, "budget.left-out") == [logged]
    assert _stored(server, "budget.counted-again") == [logged]


def test_a_part_added_in_a_reconciled_period_asks_first_and_one_deleted_says_by_whom(
    server, frozen
):
    """S2.7: a part made changes the transaction, so a reconciled period asks first."""
    from moolakata.store.entities.accounts import Split

    c, acct, cat, _ = setup_budget(server)
    _, txn = made(c, acct, cat, [])
    saved(change(c, "Txn", c.get(f"/ui/api/transactions/{txn}").json(), cleared=True))
    saved(change(c, "Recon", reconcile(c, acct["id"], "2026-10-31", "-100.00"), finished=True))
    part = {"transactionId": txn, "amount": "-100.00", "categoryId": cat["Travel"]}
    ops = [{"op": "create", "entity": "Split", "id": new("Split"), "fields": part}]
    r = save(c, ops)
    assert asked(r) == ["reconciled-period"]
    asks = [{"code": x["code"], "id": x["id"]} for x in r.json()["asks"]]
    assert save(c, ops, asks).status_code == 200
    # A part taken away is marked by who took it (schema.md §4.1).
    _, txn = made(c, acct, cat, [("-60.00", {}), ("-40.00", {})])
    first, gone = c.get(f"/ui/api/transactions/{txn}").json()["splits"]
    ops = [{"op": "delete", "entity": "Split", "id": gone["id"], "version": gone["version"]},
           {"op": "update", "entity": "Split", "id": first["id"], "version": first["version"],
            "fields": {**part, "transactionId": txn}}]  # fmt: skip
    assert save(c, ops).status_code == 200
    me = c.get("/ui/api/session").json()["user"]["id"]
    with server.db.read(unscoped="test") as s:
        assert s.get(Split, gone["id"]).deletedById == me
