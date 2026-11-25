"""File retention and pruning (requirements S14.10): when each file expires, from when its
records ended and their periods; what Settings › Storage shows; and pruning, with no backup
first, which keeps every record."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import attach, change, drop, edit, make, save_settings, saved
from sqlalchemy import select
from test_accounts import add, new_account
from test_receipts import png, upload

from moolakata import clock
from moolakata.store.entities.accounts import Category

T0 = dt.datetime(2033, 3, 1, 12, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def cat(server, name, years=None):
    with server.db.tx(unscoped="test") as s:
        c = s.scalars(select(Category).where(Category.name == name)).first()
        c.keepReceiptsYears = years
        return c.id, c.parentId


def receipt_on(c, txn_id, data):
    rid = upload(c, data).json()["id"]
    saved(attach(c, rid, txn_id))
    return rid


def kept(c, rid):
    d = c.get(f"/ui/api/receipts/{rid}").json()
    return d["keptState"], d["kept"]


def test_a_file_expires_after_its_record_ended_and_its_categorys_period(server, frozen):
    make_user(server, "jane")
    c = sign_in(server, "jane")
    acct = new_account(c)
    child, parent = cat(server, "Doctor")
    with server.db.tx(unscoped="test") as s:
        s.get(Category, parent).keepReceiptsYears = 3  # the subcategory takes its parent's
    t = add(c, acct["id"], "-42.18", "2029-10-02", payee="Clinic", categoryId=child)
    rid = receipt_on(c, t["id"], png((1, 2, 3)))
    assert kept(c, rid) == ("expired", "Expired Oct 2032, prunable")
    newer = add(c, acct["id"], "-10.00", "2030-05-01", payee="Clinic", categoryId=child)
    soon = receipt_on(c, newer["id"], png((4, 5, 6)))
    d = c.get(f"/ui/api/receipts/{soon}").json()
    assert (d["kept"], d["keptSoon"]) == ("Kept until May 2033", True)
    # Uncategorised, attached to nothing, or Keep on: kept for ever.
    loose = add(c, acct["id"], "-5.00", "2020-01-01", payee="Shop")
    assert kept(c, receipt_on(c, loose["id"], png((7, 8, 9))))[0] == "forever"
    assert kept(c, upload(c, png((9, 9, 9))).json()["id"])[0] == "forever"
    saved(edit(c, "Rcpt", f"/ui/api/receipts/{rid}", keep=True))
    assert kept(c, rid) == ("forever", "Kept for ever")


def test_a_lots_receipt_is_kept_while_the_lot_is_open(server, frozen):
    make_user(server, "jane")
    c = sign_in(server, "jane")
    acct = new_account(c, type="brokerage")
    with server.db.tx(unscoped="test") as s:
        any_cat = s.scalars(select(Category)).first()
        any_cat.keepReceiptsYears = 2
        cid = any_cat.id
    buy = make(
        c,
        "Txn",
        accountId=acct["id"],
        date="2020-01-02",
        kind="buy",
        symbol="VTI",
        quantity="10",
        price="100",
        amount="-1000.00",
        categoryId=cid,
    )
    assert buy.status_code == 200, buy.text
    rid = receipt_on(c, buy.json()["id"], png((10, 20, 30)))
    assert kept(c, rid) == ("open", "Kept while the lot is open")
    sell = make(
        c,
        "Txn",
        accountId=acct["id"],
        date="2030-02-03",
        kind="sell",
        symbol="VTI",
        quantity="10",
        price="120",
        amount="1200.00",
    )
    assert sell.status_code == 200, sell.text
    assert kept(c, rid) == ("expired", "Expired Feb 2032, prunable")


def test_a_deleted_accounts_records_end_with_its_deletion(server, frozen):
    """schema.md §6.2, S14.10.2: a record deleted with its account ends at the earlier of its
    own end and the deletion: an open lot, a later transaction or expense all end on Mar 1,
    2033, never at once from the buy's date."""
    from decimal import Decimal

    from moolakata.ids import new_id
    from moolakata.store.entities.accounts import Account
    from moolakata.store.entities.education import QualifiedExpense
    from moolakata.store.entities.receipts import ReceiptLink

    jane = make_user(server, "jane")
    c = sign_in(server, "jane")
    acct = new_account(c, type="brokerage")
    with server.db.tx(unscoped="test") as s:
        any_cat = s.scalars(select(Category)).first()
        any_cat.keepReceiptsYears = 2
        cid = any_cat.id
    r = make(c, "Txn", accountId=acct["id"], date="2020-01-02", kind="buy", symbol="VTI",
             quantity="10", price="100", amount="-1000.00", categoryId=cid)  # fmt: skip
    assert r.status_code == 200, r.text
    buy = r.json()
    later = add(c, acct["id"], "-50.00", "2033-05-01", payee="Fee", categoryId=cid)
    lot_r = receipt_on(c, buy["id"], png((1, 1, 1)))
    later_r = receipt_on(c, later["id"], png((2, 2, 2)))
    expense_r = upload(c, png((4, 4, 4))).json()["id"]
    with server.db.tx(unscoped="test") as s:
        expense = QualifiedExpense(id=new_id("QExpn"), accountId=acct["id"],
                                   date=dt.date(2033, 6, 1), year=2033, kind="tuition",
                                   amount=Decimal("50"), transactionId=later["id"])  # fmt: skip
        s.add(expense)
        s.flush()
        link = ReceiptLink(
            id=new_id("RcLnk"),
            receiptId=expense_r,
            kind="expense",
            itemId=expense.id,
            createdAt=clock.now(),
            linkedById=jane.id,
        )
        s.add(link)
    before = {rid: kept(c, rid)[1] for rid in (lot_r, later_r, expense_r)}
    assert before == {
        lot_r: "Kept while the lot is open",
        later_r: "Kept until May 2035",
        expense_r: "Kept until Jun 2035",
    }
    with server.db.tx(unscoped="test") as s:
        s.get(Account, acct["id"]).mark_deleted(jane.id)
    for rid in (lot_r, later_r, expense_r):
        assert kept(c, rid) == ("until", "Kept until Mar 2035"), before[rid]


