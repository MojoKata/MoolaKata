"""Receipts (requirements S9.1–S9.7)."""

import io

import pytest
from conftest import make_user, sign_in
from edits import attach, detach, drop, edit, save_settings, saved, share
from PIL import Image
from test_accounts import add, new_account

from moolakata import receipts
from moolakata.store import maintenance


def png(color=(200, 30, 30), size=(60, 90)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "PNG")
    return out.getvalue()


def jpeg_turned() -> bytes:
    """A photo taken on its side: 90 wide, 60 high, with EXIF saying turn it."""
    img = Image.new("RGB", (90, 60), (10, 120, 200))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° clockwise to show
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif)
    return out.getvalue()


def pdf() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (200, 300), (255, 255, 255)).save(out, "PDF")
    return out.getvalue()


def upload(c, data: bytes, name="receipt.png"):
    return c.post("/ui/api/receipts", files={"file": (name, data, "application/octet-stream")})


@pytest.fixture
def jane(server):
    make_user(server, "jane")
    return sign_in(server, "jane")


def test_types_come_from_the_content(jane):
    r = upload(jane, b"MZ\x90\x00 not a receipt", name="receipt.pdf")
    assert r.status_code == 415 and r.json()["errors"][0]["field"] == "file"
    for data, media in (
        (png(), "image/png"),
        (jpeg_turned(), "image/jpeg"),
        (pdf(), "application/pdf"),
    ):
        r = upload(jane, data, name="anything.bin")
        assert r.status_code == 201, r.text
        assert r.json()["mediaType"] == media and r.json()["hasThumbnail"]
    assert receipts.sniff(b"\x00\x00\x00\x18ftypheic\x00\x00") == "image/heic"


def test_stored_encrypted_once_and_served_back(server, jane):
    data = png()
    first = upload(jane, data).json()
    again = upload(jane, data, name="copy.png")
    assert again.status_code == 200 and again.json()["id"] == first["id"]
    files = list(server.config.receipts_dir.glob("*.mkr"))
    assert len(files) == 1
    raw = files[0].read_bytes()
    assert raw.startswith(b"MKR1") and data not in raw
    r = jane.get(f"/ui/api/receipts/{first['id']}/file")
    assert r.status_code == 200 and r.content == data
    assert r.headers["content-type"] == "image/png"
    assert r.headers["content-security-policy"] == "sandbox"
    assert r.headers["content-disposition"].startswith("inline")
    assert r.headers["x-content-type-options"] == "nosniff"
    # Someone else's upload of the same file is their own receipt, over the same file.
    make_user(server, "john")
    john = sign_in(server, "john")
    theirs = upload(john, data).json()
    assert theirs["id"] != first["id"]
    assert len(list(server.config.receipts_dir.glob("*.mkr"))) == 1


def test_a_thumbnail_follows_the_photos_orientation(jane):
    rid = upload(jane, jpeg_turned()).json()["id"]
    thumb = jane.get(f"/ui/api/receipts/{rid}/thumbnail")
    assert thumb.headers["content-type"] == "image/webp"
    w, h = Image.open(io.BytesIO(thumb.content)).size
    assert h > w, "turned upright"


