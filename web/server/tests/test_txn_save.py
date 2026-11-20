"""A transaction and its splits saved as the transaction dialog's draft saves them (requirements
S2.6, S2.9, S7.3.5, S12.15, S13.8.11)."""

import datetime as dt

import pytest
from edits import asked, change, edit, make, new_id, reconcile, remove, saved
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


UNBALANCED = ("splits", "splits-unbalanced", "The parts must add up to the transaction's amount.")


def test_parts_that_dont_add_up_save_nothing(server, frozen):
    c, acct, cat, _ = setup_budget(server)
    r, txn = made(c, acct, cat, [("-60.00", {}), ("-30.00", {})])
    assert r.status_code == 422, r.text
    (err,) = r.json()["errors"]
    assert (err["field"], err["code"], err["message"], err["id"]) == (*UNBALANCED, txn)
    assert c.get(f"/ui/api/transactions/{txn}").status_code == 404


def test_each_transaction_in_one_save_has_its_own_parts_add_up(server, frozen):
    """S2.6: two split transactions saved together are each checked against their own parts:
    the second's not adding up is refused though the first's do."""
    c, acct, cat, _ = setup_budget(server)
    ops, txns = [], []
    for parts in (("-60.00", "-40.00"), ("-60.00", "-30.00")):
        txn = new("Txn")
        txns.append(txn)
        ops.append({"op": "create", "entity": "Txn", "id": txn,
                    "fields": {"accountId": acct["id"], "date": "2026-10-02",
                               "kind": "withdrawal", "amount": "-100.00"}})  # fmt: skip
        ops += [{"op": "create", "entity": "Split", "id": new("Split"),
                 "fields": {"transactionId": txn, "amount": x, "categoryId": cat["Travel"]}}
                for x in parts]  # fmt: skip
    r = save(c, ops)
    assert _errors(r) == [UNBALANCED]
    assert r.json()["errors"][0]["id"] == txns[1]


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


def _paired(c, txn_id):
    return c.get(f"/ui/api/transactions/{txn_id}").json()["transferId"]


def test_a_transfer_matched_by_hand_names_a_live_half_of_another_account_moving_cash(
    server, frozen
):
    """S1.7: the other half named is a live transaction of another account, neither moving a
    holding, for the same amount the other way; each refusal says which, and pairs nothing."""
    from conftest import make_user, sign_in
    from test_accounts import add, new_account

    make_user(server, "jane")
    c = sign_in(server, "jane")
    chk, sav = new_account(c), new_account(c, name="Savings", type="savings", mask="2222")
    brk = new_account(c, name="Brokerage", type="brokerage", mask="3333")
    # Dates apart by more than a match's window, so only a hand pairs them.
    into = add(c, chk["id"], "50.00", "2026-10-01", kind="deposit")
    gone = add(c, sav["id"], "-50.00", "2026-10-20")
    saved(remove(c, "Txn", gone))
    same = add(c, chk["id"], "-50.00", "2026-10-20")
    bought = add(c, brk["id"], "-50.00", "2026-10-20", kind="buy", symbol="VTI", quantity="1",
                 price="50", fees="0")  # fmt: skip
    short = add(c, sav["id"], "-49.00", "2026-10-20")
    unknown = ("transferWithId", "transaction-unknown", "No such transaction.")
    apart = ("transferWithId", "not-a-transfer", "A transfer is between two accounts.")
    for other, refusal in (
        (new("Txn"), unknown),
        (gone["id"], unknown),
        (into["id"], unknown),  # itself
        (same["id"], apart),
        (bought["id"], apart),  # a holding's
        (short["id"], ("amount", "amount-mismatch", "The two halves' amounts differ.")),
    ):
        path = f"/ui/api/transactions/{into['id']}"
        assert _errors(edit(c, "Txn", path, transferWithId=other)) == [refusal], other
        assert _paired(c, into["id"]) is None
    half = add(c, sav["id"], "-50.00", "2026-10-20")
    assert saved(edit(c, "Txn", f"/ui/api/transactions/{into['id']}", transferWithId=half["id"]))
    assert (_paired(c, into["id"]), _paired(c, half["id"])) == (half["id"], into["id"])


