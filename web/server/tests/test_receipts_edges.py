"""Receipts' edges (requirements S9): what the module and the routes refuse, at their field or
status, code and words, and the corners the main tests pass by."""

from types import SimpleNamespace

import pytest
from conftest import make_user, sign_in
from edits import attach, change, edit, remove, saved, share
from PIL import Image
from test_accounts import add, new_account
from test_reader_worker import huge_png
from test_receipts import png, upload

from moolakata import receipts
from moolakata.errors import Problem
from moolakata.store.entities.receipts import Receipt, ReceiptLink


@pytest.fixture
def jane(server):
    make_user(server, "jane")
    return sign_in(server, "jane")


def john_reads(server, jane, account_id: str):
    """John, with Jane's account shared with him to read."""
    make_user(server, "john", sex="male")
    john = sign_in(server, "john")
    users = {
        u["displayName"]: u["id"]
        for u in jane.get(f"/ui/api/shares/account/{account_id}").json()["users"]
    }
    assert share(jane, "account", account_id, users={users["John"]: "read"}).status_code == 200
    return john


def refused(r, field, code, words, status):
    assert r.status_code == status, r.text
    e = r.json()["errors"][0]
    assert (e["field"], e["code"], e["message"]) == (field, code, words)


@pytest.mark.parametrize(
    ("head", "media"),
    [
        (b"%PDF-1.7\n", "application/pdf"),
        (b"\xff\xd8\xff\xe0", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"RIFF\x00\x00\x00\x00WAVEfmt ", None),
        (b"\x00\x00\x00\x18ftypheic", "image/heic"),
        (b"\x00\x00\x00\x18ftypmif1", "image/heic"),
        (b"\x00\x00\x00\x18ftypisom", None),
        (b"GIF89a", None),
        (b"", None),
    ],
)
def test_a_files_type_is_read_from_its_first_bytes(head, media):
    assert receipts.sniff(head) == media


def test_a_thumbnail_of_an_image_past_the_pixel_cap_is_refused_not_left_out():
    """S9.8.4.3: the refusal reaches the upload, which no broken picture does."""
    with pytest.warns(Image.DecompressionBombWarning), pytest.raises(Problem) as e:
        receipts.thumbnail(huge_png(10_000, 5_000), "image/png")
    assert (e.value.code, e.value.detail) == (
        "image-too-large",
        "The image is larger than 40 million pixels.",
    )


def test_a_file_whose_bytes_are_not_the_ones_uploaded_is_refused_as_it_is_read(server, jane):
    """S9.4: the plaintext's hash is checked as it streams."""
    from moolakata.keys.files import FileError

    rid = upload(jane, png((1, 2, 3))).json()["id"]
    with server.db.read(unscoped="test") as s:
        r = s.get(Receipt, rid)
        s.expunge(r)
    assert receipts.whole(server, r) == png((1, 2, 3))
    r.sha256 = "0" * 64
    with pytest.raises(FileError, match="the receipt's file is not the one uploaded"):
        receipts.whole(server, r)


def test_a_receipt_shared_to_read_is_kept_with_none_of_the_readers_things(server, jane):
    """S9.6: John reads Jane's receipt through her account, and keeps it with none of his own
    items, refused at the field."""
    from test_assets import item

    acct = new_account(jane)
    t = add(jane, acct["id"], "-42.18", "2026-10-02")
    rid = upload(jane, png((4, 5, 6))).json()["id"]
    saved(attach(jane, rid, t["id"]))
    john = john_reads(server, jane, acct["id"])
    coll = new_account(john, name="Collectables", type="collectables")
    watch = item(john, coll["id"], name="Watch")
    r = edit(john, "Item", f"/ui/api/items/{watch['id']}", receiptIds={"add": [rid], "remove": []})
    refused(
        r,
        "receiptIds",
        "receipt-read-only",
        "That receipt is shared with you to read: it can't be attached to anything else.",
        403,
    )