def test_attach_suggest_and_share_through_the_transaction(server, jane):
    acct = new_account(jane)
    t = add(jane, acct["id"], "-42.18", "2026-10-02", payee="Blue Bottle Coffee")
    add(jane, acct["id"], "-42.18", "2026-09-01", payee="Too early")
    tipped = add(jane, acct["id"], "-50.00", "2026-10-03", payee="Blue Bottle Coffee")
    rid = upload(jane, png()).json()["id"]
    r = edit(jane, "Rcpt", f"/ui/api/receipts/{rid}", date="2026-10-02", amount="42.18",
             payee="Blue Bottle")  # fmt: skip
    assert [m["transactionId"] for m in saved(r)["matches"]] == [t["id"], tipped["id"]]
    assert jane.get("/ui/api/receipts", params={"show": "inbox"}).json()["items"][0]["id"] == rid
    assert saved(attach(jane, rid, t["id"]))["itemId"] == t["id"]
    assert jane.get(f"/ui/api/receipts/{rid}").json()["links"][0]["transactionId"] == t["id"]
    assert jane.get("/ui/api/receipts", params={"show": "inbox"}).json()["items"] == []
    page = jane.get("/ui/api/transactions", params={"account": acct["id"]}).json()
    assert {x["id"]: x["receipts"] for x in page["items"]}[t["id"]] == 1
    # John sees it once the account is shared with him, and not before.
    make_user(server, "john")
    john = sign_in(server, "john")
    assert john.get(f"/ui/api/receipts/{rid}").status_code == 404
    users = {
        u["displayName"]: u["id"]
        for u in jane.get(f"/ui/api/shares/account/{acct['id']}").json()["users"]
    }
    r = share(jane, "account", acct["id"], users={users["John"]: "read"}, groups={})
    assert r.status_code == 200, r.text
    held = john.get(f"/ui/api/receipts/{rid}").json()["access"]
    assert not held["writable"] and not held["mine"]
    assert john.get(f"/ui/api/receipts/{rid}/file").status_code == 200
    assert drop(john, "Rcpt", f"/ui/api/receipts/{rid}").status_code == 403
    # A read share shows it and attaches it nowhere: not to John's own transaction (S9.6, P3).
    his = add(john, new_account(john, name="John's")["id"], "-42.18", "2026-10-02")
    r = attach(john, rid, his["id"])
    assert r.status_code == 403 and r.json()["errors"][0]["code"] == "receipt-read-only"
    # Deleted only by its owner, and only once nothing links to it.
    r = drop(jane, "Rcpt", f"/ui/api/receipts/{rid}")
    assert r.status_code == 409 and r.json()["errors"][0]["code"] == "receipt-linked"
    assert detach(jane, rid, t["id"]).status_code == 200
    assert drop(jane, "Rcpt", f"/ui/api/receipts/{rid}").status_code == 200
    assert jane.get(f"/ui/api/receipts/{rid}").status_code == 404
    assert list(server.config.receipts_dir.glob("*.mkr")), "the file stays while a row names it"


def test_attaching_needs_write_on_the_account(server, jane):
    make_user(server, "john")
    john = sign_in(server, "john")
    acct = new_account(jane)
    t = add(jane, acct["id"], "-5.00", "2026-10-02")
    rid = upload(john, png()).json()["id"]
    r = attach(john, rid, t["id"])
    assert r.status_code == 404


def test_a_link_is_made_once_and_never_changed(server, jane):
    from edits import change, create

    acct = new_account(jane)
    t = add(jane, acct["id"], "-5.00", "2026-10-02")
    rid = upload(jane, png()).json()["id"]
    link = saved(attach(jane, rid, t["id"]))
    r = attach(jane, rid, t["id"])
    assert r.status_code == 409 and r.json()["errors"][0]["code"] == "already-attached"
    r = change(jane, "RcLnk", link, itemId=acct["id"])
    assert r.json()["errors"][0]["code"] == "link-unchanged"
    # An id of another table than its kind's is refused at the field.
    r = create(jane, "RcLnk", receiptId=rid, kind="transaction", itemId=acct["id"])
    assert r.json()["errors"][0]["field"] == "itemId"
    # Taken away, it can be made again.
    assert detach(jane, rid, t["id"]).status_code == 200
    assert saved(attach(jane, rid, t["id"]))["id"] != link["id"]


def test_a_read_share_neither_attaches_nor_detaches(server, jane):
    make_user(server, "john")
    john = sign_in(server, "john")
    acct = new_account(jane)
    t = add(jane, acct["id"], "-5.00", "2026-10-02")
    users = {
        u["displayName"]: u["id"]
        for u in jane.get(f"/ui/api/shares/account/{acct['id']}").json()["users"]
    }
    assert share(jane, "account", acct["id"], users={users["John"]: "read"}).status_code == 200
    mine = upload(john, png(color=(1, 2, 3))).json()["id"]
    r = attach(john, mine, t["id"])
    assert r.status_code == 403 and r.json()["errors"][0]["code"] == "read-only"
    rid = upload(jane, png()).json()["id"]
    saved(attach(jane, rid, t["id"]))
    [link] = john.get(f"/ui/api/receipts/{rid}").json()["links"]
    assert not link["access"]["deletable"]
    assert detach(john, rid, t["id"]).status_code == 403


def test_size_limit_is_a_setting(server, jane, admin_client):
    assert save_settings(admin_client, {"receiptMaxMb": 1}).status_code == 200
    big = png() + b"\x00" * (1024 * 1024)
    r = upload(jane, big)
    assert r.status_code == 413