def test_a_half_matched_elsewhere_is_taken_unless_this_save_made_it(server, frozen):
    """S1.7: a transfer already matched stays as it is; one this save made, matched on its
    own, goes to the half that names it, and the match it made is undone."""
    from conftest import make_user, sign_in
    from test_accounts import add, new_account

    make_user(server, "jane")
    c = sign_in(server, "jane")
    chk, sav = new_account(c), new_account(c, name="Savings", type="savings", mask="2222")
    card = new_account(c, name="Visa", type="credit-card", mask="1111")
    out = add(c, chk["id"], "-500.00", "2026-09-15")
    paid = add(c, card["id"], "500.00", "2026-09-16", kind="deposit")
    assert _paired(c, paid["id"]) == out["id"]
    moved = add(c, sav["id"], "-500.00", "2026-10-01")
    r = edit(c, "Txn", f"/ui/api/transactions/{moved['id']}", transferWithId=paid["id"])
    assert _errors(r) == [("transferWithId", "transfer-taken", "That transaction isn't free.")]
    assert (_paired(c, paid["id"]), _paired(c, moved["id"])) == (out["id"], None)
    # Made in one save: the card's half matches the checking on its own, then is named.
    early = add(c, chk["id"], "-700.00", "2026-10-01")
    x, t = new("Txn"), new("Txn")
    ops = [
        {"op": "create", "entity": "Txn", "id": t,
         "fields": {"accountId": sav["id"], "date": "2026-10-02", "amount": "-700.00",
                    "transferWithId": x}},
        {"op": "create", "entity": "Txn", "id": x,
         "fields": {"accountId": card["id"], "date": "2026-10-02", "amount": "700.00",
                    "kind": "deposit"}},
    ]  # fmt: skip
    assert save(c, ops).status_code == 200
    assert (_paired(c, t), _paired(c, x), _paired(c, early["id"])) == (x, t, None)


def test_a_half_named_is_of_an_account_the_caller_writes(server, frozen):
    """S1.7, S10.3: a half the caller only reads is not theirs to pair; written, it is."""
    from edits import share
    from test_accounts import add, new_account
    from test_sharing import setup

    u, c = setup(server)
    jane, john = c["jane"], c["john"]
    theirs = new_account(jane)
    half = add(jane, theirs["id"], "-30.00", "2026-10-01")
    mine = new_account(john, name="John's", mask="4444")
    fields = {"accountId": mine["id"], "date": "2026-10-20", "amount": "30.00",
              "kind": "deposit", "transferWithId": half["id"]}  # fmt: skip
    saved(share(jane, "account", theirs["id"], users={u["john"].id: "read"}))
    r = save(john, [{"op": "create", "entity": "Txn", "id": new("Txn"), "fields": fields}])
    assert r.status_code == 403, r.text
    assert [(e["code"], e["message"]) for e in r.json()["errors"]] == [
        ("share-read-only", "You can read this account but not change it.")
    ]
    saved(share(jane, "account", theirs["id"], users={u["john"].id: "write"}))
    t = new("Txn")
    r = save(john, [{"op": "create", "entity": "Txn", "id": t, "fields": fields}])
    assert r.status_code == 200, r.text
    assert (_paired(john, t), _paired(john, half["id"])) == (half["id"], t)


def test_each_transfer_named_in_one_save_is_paired(server, frozen):
    """S1.7: two matches made by hand in one save each pair their halves."""
    from conftest import make_user, sign_in
    from test_accounts import add, new_account

    make_user(server, "jane")
    c = sign_in(server, "jane")
    chk, sav = new_account(c), new_account(c, name="Savings", type="savings", mask="2222")
    ones = [add(c, chk["id"], f"-{n}.00", "2026-10-01") for n in (100, 200)]
    others = [add(c, sav["id"], f"{n}.00", "2026-10-20", kind="deposit") for n in (100, 200)]
    pairs = zip(ones, others, strict=True)
    ops = [{"op": "update", "entity": "Txn", "id": t["id"], "version": t["version"],
            "fields": {"transferWithId": o["id"]}} for t, o in pairs]  # fmt: skip
    r = save(c, ops)
    assert r.status_code == 200, r.text
    assert [_paired(c, t["id"]) for t in ones] == [o["id"] for o in others]


def test_a_transaction_keeps_its_account_holding_and_contract_each_refused_on_its_field(
    server, frozen
):
    """S2.1, S3.2: what a transaction is of (its account, its holding, a split's ratio, an
    option's contract) is made with it and never changed; each is refused on its own field."""
    from conftest import make_user, sign_in
    from test_accounts import add, new_account

    make_user(server, "jane")
    c = sign_in(server, "jane")
    brk = new_account(c, name="Brokerage", type="brokerage")
    other = new_account(c, name="Savings", type="savings", mask="2222")
    buy = add(c, brk["id"], "-100.00", "2026-10-02", kind="buy", symbol="VTI", quantity="1",
              price="100", fees="0")  # fmt: skip
    path = f"/ui/api/transactions/{buy['id']}"
    for field, value in (
        ("accountId", other["id"]),
        ("symbol", "VOO"),
        ("instrumentId", new_id("Instr")),
        ("splitRatio", "2"),
        ("right", "call"),
        ("strike", "100"),
        ("expiry", "2026-12-18"),
        ("multiplier", 10),
    ):
        r = edit(c, "Txn", path, **{field: value})
        assert _errors(r) == [
            (field, "transaction-fixed", "A transaction keeps its account and holding.")
        ], field
    assert c.get(path).json()["version"] == buy["version"]