def test_a_document_taken_off_an_item_and_put_back_is_a_new_link(server, jane):
    """S1.10.1, S9.3: a link is a record of its own, never changed: put back, it is a new one,
    and the one taken away stays deleted."""
    from test_assets import item

    coll = new_account(jane, name="Collectables", type="collectables")
    watch = item(jane, coll["id"], name="Watch")
    rid = upload(jane, png((7, 8, 9))).json()["id"]
    path = f"/ui/api/items/{watch['id']}"
    for add_, remove_ in (([rid], []), ([], [rid]), ([rid], [])):
        saved(edit(jane, "Item", path, receiptIds={"add": add_, "remove": remove_}))
    with server.db.read(unscoped="test") as s:
        rows = s.query(ReceiptLink).filter_by(receiptId=rid).all()
        assert sorted((x.kind, x.deleted) for x in rows) == [("item", False), ("item", True)]


def test_a_gifts_receipt_taken_away_and_put_back_is_a_new_link(server, jane):
    """S9.6, S7.8.1: through the gift's own receipts, taken away and put back as a new link."""
    from test_gifts import gift, person

    g = gift(jane, people=[person(jane)["id"]], status="given", cost="40.00")
    rid = upload(jane, png((9, 9, 1))).json()["id"]
    for add_, remove_, linked in (([rid], [], 1), ([], [rid], 0), ([rid], [], 1)):
        g = saved(change(jane, "Gift", g, receiptIds={"add": add_, "remove": remove_}))
        assert len(jane.get(f"/ui/api/receipts/{rid}").json()["links"]) == linked
    with server.db.read(unscoped="test") as s:
        rows = s.query(ReceiptLink).filter_by(receiptId=rid).all()
        assert sorted((x.kind, x.deleted) for x in rows) == [("gift", False), ("gift", True)]


def test_a_link_to_what_the_reader_cant_see_is_not_found_to_them(server, jane):
    """S9.3: John reads the receipt through Jane's shared account; its link to her private
    account's transaction is hers to take away, and to him not there."""
    shared, private = new_account(jane), new_account(jane, name="Private")
    t = add(jane, shared["id"], "-42.18", "2026-10-02")
    hers = add(jane, private["id"], "-42.18", "2026-10-02")
    rid = upload(jane, png((2, 4, 6))).json()["id"]
    saved(attach(jane, rid, t["id"]))
    link = saved(attach(jane, rid, hers["id"]))
    john = john_reads(server, jane, shared["id"])
    refused(remove(john, "RcLnk", link), None, "not-found", "Not found", 404)


@pytest.mark.parametrize(
    ("a", "b", "alike"),
    [
        (None, "Blue Bottle", 0.0),
        ("Blue Bottle", "", 0.0),
        ("AB", "Blue Bottle", 0.0),
        ("Blue Bottle", "of a", 0.0),
        ("Blue Bottle Coffee", "BLUE BOTTLE", 1.0),
        ("Blue Bottle Coffee", "Bottle Shop", 1 / 2),
    ],
)
def test_how_alike_two_payees_are_counts_the_shorters_words(a, b, alike):
    """S9.8.2.6: words of three letters or more; a name with none is like nothing."""
    assert receipts._alike(a, b) == alike


# ---------- the routes (ui/receipts.py) ----------


