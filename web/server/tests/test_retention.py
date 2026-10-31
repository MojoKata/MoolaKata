"""File retention and pruning (requirements S14.10): when each file expires, from when its
records ended and their periods; what Settings › Storage shows; and pruning after a verified
backup, which keeps every record."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import attach, change, edit, make, save_settings, saved
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
    make_user(server, "alice")
    c = sign_in(server, "alice")
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
    make_user(server, "alice")
    c = sign_in(server, "alice")
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


def test_pruning_needs_the_password_again_and_the_count_and_keeps_the_record(
    server, frozen, admin_client
):
    from moolakata.store.entities.users import Session

    make_user(server, "alice")
    c = sign_in(server, "alice")
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
    body = {"categories": ["Groceries"], "count": 1}
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
    assert any("pruned 1 expired files" in a["text"] for a in acts)
    # The same file uploaded again is a new receipt with its file.
    again = upload(c, png((50, 60, 70))).json()
    assert again["id"] != rid
    assert c.get(f"/ui/api/receipts/{again['id']}/file").status_code == 200


def test_a_statement_expires_after_its_period_and_the_storage_setting(server, frozen, admin_client):
    from moolakata import receipts
    from moolakata.store.entities.receipts import Receipt

    alice = make_user(server, "alice")
    c = sign_in(server, "alice")
    acct = new_account(c)
    rid = upload(c, png((90, 91, 92))).json()["id"]
    with server.db.tx(unscoped="test") as s:
        r = s.get(Receipt, rid)
        r.date = dt.date(2027, 9, 30)
        receipts.attach_account(s, alice.id, r, acct["id"])
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

    make_user(server, "alice")
    c = sign_in(server, "alice")
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


def test_how_long_a_categorys_receipts_are_kept_is_an_admins(server, admin_client):
    make_user(server, "alice")
    alice = sign_in(server, "alice")
    food = next(
        x for x in admin_client.get("/ui/api/categories").json()["items"] if x["name"] == "Food"
    )
    r = change(alice, "Cat", food, keepReceiptsYears=7)
    assert r.status_code == 403 and r.json()["errors"][0]["field"] == "keepReceiptsYears"
    r = change(admin_client, "Cat", food, keepReceiptsYears=0)
    assert r.json()["errors"][0]["code"] == "years-invalid"
    assert saved(change(admin_client, "Cat", food, keepReceiptsYears=7))["keepReceiptsYears"] == 7
    food = next(
        x for x in admin_client.get("/ui/api/categories").json()["items"] if x["name"] == "Food"
    )
    r = change(admin_client, "Cat", food, name="Eating")
    assert r.json()["errors"][0]["code"] == "category-fixed"


def test_an_admins_household_wide_file_work_counts_every_users_files(server, admin_client):
    """Storage's counts, its pruning and *Remove orphans* are the household's: a file is an
    orphan only when no one's record names it, never when the admin can't read that record
    (schema.md §7.6)."""
    make_user(server, "alice")
    c = sign_in(server, "alice")
    acct = new_account(c)
    t = add(c, acct["id"], "-42.18", "2026-10-02", payee="Kroger")
    rid = receipt_on(c, t["id"], png((10, 20, 30)))
    st = admin_client.get("/ui/api/settings/storage").json()
    assert st["orphans"]["files"] == 0 and st["receiptsBytes"] > 0
    admin_client.post("/ui/api/session/reauth", json={"password": "a long admin passphrase"})
    r = admin_client.post("/ui/api/settings/storage/orphans/remove")
    assert r.status_code == 200 and r.json()["files"] == 0, r.text
    assert c.get(f"/ui/api/receipts/{rid}/file").status_code == 200