def test_a_change_is_logged_for_the_owner_by_its_fields_and_a_tick_or_tags_alone_are_not(
    server, frozen
):
    """S10.8: a transaction changed is its account owner's activity, by who changed it,
    naming the fields changed and counting one; ticking it cleared, or the saver's own tags
    alone, log nothing."""
    from edits import share, tag
    from test_accounts import add, new_account
    from test_sharing import setup

    u, c = setup(server)
    jane, john = c["jane"], c["john"]
    a = new_account(jane)
    t = add(jane, a["id"], "-10.00", "2026-10-02", payee="Shop")
    saved(share(jane, "account", a["id"], users={u["john"].id: "write"}))
    path = f"/ui/api/transactions/{t['id']}"
    saved(edit(john, "Txn", path, memo="lunch", payee="Cafe"))
    saved(edit(john, "Txn", path, cleared=True))
    saved(edit(john, "Txn", path, tagIds=[tag(john, "work")]))
    assert _stored(server, "transaction.updated") == [
        (u["john"].id, "account", a["id"], u["jane"].id,
         '{"count": 1, "fields": ["payee", "memo"]}')
    ]  # fmt: skip


def test_one_who_reads_an_account_changes_and_unpairs_none_of_its_transactions(server, frozen):
    """S10.3: a read share changes nothing of a transaction: neither its fields nor the
    transfer it is half of (S1.7)."""
    from edits import share
    from test_accounts import add, new_account
    from test_sharing import setup

    u, c = setup(server)
    jane, john = c["jane"], c["john"]
    chk = new_account(jane)
    card = new_account(jane, name="Visa", type="credit-card", mask="1111")
    out = add(jane, chk["id"], "-500.00", "2026-09-15")
    paid = add(jane, card["id"], "500.00", "2026-09-16", kind="deposit")
    assert _paired(jane, paid["id"]) == out["id"]
    saved(share(jane, "account", card["id"], users={u["john"].id: "read"}))
    path = f"/ui/api/transactions/{paid['id']}"
    for fields in ({"memo": "card"}, {"transferWithId": None}):
        r = edit(john, "Txn", path, **fields)
        assert r.status_code == 403, r.text
        assert [(e["code"], e["message"]) for e in r.json()["errors"]] == [
            ("share-read-only", "You can read this account but not change it.")
        ]
    assert jane.get(path).json()["memo"] is None
    assert _paired(jane, paid["id"]) == out["id"]


def test_a_transfer_paired_or_unpaired_in_a_reconciled_period_asks_first(server, frozen):
    """S1.11.6: pairing the halves of a transfer by hand, or undoing it, changes what each
    counts as (a transfer, or spending and income), so a reconciled period of either half
    asks first, as any other edit there does."""
    from test_accounts import add, new_account

    c, acct, cat, _ = setup_budget(server)
    _, txn = made(c, acct, cat, [])
    path = f"/ui/api/transactions/{txn}"
    saved(change(c, "Txn", c.get(path).json(), cleared=True))
    saved(change(c, "Recon", reconcile(c, acct["id"], "2026-10-31", "-100.00"), finished=True))
    sav = new_account(c, name="Savings", type="savings", mask="2222")
    half = add(c, sav["id"], "100.00", "2026-10-25", kind="deposit")
    assert _paired(c, txn) is None
    assert asked(edit(c, "Txn", path, transferWithId=half["id"])) == ["reconciled-period"]
    assert _paired(c, txn) is None
    saved(edit(c, "Txn", path, confirm=True, transferWithId=half["id"]))
    assert _paired(c, txn) == half["id"]
    assert asked(edit(c, "Txn", path, transferWithId=None)) == ["reconciled-period"]
    saved(edit(c, "Txn", path, confirm=True, transferWithId=None))
    assert (_paired(c, txn), _paired(c, half["id"])) == (None, None)
    # From the other side: the half named is in the reconciled period, so pairing it asks.
    other = f"/ui/api/transactions/{half['id']}"
    assert asked(edit(c, "Txn", other, transferWithId=txn)) == ["reconciled-period"]
    saved(edit(c, "Txn", other, confirm=True, transferWithId=txn))
    # And letting it go asks too: the half it was paired with is the reconciled one.
    assert asked(edit(c, "Txn", other, transferWithId=None)) == ["reconciled-period"]


