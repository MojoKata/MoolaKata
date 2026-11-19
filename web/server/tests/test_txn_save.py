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


def test_a_transfer_paired_or_unpaired_in_a_reconciled_period_asks_nothing(server, frozen):
    """S1.7: pairing the halves of a transfer by hand, or undoing it, changes neither one's
    amount nor its day, so a reconciled period (S2.7) has nothing to ask."""
    from test_accounts import add, new_account

    c, acct, cat, _ = setup_budget(server)
    _, txn = made(c, acct, cat, [])
    path = f"/ui/api/transactions/{txn}"
    saved(change(c, "Txn", c.get(path).json(), cleared=True))
    saved(change(c, "Recon", reconcile(c, acct["id"], "2026-10-31", "-100.00"), finished=True))
    sav = new_account(c, name="Savings", type="savings", mask="2222")
    half = add(c, sav["id"], "100.00", "2026-10-25", kind="deposit")
    assert _paired(c, txn) is None
    saved(edit(c, "Txn", path, transferWithId=half["id"]))
    assert _paired(c, txn) == half["id"]
    saved(edit(c, "Txn", path, transferWithId=None))
    assert (_paired(c, txn), _paired(c, half["id"])) == (None, None)


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
