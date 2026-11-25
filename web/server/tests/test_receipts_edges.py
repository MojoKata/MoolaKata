"""Receipts' edges (requirements S9): what the module and the routes refuse, at their field or
status, code and words, and the corners the main tests pass by."""

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