def test_tags_changed_on_a_transaction_are_the_savers_own_and_one_taken_off_says_by_whom(
    server, frozen
):
    """S2.6: the tags a change sends are the saver's own on it, in place of those it had; a
    tag taken off is marked by who took it off (schema.md §4.1)."""
    from edits import tag

    from moolakata.store.entities.accounts import TransactionTag

    c, acct, cat, _ = setup_budget(server)
    _, txn = made(c, acct, cat, [])
    path = f"/ui/api/transactions/{txn}"
    work, home = tag(c, "work"), tag(c, "home")
    assert saved(edit(c, "Txn", path, tagIds=[work]))["tags"] == ["work"]
    assert saved(edit(c, "Txn", path, tagIds=[home]))["tags"] == ["home"]
    me = c.get("/ui/api/session").json()["user"]["id"]
    with server.db.read(unscoped="test") as s:
        row = s.query(TransactionTag).filter_by(transactionId=txn, tagId=work).one()
        assert row.deletedById == me


def test_lots_typed_again_replace_only_that_moves_own_each_marked_when_and_by_whom(server, frozen):
    """S2.2: shares moved in, their lots typed again, take the place of the lots they had,
    each marked deleted by who typed over it, when they did; another move's lots, and lots
    typed over before, stay as they were. Each change logs what it changed (S10.8)."""
    from conftest import make_user, sign_in
    from test_accounts import _lots_made, add, new_account

    from moolakata.store.entities.accounts import Lot

    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, name="Brokerage", type="brokerage")["id"]
    other = add(c, a, "0.00", "2026-09-10", kind="transfer-in", symbol="VTI", quantity="4")
    t = add(c, a, "0.00", "2026-09-10", kind="transfer-in", symbol="KO", quantity="5")
    path = f"/ui/api/transactions/{t['id']}"
    for day in ("2020-01-02", "2021-01-04"):
        lots = [{"acquiredOn": day, "quantity": "5", "costBasis": "250"}]
        saved(edit(c, "Txn", path, transferLots=lots))
        clock.fix(clock.now() + dt.timedelta(hours=1))
    assert _lots_made(server, other["id"]) == [("2026-09-10", 4, None, True, True)]
    saved(edit(c, "Txn", f"/ui/api/transactions/{other['id']}", costBasis="400.00"))
    me = c.get("/ui/api/session").json()["user"]["id"]
    with server.db.read(unscoped="test") as s:
        rows = s.query(Lot).filter_by(transactionId=t["id"]).order_by(Lot.acquiredOn).all()
        gone = [(str(x.acquiredOn), x.deletedById, x.deletedAt) for x in rows if x.deleted]
    assert [x[:2] for x in gone] == [("2020-01-02", me), ("2026-09-10", me)]
    # The lot of the day it moved in was typed over first, an hour before the next.
    assert gone[1][2] < gone[0][2]
    assert _lots_made(server, t["id"]) == [("2021-01-04", 5, 250, False, False)]
    assert sorted(x[4] for x in _stored(server, "transaction.updated")) == [
        '{"count": 1, "fields": ["costBasis"]}',
        '{"count": 1, "fields": ["transferLots"]}',
        '{"count": 1, "fields": ["transferLots"]}',
    ]


def test_a_transaction_or_part_deleted_or_never_made_is_not_found(server, frozen):
    """S13.8.11: a change or a delete of a transaction or a part that was deleted, or never
    made, finds nothing to change: refused as not found."""
    c, acct, cat, _ = setup_budget(server)
    _, txn = made(c, acct, cat, [("-60.00", {}), ("-40.00", {})])
    kept, gone = c.get(f"/ui/api/transactions/{txn}").json()["splits"]
    ops = [{"op": "delete", "entity": "Split", "id": gone["id"], "version": gone["version"]},
           {"op": "update", "entity": "Split", "id": kept["id"], "version": kept["version"],
            "fields": {"amount": "-100.00"}}]  # fmt: skip
    assert save(c, ops).status_code == 200
    _, spent = made(c, acct, cat, [])
    spent = c.get(f"/ui/api/transactions/{spent}").json()
    saved(remove(c, "Txn", spent))
    for entity, record in (
        ("Split", gone),
        ("Split", {"id": new("Split"), "version": 1}),
        ("Txn", spent),
        ("Txn", {"id": new("Txn"), "version": 1}),
    ):
        for r in (change(c, entity, record, memo="again"), remove(c, entity, record)):
            assert r.status_code == 404, r.text
            assert [(e["field"], e["code"], e["message"]) for e in r.json()["errors"]] == [
                (None, "not-found", "Not found")
            ], record["id"]