def test_a_receipt_names_what_it_is_kept_with_leaving_out_what_was_deleted(server, jane):
    """S9.3: each link is named in the receipt's dialog, a donation by its organisation, its
    description or *a cause*; a link to a record deleted, or kept in an account deleted, or a
    tax document of a deleted book, is left out."""
    import datetime as dt
    from decimal import Decimal

    from test_assets import item

    from moolakata.ids import new_id
    from moolakata.store.entities.accounts import Account, Transaction
    from moolakata.store.entities.assets import Item
    from moolakata.store.entities.education import Gift
    from moolakata.store.entities.giving import Donation, Organisation
    from moolakata.store.entities.taxes import TaxBook, TaxDocument
    from moolakata.store.entities.users import User

    acct = new_account(jane)
    t = add(jane, acct["id"], "-42.18", "2026-10-02", payee="Corner Store")
    coll = new_account(jane, name="Collectables", type="collectables")
    watch = item(jane, coll["id"], name="Watch")
    ring = item(jane, coll["id"], name="Ring")
    statement = new_account(jane, name="Old checking")
    rid = upload(jane, png((3, 1, 4))).json()["id"]
    with server.db.tx(unscoped="test") as s:
        me = s.query(User).filter_by(username="jane").one().id
        red = Organisation(id=new_id("Orgzn"), ownerId=me, name="Red Cross")
        gift = Gift(id=new_id("Gift"), ownerId=me, description="Scarf")
        day, cash = dt.date(2026, 3, 1), Decimal("25")
        gifts = [
            Donation(id=new_id("Dnatn"), ownerId=me, date=day, kind="cash", amount=cash, **kw)
            for kw in ({"organisationId": red.id}, {"description": "Food bank"}, {})
        ]
        book = TaxBook(id=new_id("TaxBk"), ownerId=me, year=2026)
        doc = TaxDocument(id=new_id("TxDoc"), bookId=book.id, direction="received",
                          form="W-2", receiptId=rid)  # fmt: skip
        s.add_all([red, gift, book])
        s.flush()
        s.add_all([*gifts, doc])
        kinds = [("transaction", t["id"]), ("item", watch["id"]), ("item", ring["id"]),
                 ("account", statement["id"]), ("gift", gift.id)]  # fmt: skip
        kinds += [("donation", d.id) for d in gifts]
        for kind, item_id in kinds:
            s.add(ReceiptLink(id=new_id("RcLnk"), receiptId=rid, kind=kind, itemId=item_id))
    labels = [x["label"] for x in jane.get(f"/ui/api/receipts/{rid}").json()["links"]]
    assert sorted(labels) == sorted([
        "Corner Store",
        "Watch in Collectables",
        "Ring in Collectables",
        "The statement of Old checking",
        "The gift Scarf",
        "The donation to Red Cross",
        "The donation to Food bank",
        "The donation to a cause",
        "W-2 in the 2026 tax book",
    ])  # fmt: skip
    with server.db.tx(unscoped="test") as s:
        for row in (s.get(Transaction, t["id"]), s.get(Item, watch["id"]), s.get(Gift, gift.id),
                    s.get(Account, statement["id"]), s.get(TaxBook, book.id),
                    *(s.get(Donation, d.id) for d in gifts)):  # fmt: skip
            row.mark_deleted(None)
    labels = [x["label"] for x in jane.get(f"/ui/api/receipts/{rid}").json()["links"]]
    assert labels == ["Ring in Collectables"]
    with server.db.tx(unscoped="test") as s:
        s.get(Account, coll["id"]).mark_deleted(None)
    assert jane.get(f"/ui/api/receipts/{rid}").json()["links"] == []


def test_an_upload_and_a_read_again_are_queued_for_the_reader(server, jane, monkeypatch):
    """S9.8.6: an upload waiting to be read, and Read Again, go to the reading queue."""
    queued = []
    monkeypatch.setattr(server, "reader", SimpleNamespace(queue=queued.append))
    rid = upload(jane, png((2, 7, 1))).json()["id"]
    assert jane.post(f"/ui/api/receipts/{rid}/read").status_code == 200
    assert queued == [rid, rid]


