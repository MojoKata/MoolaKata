"""Receipts (requirements S9.1–S9.7)."""

import io

import pytest
from conftest import make_user, sign_in
from edits import drop, edit, saved
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
def alice(server):
    make_user(server, "alice")
    return sign_in(server, "alice")


def test_types_come_from_the_content(alice):
    r = upload(alice, b"MZ\x90\x00 not a receipt", name="receipt.pdf")
    assert r.status_code == 415 and r.json()["errors"][0]["field"] == "file"
    for data, media in (
        (png(), "image/png"),
        (jpeg_turned(), "image/jpeg"),
        (pdf(), "application/pdf"),
    ):
        r = upload(alice, data, name="anything.bin")
        assert r.status_code == 201, r.text
        assert r.json()["mediaType"] == media and r.json()["hasThumbnail"]
    assert receipts.sniff(b"\x00\x00\x00\x18ftypheic\x00\x00") == "image/heic"


def test_stored_encrypted_once_and_served_back(server, alice):
    data = png()
    first = upload(alice, data).json()
    again = upload(alice, data, name="copy.png")
    assert again.status_code == 200 and again.json()["id"] == first["id"]
    files = list(server.config.receipts_dir.glob("*.mkr"))
    assert len(files) == 1
    raw = files[0].read_bytes()
    assert raw.startswith(b"MKR1") and data not in raw
    r = alice.get(f"/ui/api/receipts/{first['id']}/file")
    assert r.status_code == 200 and r.content == data
    assert r.headers["content-type"] == "image/png"
    assert r.headers["content-security-policy"] == "sandbox"
    assert r.headers["content-disposition"].startswith("inline")
    assert r.headers["x-content-type-options"] == "nosniff"
    # Someone else's upload of the same file is their own receipt, over the same file.
    make_user(server, "bob")
    bob = sign_in(server, "bob")
    theirs = upload(bob, data).json()
    assert theirs["id"] != first["id"]
    assert len(list(server.config.receipts_dir.glob("*.mkr"))) == 1


def test_a_thumbnail_follows_the_photos_orientation(alice):
    rid = upload(alice, jpeg_turned()).json()["id"]
    thumb = alice.get(f"/ui/api/receipts/{rid}/thumbnail")
    assert thumb.headers["content-type"] == "image/webp"
    w, h = Image.open(io.BytesIO(thumb.content)).size
    assert h > w, "turned upright"


def test_attach_suggest_and_share_through_the_transaction(server, alice):
    acct = new_account(alice)
    t = add(alice, acct["id"], "-42.18", "2026-10-02", payee="Blue Bottle Coffee")
    add(alice, acct["id"], "-42.18", "2026-09-01", payee="Too early")
    tipped = add(alice, acct["id"], "-50.00", "2026-10-03", payee="Blue Bottle Coffee")
    rid = upload(alice, png()).json()["id"]
    r = edit(alice, "Rcpt", f"/ui/api/receipts/{rid}", date="2026-10-02", amount="42.18",
             payee="Blue Bottle")  # fmt: skip
    assert [m["transactionId"] for m in saved(r)["matches"]] == [t["id"], tipped["id"]]
    assert alice.get("/ui/api/receipts", params={"show": "inbox"}).json()["items"][0]["id"] == rid
    r = alice.post(f"/ui/api/receipts/{rid}/links", json={"transactionId": t["id"]})
    assert r.status_code == 200 and r.json()["links"][0]["transactionId"] == t["id"]
    assert alice.get("/ui/api/receipts", params={"show": "inbox"}).json()["items"] == []
    page = alice.get("/ui/api/transactions", params={"account": acct["id"]}).json()
    assert {x["id"]: x["receipts"] for x in page["items"]}[t["id"]] == 1
    # Bob sees it once the account is shared with him, and not before.
    make_user(server, "bob")
    bob = sign_in(server, "bob")
    assert bob.get(f"/ui/api/receipts/{rid}").status_code == 404
    users = {
        u["displayName"]: u["id"]
        for u in alice.get(f"/ui/api/shares/account/{acct['id']}").json()["users"]
    }
    r = alice.put(
        f"/ui/api/shares/account/{acct['id']}", json={"users": {users["Bob"]: "read"}, "groups": {}}
    )
    assert r.status_code == 200, r.text
    assert bob.get(f"/ui/api/receipts/{rid}").json()["level"] == "read"
    assert bob.get(f"/ui/api/receipts/{rid}/file").status_code == 200
    assert drop(bob, "Rcpt", f"/ui/api/receipts/{rid}").status_code == 403
    # A read share shows it and attaches it nowhere: not to Bob's own transaction (S9.6, P3).
    his = add(bob, new_account(bob, name="Bob's")["id"], "-42.18", "2026-10-02")
    r = bob.post(f"/ui/api/receipts/{rid}/links", json={"transactionId": his["id"]})
    assert r.status_code == 403 and r.json()["code"] == "receipt-read-only"
    # Deleted only by its owner, and only once nothing links to it.
    r = drop(alice, "Rcpt", f"/ui/api/receipts/{rid}")
    assert r.status_code == 409 and r.json()["errors"][0]["code"] == "receipt-linked"
    alice.delete(f"/ui/api/receipts/{rid}/links/{t['id']}")
    assert drop(alice, "Rcpt", f"/ui/api/receipts/{rid}").status_code == 200
    assert alice.get(f"/ui/api/receipts/{rid}").status_code == 404
    assert list(server.config.receipts_dir.glob("*.mkr")), "the file stays while a row names it"


def test_attaching_needs_write_on_the_account(server, alice):
    make_user(server, "bob")
    bob = sign_in(server, "bob")
    acct = new_account(alice)
    t = add(alice, acct["id"], "-5.00", "2026-10-02")
    rid = upload(bob, png()).json()["id"]
    r = bob.post(f"/ui/api/receipts/{rid}/links", json={"transactionId": t["id"]})
    assert r.status_code == 404


def test_size_limit_is_a_setting(server, alice, admin_client):
    assert admin_client.patch("/ui/api/settings", json={"receiptMaxMb": 1}).status_code == 200
    big = png() + b"\x00" * (1024 * 1024)
    r = upload(alice, big)
    assert r.status_code == 413


def test_reencrypt_carries_the_receipts_over(server, alice, keyed_config, master_key):
    data = png((1, 2, 3))
    rid = upload(alice, data).json()["id"]
    server.store = maintenance.reencrypt(keyed_config, server.store, master_key)
    assert alice.get(f"/ui/api/receipts/{rid}/file").content == data