def test_a_part_keeps_its_transaction_and_who_owes_it_is_kept_without_spaces(server, frozen):
    """S2.6: a part stays with the transaction it is of, refused on its field; S2.9: who owes
    a part back is kept without the spaces around it, and none when not typed."""
    c, acct, cat, _ = setup_budget(server)
    owing = {"reimbursable": "20.00", "owedBy": "  Acme "}
    _, txn = made(c, acct, cat, [("-80.00", {}), ("-20.00", owing)])
    _, other = made(c, acct, cat, [])
    parts = c.get(f"/ui/api/transactions/{txn}").json()["splits"]
    assert sorted((str(x["amount"]), x["owedBy"]) for x in parts) == [
        ("-20.00", "Acme"),
        ("-80.00", None),
    ]
    r = change(c, "Split", parts[0], transactionId=other)
    assert _errors(r) == [("transactionId", "split-fixed", "A part stays with its transaction.")]


def test_a_part_changed_in_a_reconciled_period_asks_first(server, frozen):
    """S2.7: a part changed changes the transaction, so a reconciled period asks first."""
    c, acct, cat, _ = setup_budget(server)
    _, txn = made(c, acct, cat, [("-60.00", {}), ("-40.00", {})])
    path = f"/ui/api/transactions/{txn}"
    saved(change(c, "Txn", c.get(path).json(), cleared=True))
    saved(change(c, "Recon", reconcile(c, acct["id"], "2026-10-31", "-100.00"), finished=True))
    part = c.get(path).json()["splits"][0]
    assert asked(change(c, "Split", part, memo="breakfast")) == ["reconciled-period"]
    saved(change(c, "Split", part, confirm=True, memo="breakfast"))


def test_one_who_reads_an_account_changes_and_deletes_none_of_its_parts(server, frozen):
    """S10.3: a read share changes nothing of a transaction's parts (S2.6)."""
    from edits import share
    from test_accounts import new_account
    from test_sharing import setup

    u, c = setup(server)
    jane, john = c["jane"], c["john"]
    a = new_account(jane)
    groceries = {x["path"]: x["id"] for x in jane.get("/ui/api/categories").json()["items"]}[
        "Food › Groceries"
    ]
    _, txn = made(jane, a, {"Travel": groceries}, [("-100.00", {})])
    saved(share(jane, "account", a["id"], users={u["john"].id: "read"}))
    (part,) = john.get(f"/ui/api/transactions/{txn}").json()["splits"]
    for r in (change(john, "Split", part, memo="mine"), remove(john, "Split", part)):
        assert r.status_code == 403, r.text
        assert [(e["code"], e["message"]) for e in r.json()["errors"]] == [
            ("share-read-only", "You can read this account but not change it.")
        ]
    assert jane.get(f"/ui/api/transactions/{txn}").json()["splits"] == [part]


def test_lots_sent_again_as_they_are_type_nothing_over(server, frozen):
    """S2.2: a transfer in's lots sent as it has them, in the order bought, change nothing:
    neither typed over nor logged (S10.8); nor does one still missing its day bought, sent
    with none."""
    from conftest import make_user, sign_in
    from test_accounts import _lots_made, add, new_account

    from moolakata.store.entities.accounts import Lot

    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, name="Brokerage", type="brokerage")["id"]
    add(c, a, "-100.00", "2026-09-01", kind="buy", symbol="VTI", quantity="1", price="100",
        fees="0")  # fmt: skip
    t = add(c, a, "0.00", "2026-09-10", kind="transfer-in", symbol="KO", quantity="5")
    missing = add(c, a, "0.00", "2026-09-10", kind="transfer-in", symbol="KO", quantity="2")
    # Typed out of the order bought, they are read back in it.
    typed = [{"acquiredOn": "2021-01-04", "quantity": "3", "costBasis": "300"},
             {"acquiredOn": "2020-01-02", "quantity": "2", "costBasis": "100"}]  # fmt: skip
    path = f"/ui/api/transactions/{t['id']}"
    saved(edit(c, "Txn", path, transferLots=typed))
    saved(edit(c, "Txn", path, transferLots=typed[::-1], memo="from Schwab"))
    path = f"/ui/api/transactions/{missing['id']}"
    saved(edit(c, "Txn", path, transferLots=None, memo="a gift"))
    assert _lots_made(server, t["id"]) == [
        ("2020-01-02", 2, 100, False, False),
        ("2021-01-04", 3, 300, False, False),
    ]
    assert _lots_made(server, missing["id"]) == [("2026-09-10", 2, None, True, True)]
    with server.db.read(unscoped="test") as s:
        rows = s.query(Lot).filter(Lot.transactionId.in_([t["id"], missing["id"]])).all()
        assert [str(x.acquiredOn) for x in rows if x.deleted] == ["2026-09-10"]
    assert sorted(x[4] for x in _stored(server, "transaction.updated")) == [
        '{"count": 1, "fields": ["memo"]}',
        '{"count": 1, "fields": ["memo"]}',
        '{"count": 1, "fields": ["transferLots"]}',
    ]