def test_the_routes_refuse_at_their_field_or_status(server, jane, admin_client):
    """R3.11, S9.1, S9.8.6: an empty file, a receipt made but by upload, a payee or notes too
    long, Read Again with reading off, a link not there, a missing thumbnail, a transaction
    not there."""
    from edits import new_id, save_settings

    r = jane.post("/ui/api/receipts", files={"file": ("r.png", b"", "image/png")})
    refused(r, "file", "file-empty", "The file is empty.", 422)
    made = {"op": "create", "entity": "Rcpt", "id": new_id("Rcpt"), "fields": {}}
    refused(jane.post("/ui/api/save", json={"ops": [made]}), None, "receipt-uploaded",
            "A receipt is made by uploading its file.", 422)  # fmt: skip
    rid = upload(jane, png((8, 1, 8))).json()["id"]
    got = jane.get(f"/ui/api/receipts/{rid}").json()
    refused(change(jane, "Rcpt", got, payee="p" * 201), "payee", "payee-too-long",
            "At most 200 characters.", 422)  # fmt: skip
    refused(change(jane, "Rcpt", got, notes="n" * 2001), "notes", "notes-too-long",
            "At most 2,000 characters.", 422)  # fmt: skip
    assert change(jane, "Rcpt", got, payee="p" * 200, notes="n" * 2000).status_code == 200
    assert save_settings(admin_client, {"readReceipts": False}).status_code == 200
    r = jane.post(f"/ui/api/receipts/{rid}/read")
    assert (r.status_code, r.json()["code"], r.json()["detail"]) == (
        409, "reading-off", "Reading receipts is off in Settings › Receipts."
    )  # fmt: skip
    gone = {"id": "RcLnk_00000000000000000000000000", "version": 1}
    refused(remove(jane, "RcLnk", gone), None, "not-found", "Not found", 404)
    with server.db.tx(unscoped="test") as s:
        s.get(Receipt, rid).thumbnail = None
    r = jane.get(f"/ui/api/receipts/{rid}/thumbnail")
    assert (r.status_code, r.json()["code"]) == (404, "no-thumbnail")
    r = jane.get("/ui/api/transactions/Txn_00000000000000000000000000/receipts")
    assert (r.status_code, r.json()["code"]) == (404, "not-found")


def test_a_heic_photo_is_served_as_jpeg_drawn_in_the_worker(server, jane, monkeypatch):
    """S9.1, S9.8.4.2: decoded in the reader's worker, never in the server; one it can't
    decode is refused with the reason."""
    from moolakata import parsing

    heic = b"\x00\x00\x00\x18ftypheic\x00\x00" + b"h" * 100
    r = jane.post("/ui/api/receipts", files={"file": ("p.heic", heic, "image/heic")})
    rid = r.json()["id"]
    monkeypatch.setattr(parsing, "as_jpeg", lambda data, user: b"\xff\xd8jpeg")
    got = jane.get(f"/ui/api/receipts/{rid}/file")
    assert (got.status_code, got.headers["content-type"], got.content) == (
        200, "image/jpeg", b"\xff\xd8jpeg"
    )  # fmt: skip

    def broken(data, user):
        raise parsing.ReadError("not a photo")

    monkeypatch.setattr(parsing, "as_jpeg", broken)
    got = jane.get(f"/ui/api/receipts/{rid}/file")
    assert (got.status_code, got.json()["code"], got.json()["detail"]) == (
        415, "receipt-unshowable", "The photo can't be shown: not a photo"
    )  # fmt: skip


def test_a_file_lost_on_disk_is_refused_naming_no_path(server, jane):
    """S13.7.8: the reason, which may name a path on the host, goes to the log only."""
    rid = upload(jane, png((6, 2, 6))).json()["id"]
    with server.db.read(unscoped="test") as s:
        path = receipts.file_path(server.config.receipts_dir, s.get(Receipt, rid).fileId)
    path.unlink()
    r = jane.get(f"/ui/api/receipts/{rid}/file")
    assert (r.status_code, r.json()["code"], r.json()["detail"]) == (
        500, "receipt-unreadable", "The receipt's file can't be read."
    )  # fmt: skip
    assert str(server.config.receipts_dir) not in r.text


def test_a_transactions_receipts_are_listed_for_who_reads_it(server, jane):
    acct = new_account(jane)
    t = add(jane, acct["id"], "-42.18", "2026-10-02")
    rid = upload(jane, png((5, 3, 5))).json()["id"]
    saved(attach(jane, rid, t["id"]))
    got = jane.get(f"/ui/api/transactions/{t['id']}/receipts").json()["items"]
    assert [x["id"] for x in got] == [rid]