def test_an_items_receipt_is_kept_for_ever_sold_or_not(server, frozen):
    """S14.10.2: a physical-asset item has no category, so no period: a receipt kept only
    with one is kept for ever, before its sale and after it, even with every category kept
    for a time (G#675)."""
    from test_assets import item

    make_user(server, "jane")
    c = sign_in(server, "jane")
    with server.db.tx(unscoped="test") as s:
        for x in s.scalars(select(Category)):
            x.keepReceiptsYears = 1
    coll = new_account(c, name="Collectables", type="collectables")
    watch = item(c, coll["id"], name="Watch", acquiredOn="2020-01-10")
    rid = upload(c, png((5, 6, 7))).json()["id"]
    path = f"/ui/api/items/{watch['id']}"
    saved(edit(c, "Item", path, receiptIds={"add": [rid], "remove": []}))
    d = c.get(f"/ui/api/receipts/{rid}").json()
    assert (d["keptState"], d["kept"], d["keptWhy"]) == ("forever", "Kept for ever", None)
    saved(edit(c, "Item", path, soldOn="2021-02-03", proceeds="1500", saleFees="0"))
    assert kept(c, rid) == ("forever", "Kept for ever"), "sold long ago, still kept"


def test_pruning_needs_the_password_again_and_the_count_and_keeps_the_record(
    server, frozen, admin_client
):
    from moolakata.store.entities.users import Session

    make_user(server, "jane")
    c = sign_in(server, "jane")
    acct = new_account(c)
    cid, _ = cat(server, "Groceries", 1)
    t = add(c, acct["id"], "-42.18", "2026-10-02", payee="Kroger", categoryId=cid)
    rid = receipt_on(c, t["id"], png((50, 60, 70)))
    st = admin_client.get("/ui/api/settings/storage").json()
    assert st["expired"]["files"] == 1 and st["expiredBy"][0]["category"] == "Groceries"
    assert "text" not in str(st), "sizes and counts only"
    with server.db.tx(unscoped="test") as s:
        for row in s.scalars(select(Session)):
            row.authAt -= dt.timedelta(minutes=11)
    body = {"categories": ["Groceries"], "deleted": False, "count": 1}
    r = admin_client.post("/ui/api/settings/storage/prune", json=body)
    assert r.json()["code"] == "reauth-required"
    admin_client.post("/ui/api/session/reauth", json={"password": "a long admin passphrase"})
    r = admin_client.post("/ui/api/settings/storage/prune", json={**body, "count": 2})
    assert r.json()["code"] == "count-mismatch"
    r = admin_client.post("/ui/api/settings/storage/prune", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["files"] == 1 and "backup" not in r.json()  # no backup first (S14.10.5)
    d = c.get(f"/ui/api/receipts/{rid}").json()
    assert d["keptState"] == "pruned" and d["kept"].startswith("File pruned")
    assert d["links"] and d["links"][0]["transactionId"] == t["id"], "the record keeps its links"
    assert c.get(f"/ui/api/receipts/{rid}/file").json()["code"] == "file-pruned"
    acts = admin_client.get("/ui/api/activity").json()["items"]
    assert any("pruned 1 files" in a["text"] for a in acts)
    # The same file uploaded again is a new receipt with its file.
    again = upload(c, png((50, 60, 70))).json()
    assert again["id"] != rid
    assert c.get(f"/ui/api/receipts/{again['id']}/file").status_code == 200


def test_a_statement_expires_after_its_period_and_the_storage_setting(server, frozen, admin_client):
    from moolakata import receipts
    from moolakata.store.entities.receipts import Receipt

    jane = make_user(server, "jane")
    c = sign_in(server, "jane")
    acct = new_account(c)
    rid = upload(c, png((90, 91, 92))).json()["id"]
    with server.db.tx(unscoped="test") as s:
        r = s.get(Receipt, rid)
        r.date = dt.date(2027, 9, 30)
        receipts.attach_account(s, jane.id, r, acct["id"])
    assert kept(c, rid)[0] == "forever", "statements are kept for ever by default"
    r = save_settings(admin_client, {"keepStatementsYears": 5})
    assert r.status_code == 200, r.text
    d = c.get(f"/ui/api/receipts/{rid}").json()
    assert (d["keptState"], d["kept"], d["keptWhy"]) == (
        "expired",
        "Expired Sep 2032, prunable",
        "Statements keeps statements 5 years",
    )


def test_a_file_only_a_deleted_receipt_names_is_pruned(server, frozen):
    # S14.10.5: a file is removed once no live receipt needs it; a deleted one doesn't count.
    from moolakata.receipts import retention
    from moolakata.store.entities.receipts import Receipt

    make_user(server, "jane")
    c = sign_in(server, "jane")
    first = upload(c, png((9, 8, 7))).json()["id"]
    second = upload(c, png((9, 8, 7))).json()["id"]
    with server.db.tx(unscoped="test") as s:
        a, b = s.get(Receipt, first), s.get(Receipt, second)
        assert a.fileId == b.fileId, "one file for the same bytes"
        b.mark_deleted(None)
        path = retention.file_path(server.config.receipts_dir, a.fileId)
        assert path.exists()
        assert retention.prune_files(server, s, [a], a.ownerId) > 0
    assert not path.exists()


def _reauth(server):
    from moolakata.store.entities.users import Session

    with server.db.tx(unscoped="test") as s:
        for row in s.scalars(select(Session)):
            row.authAt = clock.now()


def test_a_deleted_receipts_file_is_a_part_of_storage_of_its_own_and_prunable(
    server, frozen, admin_client
):
    # S14.10.4, S14.10.5, S9.7: a file only deleted receipts name is counted in a part of its
    # own, so the parts add up to the directory's size, and Prune offers it on its own.
    from moolakata.receipts import retention
    from moolakata.store.entities.receipts import Receipt

    make_user(server, "jane")
    make_user(server, "john")
    c, john = sign_in(server, "jane"), sign_in(server, "john")
    gone = upload(c, png((11, 22, 33))).json()["id"]
    live = upload(c, png((44, 55, 66))).json()["id"]
    # John's upload of the same bytes is his own receipt over the one file, which Jane's
    # live receipt still needs once he deletes his.
    twin = upload(john, png((44, 55, 66))).json()["id"]
    assert drop(john, "Rcpt", f"/ui/api/receipts/{twin}").status_code == 200
    assert drop(c, "Rcpt", f"/ui/api/receipts/{gone}").status_code == 200
    with server.db.read(unscoped="test") as s:
        gone_file = retention.file_path(server.config.receipts_dir, s.get(Receipt, gone).fileId)
    st = admin_client.get("/ui/api/settings/storage").json()
    assert st["deleted"] == {"files": 1, "bytes": gone_file.stat().st_size}
    parts = ("expired", "later", "forever", "deleted", "orphans")
    assert sum(st[k]["bytes"] for k in parts) == st["receiptsBytes"]
    _reauth(server)
    # Left unticked, a deleted receipt's file stays.
    r = admin_client.post(
        "/ui/api/settings/storage/prune", json={"categories": [], "deleted": False, "count": 1}
    )
    assert r.json()["code"] == "nothing-to-prune"
    r = admin_client.post(
        "/ui/api/settings/storage/prune", json={"categories": [], "deleted": True, "count": 1}
    )
    assert r.status_code == 200, r.text
    assert r.json()["files"] == 1 and not gone_file.exists()
    with server.db.read(unscoped="test") as s:
        assert s.get(Receipt, gone).filePrunedAt is not None, "the row stays, File pruned"
    st = admin_client.get("/ui/api/settings/storage").json()
    assert st["deleted"]["files"] == 0 and st["pruned"] == 1
    assert c.get(f"/ui/api/receipts/{live}/file").status_code == 200


def test_after_a_prune_the_same_file_uploaded_again_is_stored_once(server, frozen):
    # S9.2, S14.10.5: the pruned receipt's file is gone; the next upload of the bytes writes
    # one new file, and every later one, anyone's, is kept with it.
    from moolakata.receipts import retention
    from moolakata.store.entities.receipts import Receipt

    make_user(server, "jane")
    make_user(server, "john")
    jane, john = sign_in(server, "jane"), sign_in(server, "john")
    data = png((3, 1, 4))
    first = upload(jane, data).json()["id"]
    with server.db.tx(unscoped="test") as s:
        a = s.get(Receipt, first)
        assert retention.prune_files(server, s, [a], a.ownerId) > 0
    again = upload(jane, data).json()["id"]
    theirs = upload(john, data).json()["id"]
    with server.db.read(unscoped="test") as s:
        ids = {rid: s.get(Receipt, rid).fileId for rid in (first, again, theirs)}
    assert ids[again] != ids[first], "the pruned file is not brought back"
    assert ids[theirs] == ids[again], "one file for the same bytes"
    on_disk = {
        f for f in set(ids.values()) if retention.file_path(server.config.receipts_dir, f).exists()
    }
    assert on_disk == {ids[again]}


def test_how_long_a_categorys_receipts_are_kept_is_an_admins(server, admin_client):
    make_user(server, "jane")
    jane = sign_in(server, "jane")
    food = next(
        x for x in admin_client.get("/ui/api/categories").json()["items"] if x["name"] == "Food"
    )
    r = change(jane, "Cat", food, keepReceiptsYears=7)
    assert r.status_code == 403 and r.json()["errors"][0]["field"] == "keepReceiptsYears"
    r = change(admin_client, "Cat", food, keepReceiptsYears=0)
    assert r.json()["errors"][0]["code"] == "years-invalid"
    assert saved(change(admin_client, "Cat", food, keepReceiptsYears=7))["keepReceiptsYears"] == 7
    food = next(
        x for x in admin_client.get("/ui/api/categories").json()["items"] if x["name"] == "Food"
    )
    # Its name is anyone's to change (S7.2.3), and leaves how long its receipts are kept be.
    renamed = saved(change(jane, "Cat", food, name="Eating"))
    assert renamed["name"] == "Eating" and renamed["keepReceiptsYears"] == 7


def test_an_admins_household_wide_file_work_counts_every_users_files(server, admin_client):
    """Storage's counts, its pruning and *Remove orphans* are the household's: a file is an
    orphan only when no one's record names it, never when the admin can't read that record
    (schema.md §7.6)."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    acct = new_account(c)
    t = add(c, acct["id"], "-42.18", "2026-10-02", payee="Kroger")
    rid = receipt_on(c, t["id"], png((10, 20, 30)))
    st = admin_client.get("/ui/api/settings/storage").json()
    assert st["orphans"]["files"] == 0 and st["receiptsBytes"] > 0
    admin_client.post("/ui/api/session/reauth", json={"password": "a long admin passphrase"})
    r = admin_client.post("/ui/api/settings/storage/orphans/remove")
    assert r.status_code == 200 and r.json()["files"] == 0, r.text
    assert c.get(f"/ui/api/receipts/{rid}/file").status_code == 200


def test_an_admins_reading_queue_and_wallets_are_the_households(server, admin_client):
    """Settings › Receipts counts and reads again every user's receipts, and Settings ›
    Bitcoin counts every wallet, not only what the admin reads (schema.md §7.6)."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    acct = new_account(c)
    t = add(c, acct["id"], "-42.18", "2026-10-02", payee="Kroger")
    assert save_settings(admin_client, {"readReceipts": False}).status_code == 200
    rid = receipt_on(c, t["id"], png((40, 50, 60)))
    assert c.get(f"/ui/api/receipts/{rid}").json()["readStatus"] == "off"
    new_account(c, name="Cold storage", type="crypto-wallet")
    assert admin_client.get("/ui/api/settings/bitcoin").json()["wallets"] == 1
    assert save_settings(admin_client, {"readReceipts": True}).status_code == 200
    admin_client.post("/ui/api/settings/receipts/reread")
    assert c.get(f"/ui/api/receipts/{rid}").json()["readStatus"] != "off", "hers too"