def test_a_basis_typed_or_cleared_is_the_moves_own_and_a_buy_keeps_its_cost(server, frozen):
    """S2.2: a basis typed for shares moved in is their own lot's, whatever another move's is,
    and cleared, it is missing again; a buy's lot keeps its cost when its draft sends no basis,
    and its own symbol sent with it is no change of holding (S2.1)."""
    from conftest import make_user, sign_in
    from test_accounts import _lots_made, add, new_account

    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, name="Brokerage", type="brokerage")["id"]
    first = add(c, a, "0.00", "2026-09-01", kind="transfer-in", symbol="VTI", quantity="4",
                costBasis="100.00")  # fmt: skip
    t = add(c, a, "0.00", "2026-09-10", kind="transfer-in", symbol="KO", quantity="5",
            costBasis="400.00")  # fmt: skip
    path = f"/ui/api/transactions/{t['id']}"
    saved(edit(c, "Txn", path, costBasis="100.00"))
    assert _lots_made(server, t["id"]) == [("2026-09-10", 5, 100, False, True)]
    saved(edit(c, "Txn", path, costBasis=None))
    assert _lots_made(server, t["id"]) == [("2026-09-10", 5, None, True, True)]
    assert _lots_made(server, first["id"]) == [("2026-09-01", 4, 100, False, True)]
    bought = add(c, a, "-100.00", "2026-09-02", kind="buy", symbol="VTI", quantity="1",
                 price="100", fees="0")  # fmt: skip
    path = f"/ui/api/transactions/{bought['id']}"
    saved(edit(c, "Txn", path, symbol="VTI", costBasis=None, memo="monthly"))
    assert _lots_made(server, bought["id"]) == [("2026-09-02", 1, 100, False, False)]


def test_one_who_reads_an_account_leaves_a_trade_out_with_its_draft_as_it_is(server, frozen):
    """S7.3.5: one who only reads the account leaves a trade out of a budget they write, the
    draft sending the trade's holding, basis and lots as they are: none of them changes, so
    the account's write is not needed (S10.3)."""
    from edits import share
    from test_accounts import add, new_account
    from test_sharing import setup

    u, c = setup(server)
    jane, john = c["jane"], c["john"]
    brk = new_account(jane, name="Brokerage", type="brokerage")["id"]
    buy = add(jane, brk, "-100.00", "2026-10-02", kind="buy", symbol="VTI", quantity="1",
              price="100", fees="0")  # fmt: skip
    b = make(jane, "Bdgt", name="Household", accountIds=[brk]).json()
    saved(share(jane, "account", brk, users={u["john"].id: "read"}))
    saved(share(jane, "budget", b["id"], users={u["john"].id: "write"}))
    path = f"/ui/api/transactions/{buy['id']}"
    t = saved(edit(john, "Txn", path, symbol="VTI", costBasis=None, transferLots=None,
                   leftOutOf={"add": [b["id"]], "remove": []}))  # fmt: skip
    assert t["leftOutOf"] == [b["id"]]


def test_tags_sent_as_what_to_add_and_take_away_keep_the_others(server, frozen):
    """S13.8.11.1: tags sent as what to add and what to take away change those alone; the
    saver's other tags on the transaction stay (S2.6)."""
    from edits import tag

    c, acct, cat, _ = setup_budget(server)
    _, txn = made(c, acct, cat, [])
    path = f"/ui/api/transactions/{txn}"
    work, home = tag(c, "work"), tag(c, "home")
    saved(edit(c, "Txn", path, tagIds=[work]))
    t = saved(edit(c, "Txn", path, tagIds={"add": [home], "remove": []}))
    assert t["tags"] == ["home", "work"]
    t = saved(edit(c, "Txn", path, tagIds={"add": [], "remove": [work]}))
    assert t["tags"] == ["home"]