def test_reencrypt_carries_the_receipts_over(server, jane, keyed_config, master_key):
    data = png((1, 2, 3))
    rid = upload(jane, data).json()["id"]
    server.store = maintenance.reencrypt(keyed_config, server.store, master_key)
    assert jane.get(f"/ui/api/receipts/{rid}/file").content == data


def test_a_reader_sees_only_the_links_they_read_and_how_many_more(server, jane):
    """CR3-47 (S9.3): John, reading the joint account, sees the receipt's joint link and that
    it is kept with one thing more, never what; the reason it is kept is named only from a
    link he reads. Jane, its owner, sees the same of a link John made to his own account, and
    the receipt stays out of her inbox."""
    from moolakata import ids
    from moolakata.store.entities.accounts import Category

    with server.db.tx(unscoped="test") as s:
        jewels = Category(id=ids.new_id("Cat"), name="Jewellery", kind="expense",
                          keepReceiptsYears=7)  # fmt: skip
        coffee = Category(id=ids.new_id("Cat"), name="Coffee", kind="expense",
                          keepReceiptsYears=2)  # fmt: skip
        s.add_all([jewels, coffee])
    joint, private = new_account(jane, name="Joint"), new_account(jane, name="Jane private")
    ours = add(jane, joint["id"], "-42.18", "2026-10-02", payee="Blue Bottle",
               categoryId=coffee.id)  # fmt: skip
    hers = add(jane, private["id"], "-42.18", "2026-10-02", payee="Secret Jeweller",
               categoryId=jewels.id)  # fmt: skip
    rid = upload(jane, png((1, 2, 3))).json()["id"]
    assert saved(attach(jane, rid, ours["id"]))
    assert saved(attach(jane, rid, hers["id"]))
    make_user(server, "john")
    john = sign_in(server, "john")
    users = {
        u["displayName"]: u["id"]
        for u in jane.get(f"/ui/api/shares/account/{joint['id']}").json()["users"]
    }
    assert share(jane, "account", joint["id"], users={users["John"]: "write"}).status_code == 200
    seen = john.get(f"/ui/api/receipts/{rid}").json()
    assert [x["payee"] for x in seen["links"]] == ["Blue Bottle"]
    assert seen["alsoKeptWith"] == 1 and "Secret Jeweller" not in str(seen)
    assert seen["keptWhy"] == "Kept for something not shared with you"
    mine = jane.get(f"/ui/api/receipts/{rid}").json()
    assert len(mine["links"]) == 2 and mine["alsoKeptWith"] == 0
    assert mine["keptWhy"] == "Jewellery keeps receipts 7 years"
    assert seen["keptUntil"] == mine["keptUntil"], "the file's own date, for whoever reads"
    # John, writing the joint account, keeps it with a transaction of his own as well.
    his = add(john, new_account(john, name="John's")["id"], "-42.18", "2026-10-02")
    assert saved(attach(john, rid, his["id"]))
    assert jane.get(f"/ui/api/receipts/{rid}").json()["alsoKeptWith"] == 1
    assert jane.get("/ui/api/receipts", params={"show": "inbox"}).json()["items"] == []


def test_a_slow_thumbnail_holds_no_one_elses_write(server, jane, monkeypatch):
    """CR3-48 (S9.5): an upload's thumbnail is drawn before its transaction, so another
    user's save goes through while the reader's worker is still drawing it."""
    import threading

    drawing, go = threading.Event(), threading.Event()

    class Slow:
        @staticmethod
        def thumbnail(data, media):
            drawing.set()
            assert go.wait(30)
            return None

    monkeypatch.setattr(receipts, "_parsing", lambda: Slow)
    make_user(server, "john")
    john = sign_in(server, "john")
    acct = new_account(john, name="John's")
    answers = []
    t = threading.Thread(target=lambda: answers.append(upload(jane, png((9, 9, 9)))))
    t.start()
    try:
        assert drawing.wait(30), "the upload reached its thumbnail"
        made = add(john, acct["id"], "-5.00", "2026-10-02", payee="Meanwhile")
        assert made["payee"] == "Meanwhile"
    finally:
        go.set()
        t.join(30)
    assert answers and answers[0].status_code == 201, answers
    assert answers[0].json()["hasThumbnail"] is False, "it keeps its icon"