def test_a_new_transaction_is_left_out_of_a_budget_from_its_draft(server, frozen):
    """S7.3.5: a transaction made from its dialog with a budget it is left out of is left out
    of it from the start."""
    c, acct, _, b = setup_budget(server)
    txn = new("Txn")
    fields = {"accountId": acct["id"], "date": "2026-10-02", "amount": "-100.00",
              "payee": "Hotel", "leftOutOf": [b["id"]]}  # fmt: skip
    r = save(c, [{"op": "create", "entity": "Txn", "id": txn, "fields": fields}])
    assert r.status_code == 200, r.text
    assert c.get(f"/ui/api/transactions/{txn}").json()["leftOutOf"] == [b["id"]]


def test_a_transaction_reads_only_its_own_tags_budgets_left_out_of_and_paybacks(server, frozen):
    """S2.6, S7.3.5, S2.9: a transaction reads the tags it has, the budgets it is left out of
    and what was paid back of it; another of the same account reads none of them."""
    from edits import tag

    c, acct, cat, b = setup_budget(server)
    _, one = made(c, acct, cat, [])
    _, two = made(c, acct, cat, [])
    work = tag(c, "work")
    saved(edit(c, "Txn", f"/ui/api/transactions/{one}", tagIds=[work],
               leftOutOf={"add": [b["id"]], "remove": []}))  # fmt: skip
    keys = ("tags", "tagIds", "leftOutOf", "paidBack")
    got = [c.get(f"/ui/api/transactions/{t}").json() for t in (one, two)]
    assert [{k: t[k] for k in keys} for t in got] == [
        {"tags": ["work"], "tagIds": [work], "leftOutOf": [b["id"]], "paidBack": "0.00"},
        {"tags": [], "tagIds": [], "leftOutOf": [], "paidBack": "0.00"},
    ]


def test_the_other_half_of_a_transfer_is_named_only_to_one_who_reads_its_account(server, frozen):
    """S1.7, S10.3: a half paired with one of an account its reader doesn't read names neither
    that half nor its account; one who reads both reads the pair."""
    from edits import share
    from test_accounts import add, new_account
    from test_sharing import setup

    u, c = setup(server)
    jane, john = c["jane"], c["john"]
    theirs = new_account(jane)
    half = add(jane, theirs["id"], "-30.00", "2026-10-01")
    mine = new_account(john, name="John's", mask="4444")
    saved(share(jane, "account", theirs["id"], users={u["john"].id: "write"}))
    t = new("Txn")
    fields = {"accountId": mine["id"], "date": "2026-10-20", "amount": "30.00",
              "kind": "deposit", "transferWithId": half["id"]}  # fmt: skip
    r = save(john, [{"op": "create", "entity": "Txn", "id": t, "fields": fields}])
    assert r.status_code == 200, r.text
    keys = ("transferId", "transferAccountName")
    path = f"/ui/api/transactions/{half['id']}"
    got = [[who.get(path).json()[k] for k in keys] for who in (jane, john)]
    assert got == [[None, None], [t, "John's"]]


def _reconciled_bill(server, parts):
    """A $100 bill with its parts, cleared and inside a finished reconciliation."""
    c, acct, cat, _ = setup_budget(server)
    _, txn = made(c, acct, cat, parts)
    path = f"/ui/api/transactions/{txn}"
    saved(change(c, "Txn", c.get(path).json(), cleared=True))
    saved(change(c, "Recon", reconcile(c, acct["id"], "2026-10-31", "-100.00"), finished=True))
    return c, cat, txn, path


def test_a_part_taken_away_in_a_reconciled_period_asks_first(server, frozen):
    """S1.11.6: taking a part away changes the transaction, as adding or changing one does."""
    c, _, _, path = _reconciled_bill(server, [("-60.00", {}), ("-40.00", {})])
    first, gone = c.get(path).json()["splits"]
    ops = [{"op": "delete", "entity": "Split", "id": gone["id"], "version": gone["version"]},
           {"op": "update", "entity": "Split", "id": first["id"], "version": first["version"],
            "fields": {"amount": "-100.00"}}]  # fmt: skip
    r = save(c, ops)
    assert asked(r) == ["reconciled-period", "reconciled-period"]
    assert {x["id"] for x in r.json()["asks"]} == {first["id"], gone["id"]}
    asks = [{"code": x["code"], "id": x["id"]} for x in r.json()["asks"]]
    assert save(c, ops, asks).status_code == 200
    assert [p["amount"] for p in c.get(path).json()["splits"]] == ["-100.00"]


def test_a_save_that_asks_is_judged_whole_once_answered_never_on_what_is_left(server, frozen):
    """S13.8.11.5: a part taken away and another added in a reconciled period ask, and the
    parts are added up only on the whole save: never a refusal for the half the question
    held back."""
    c, cat, txn, path = _reconciled_bill(server, [("-60.00", {}), ("-40.00", {})])
    _, gone = c.get(path).json()["splits"]
    ops = [{"op": "delete", "entity": "Split", "id": gone["id"], "version": gone["version"]},
           {"op": "create", "entity": "Split", "id": new("Split"),
            "fields": {"transactionId": txn, "amount": gone["amount"],
                       "categoryId": cat["Travel"]}}]  # fmt: skip
    r = save(c, ops)
    assert r.status_code == 409, r.text
    asks = [{"code": x["code"], "id": x["id"]} for x in r.json()["asks"]]
    r = save(c, ops, asks)
    assert r.status_code == 200, r.text
    assert sorted(str(p["amount"]) for p in c.get(path).json()["splits"]) == ["-40.00", "-60.00"]
    assert gone["id"] not in {p["id"] for p in c.get(path).json()["splits"]}
    # Answered, a save whose parts don't add up is refused for that, as any other is.
    first, _ = c.get(path).json()["splits"]
    ops = [{"op": "update", "entity": "Split", "id": first["id"], "version": first["version"],
            "fields": {"amount": "-1.00"}}]  # fmt: skip
    r = save(c, ops)
    assert asked(r) == ["reconciled-period"]
    asks = [{"code": x["code"], "id": x["id"]} for x in r.json()["asks"]]
    assert _errors(save(c, ops, asks))[0][1] == "splits-unbalanced"


def test_a_trades_quantity_is_more_than_none_made_or_changed(server, frozen):
    """R3.11, S2.2: a trade names how many shares it moves, more than none, the kind saying
    which way; a change can't take it to none, clear it or turn it negative, nor make a
    trade of a transaction with no shares."""
    from conftest import make_user, sign_in
    from test_accounts import add, new_account

    make_user(server, "jane")
    c = sign_in(server, "jane")
    brk = new_account(c, name="Brokerage", type="brokerage")["id"]
    words = "A trade needs its instrument and quantity."
    for kind in ("buy", "sell"):
        t = add(c, brk, "-100.00", "2026-10-02", kind=kind, symbol="VTI", quantity="5",
                price="20", fees="0")  # fmt: skip
        path = f"/ui/api/transactions/{t['id']}"
        none = ("quantity", "trade-incomplete", words)
        less = ("quantity", "quantity-invalid", "More than none.")
        for value, want in (("0", none), (None, none), ("-5", less)):
            assert _errors(edit(c, "Txn", path, quantity=value)) == [want], (kind, value)
        r = make(c, "Txn", accountId=brk, date="2026-10-02", amount="-100.00", kind=kind,
                 symbol="VTI", quantity="-5", price="20", fees="0")  # fmt: skip
        assert _errors(r) == [("quantity", "quantity-invalid", "More than none.")], kind
    cash = add(c, brk, "500.00", "2026-10-02", kind="deposit")
    r = edit(c, "Txn", f"/ui/api/transactions/{cash['id']}", kind="buy", fees="0")
    assert _errors(r) == [("symbol", "trade-incomplete", words)]


def test_only_a_split_has_a_ratio_and_a_split_is_a_corporate_action(server, frozen):
    """S2.4.1: a split is recorded on Positions; a trade sent with a ratio is refused, never
    kept with it (R3.11)."""
    from conftest import make_user, sign_in
    from test_accounts import new_account

    make_user(server, "jane")
    c = sign_in(server, "jane")
    brk = new_account(c, name="Brokerage", type="brokerage")["id"]
    trade = {"accountId": brk, "date": "2026-10-02", "amount": "-100.00", "symbol": "VTI",
             "quantity": "5", "price": "20", "fees": "0"}  # fmt: skip
    r = make(c, "Txn", **trade, kind="buy", splitRatio="2")
    assert _errors(r) == [
        ("splitRatio", "ratio-not-for-kind", "Only a split has a ratio: record it as a corporate"
         " action.")
    ]  # fmt: skip
    r = make(c, "Txn", **{**trade, "amount": "0.00"}, kind="split", splitRatio="2")
    assert _errors(r)[0] == (
        "kind",
        "corporate-kind",
        "Record it as a corporate action on Positions.",
    )
