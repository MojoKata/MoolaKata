"""Linked copies (requirements S11.9.1–S11.9.4, S11.9.8): a copy apart under its own 12-word
access key, unlocked by the people its items name, locked when unused, and reset."""

import json
import sqlite3

import pytest
from conftest import make_user, sign_in
from test_accounts import wait_job

from moolakata import clock, ids
from moolakata.links import copy as lcopy
from moolakata.store.entities.links import Link, LinkedItem


@pytest.fixture
def setup(server, admin_client):
    make_user(server, "jane")
    make_user(server, "john")
    jane, john = sign_in(server, "jane"), sign_in(server, "john")
    jane_id = jane.get("/ui/api/session").json()["user"]["id"]
    with server.db.tx(unscoped="test") as s:
        link = Link(
            id=ids.new_id("Link"),
            state="active",
            role="joiner",
            peerName="doe-parents",
            householdName="Jeremy & Candace",
            address="https://parents.test",
            peerKey="k" * 43,
        )
        s.add(link)
        s.flush()
        s.add(
            LinkedItem(
                id=ids.new_id("LItem"),
                linkId=link.id,
                remoteId="Acct_x",
                kind="account",
                ownerName="Candace Doe",
                sharedAt=clock.now(),
                viewers=json.dumps([jane_id]),
                createdAt=clock.now(),
            )
        )
        link_id = link.id
    return link_id, admin_client, jane, john


def test_an_admin_makes_the_words_and_a_named_person_unlocks_with_them(server, setup):
    link_id, admin, jane, john = setup
    assert jane.get("/ui/api/linked").json()["items"][0]["items"] == 1
    assert john.get("/ui/api/linked").json()["items"] == [], "john is named by nothing"
    st = jane.get(f"/ui/api/linked/{link_id}").json()
    assert st["hasKey"] is False and st["household"]["locked"]
    r = admin.post(f"/ui/api/settings/links/{link_id}/copy-key")
    assert r.status_code == 200, r.text
    words = r.json()["words"]
    assert len(words) == 12
    again = admin.post(f"/ui/api/settings/links/{link_id}/copy-key")
    assert again.status_code == 409
    path = lcopy.folder(server.config.data_dir, link_id) / "shared.db"
    assert path.exists() and not path.read_bytes().startswith(b"SQLite format 3")
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(path).execute("select * from sqlite_master").fetchall()
    with server.db.read(unscoped="test") as s:
        row = s.get(Link, link_id)
        assert row.copyPublicKey and " ".join(words) not in str(vars(row))
    assert jane.get(f"/ui/api/linked/{link_id}").json()["household"]["locked"]
    r = jane.post(f"/ui/api/linked/{link_id}/unlock", json={"words": " ".join(words)})
    assert r.status_code == 200, r.text
    st = r.json()
    assert not st["household"]["locked"] and st["unlockedBy"] and st["locksInSeconds"] > 3500
    # Open already, it still takes only its own words (S11.9.4).
    other = " ".join(lcopy.phrase.to_words(bytes(16)))
    r = jane.post(f"/ui/api/linked/{link_id}/unlock", json={"words": other})
    assert r.status_code == 422 and r.json()["code"] == "words-wrong"
    assert (
        john.post(f"/ui/api/linked/{link_id}/unlock", json={"words": " ".join(words)}).status_code
        == 404
    )
    r = jane.post(f"/ui/api/linked/{link_id}/lock")
    assert r.json()["household"]["locked"]
    texts = [e["text"] for e in admin.get("/ui/api/activity").json()["items"]]
    assert "Ada Admin created the access key of the linked copy from doe-parents" in texts
    assert "Jane unlocked the linked copy from doe-parents" in texts
    assert "Jane locked the linked copy from doe-parents (Lock now)" in texts


def test_a_restart_records_the_release_of_each_copy_with_a_key(server, setup):
    # S11.8: a release at a restart is recorded, naming the link, for each copy that has an
    # access key; a copy with none has nothing to release.
    from moolakata.links import copies

    link_id, admin, _, _ = setup
    with server.db.tx(unscoped="test") as s:
        copies.record_restart(s)
    texts = [e["text"] for e in admin.get("/ui/api/activity").json()["items"]]
    assert not any("(restart)" in t for t in texts)
    admin.post(f"/ui/api/settings/links/{link_id}/copy-key")
    with server.db.tx(unscoped="test") as s:
        copies.record_restart(s)
    items = admin.get("/ui/api/activity").json()["items"]
    [entry] = [e for e in items if "(restart)" in e["text"]]
    assert entry["text"] == "MoolaKata locked the linked copy from doe-parents (restart)"
    assert (entry["subjectKind"], entry["subjectId"]) == ("link", link_id)


def test_wrong_words_are_limited(server, setup):
    link_id, admin, jane, _ = setup
    words = admin.post(f"/ui/api/settings/links/{link_id}/copy-key").json()["words"]
    other = lcopy.phrase.to_words(bytes(16))
    for _ in range(4):
        r = jane.post(f"/ui/api/linked/{link_id}/unlock", json={"words": " ".join(other)})
        assert r.status_code == 422 and r.json()["code"] == "words-wrong"
    assert (
        jane.post(f"/ui/api/linked/{link_id}/unlock", json={"words": "not words"}).status_code
        == 422
    )
    r = jane.post(f"/ui/api/linked/{link_id}/unlock", json={"words": " ".join(words)})
    assert r.status_code == 429 and r.json()["code"] == "too-many-wrong"
    assert int(r.headers["retry-after"]) > 800


def test_an_unused_copy_locks_and_reset_starts_again(server, setup):
    link_id, admin, jane, _ = setup
    words = admin.post(f"/ui/api/settings/links/{link_id}/copy-key").json()["words"]
    now = [1000.0]
    server.copies.clock = lambda: now[0]
    jane.post(f"/ui/api/linked/{link_id}/unlock", json={"words": " ".join(words)})
    from moolakata.links import copies

    now[0] += 59 * 60
    assert copies.sweep(server) == []
    jane.get(f"/ui/api/linked/{link_id}")  # a look at the state isn't a use
    now[0] += 2 * 60
    assert copies.sweep(server) == [link_id]
    assert jane.get(f"/ui/api/linked/{link_id}").json()["household"]["locked"]
    job = admin.post(f"/ui/api/settings/links/{link_id}/reset-copy")
    assert job.status_code == 202 and job.headers["Location"] == f"/ui/api/jobs/{job.json()['id']}"
    assert wait_job(admin, job.json())["state"] == "done", "a reset copy is a job (S13.8.7)"
    out = admin.get("/ui/api/settings/links").json()["links"][0]
    assert out["linkedCopy"]["keyMadeAt"] is None
    assert not lcopy.folder(server.config.data_dir, link_id).exists()
    r = jane.post(f"/ui/api/linked/{link_id}/unlock", json={"words": " ".join(words)})
    assert r.status_code == 422 and r.json()["code"] == "no-key"


def test_files_no_row_names_are_swept_once_old_enough(server, setup):
    # A crash's leftovers go; a file still arriving, or delivered for a change to come,
    # stays (S11.9.6.6).
    import os
    import time

    from moolakata.links import copies
    from moolakata.links.routes import DELIVERED

    link_id, admin, jane, _ = setup
    words = admin.post(f"/ui/api/settings/links/{link_id}/copy-key").json()["words"]
    jane.post(f"/ui/api/linked/{link_id}/unlock", json={"words": " ".join(words)})
    d = lcopy.folder(server.config.data_dir, link_id) / "receipts"
    old = time.time() - 3600
    for name in ("left.mkr", "half.mkr.tmp", "waiting.mkr", "new.mkr"):
        (d / name).write_bytes(b"x")
        if name != "new.mkr":
            os.utime(d / name, (old, old))
    DELIVERED.put(link_id, "Rcpt_1", "waiting.mkr")
    try:
        assert copies.orphans(server, link_id) == 2
    finally:
        DELIVERED.take(link_id)
    assert sorted(p.name for p in d.iterdir()) == ["new.mkr", "waiting.mkr"]


def test_who_viewed_linked_data_is_recorded_once_an_hour(server, setup):
    # The receiving side records who viewed linked data (S11.8).
    from moolakata.ui import linked

    link_id, admin, jane, _ = setup
    words = admin.post(f"/ui/api/settings/links/{link_id}/copy-key").json()["words"]
    jane.post(f"/ui/api/linked/{link_id}/unlock", json={"words": " ".join(words)})
    linked._viewed.clear()
    for _ in range(3):
        assert jane.get(f"/ui/api/linked/{link_id}/items").status_code == 200
    feed = admin.get("/ui/api/activity").json()["items"]
    seen = [x["text"] for x in feed if "viewed what" in x["text"]]
    assert seen == ["Jane viewed what doe-parents shares"], seen


def test_a_copys_key_lock_and_unlock_are_refused_for_a_link_or_person_it_isnt_for(server, setup):
    # S11.9.2.1, S11.9.3.2: each refusal at its code and in its words.
    from moolakata.links import copies

    link_id, _admin, jane, john = setup
    john_id = john.get("/ui/api/session").json()["user"]["id"]
    jane_id = jane.get("/ui/api/session").json()["user"]["id"]

    def refused(fn, *args) -> tuple[str, str]:
        with pytest.raises(lcopy.CopyError) as e:
            fn(server, *args)
        return e.value.code, e.value.message

    assert refused(copies.make_key, "Link_none", jane_id) == ("not-found", "No such link.")
    with server.db.tx(unscoped="test") as s:
        s.get(Link, link_id).state = "pending"
    assert refused(copies.make_key, link_id, jane_id) == (
        "link-not-active",
        "Only an active link's copy has an access key.",
    )
    not_named = ("not-named", "Nothing from this household is shared with you.")
    assert refused(copies.unlock, link_id, john_id, "words") == not_named
    assert refused(copies.lock, link_id, john_id, False) == not_named
    copies.lock(server, link_id, john_id, True)  # an admin locks whomever it names
    with server.db.read(unscoped="test") as s:
        assert copies.named(s, link_id, jane_id) and not copies.named(s, link_id, john_id)
    assert copies.orphans(server, link_id) == 0, "a locked copy's files aren't swept"


def test_a_sweep_that_fails_for_one_copy_still_locks_the_unused_ones(server, setup, monkeypatch):
    from moolakata.links import copies

    link_id, admin, jane, _ = setup
    words = admin.post(f"/ui/api/settings/links/{link_id}/copy-key").json()["words"]
    now = [1000.0]
    server.copies.clock = lambda: now[0]
    assert jane.post(f"/ui/api/linked/{link_id}/unlock", json={"words": " ".join(words)}).is_success
    now[0] += 2 * 3600

    def broken(srv, link_id):
        raise OSError("the disk")

    monkeypatch.setattr(copies, "orphans", broken)
    assert copies.sweep(server) == [link_id]


def test_a_copys_unlocks_are_limited_to_twenty_an_hour_and_an_open_one_is_shared(tmp_path):
    # S11.9.4: 20 tries an hour on one copy, from anyone; the words still checked when it is
    # open already, and then the one open copy is everyone's.
    now = [1000.0]
    c = lcopy.Copies(clock=lambda: now[0])
    at = clock.now()
    public, words, _ = c.create(tmp_path, "Link_x", "u0", at)
    wrong = " ".join(lcopy.phrase.to_words(bytes(16)))
    for n in range(lcopy.PER_HOUR):
        with pytest.raises(lcopy.CopyError) as e:
            c.unlock(tmp_path, "Link_x", public, wrong, f"u{n}", at)
        assert e.value.code == "words-wrong"
    with pytest.raises(lcopy.CopyError) as e:
        c.unlock(tmp_path, "Link_x", public, " ".join(words), "u0", at)
    assert (e.value.code, e.value.message) == (
        "too-many-tries",
        "This copy has had 20 tries in the last hour: try again later.",
    )
    now[0] += 3600
    first = c.unlock(tmp_path, "Link_x", public, " ".join(words), "u0", at)
    now[0] += 60
    again = c.unlock(tmp_path, "Link_x", public, " ".join(words), "u1", at)
    assert again is first and again.used == now[0] and again.by == "u0"
    with pytest.raises(lcopy.CopyError) as e:
        c.unlock(tmp_path, "Link_x", public, wrong, "u2", at)
    assert e.value.code == "words-wrong", "checked even while it is open"
    c.release("Link_x")


def test_a_households_colour_is_one_of_the_palette_one_per_person_and_stays_with_it(server, setup):
    # S12.10.3.2: each refusal at its field, in its words.
    from edits import change, create, saved

    from moolakata.store.entities.links import LinkColour

    link_id, _admin, jane, john = setup

    def refusal(r) -> tuple[int, str, str, str]:
        (e,) = r.json()["errors"]
        return r.status_code, e["code"], e["field"], e["message"]

    r = create(jane, "LkCol", linkId=link_id, colour="mauve")
    assert refusal(r) == (422, "colour-invalid", "colour", "One of the palette's colours.")
    assert saved(create(jane, "LkCol", linkId=link_id, colour="amber"))
    r = create(jane, "LkCol", linkId=link_id, colour="rose")
    assert refusal(r) == (409, "colour-chosen", "linkId", "A colour is chosen: change it.")
    with server.db.read(unscoped="test") as s:
        row = s.query(LinkColour).one()
        record = {"id": row.id, "version": row.version}
    r = change(jane, "LkCol", record, linkId=ids.new_id("Link"), colour="rose")
    assert refusal(r) == (422, "colour-fixed", "linkId", "It stays with its household.")
    r = change(john, "LkCol", record, linkId=link_id, colour="rose")
    assert r.status_code == 404 and r.json()["errors"][0]["code"] == "not-found", "not theirs"
    assert saved(change(jane, "LkCol", record, linkId=link_id, colour="rose"))
    homes = jane.get("/ui/api/linked").json()["items"]
    assert homes[0]["colour"] == "rose"


def _receipt_in_copy(server, link_id, words, jane, data: bytes, *, viewers=None, sha=None):
    """A receipt that crossed, sealed by its source to the copy's key and named by an item of
    the copy (S11.9.6): its id, its sealed file and its item's id."""
    import hashlib

    from sqlalchemy import insert

    from moolakata.links import copydb, keys, sealed

    jane_id = jane.get("/ui/api/session").json()["user"]["id"]
    assert jane.post(f"/ui/api/linked/{link_id}/unlock", json={"words": " ".join(words)}).is_success
    with server.db.tx(unscoped="test") as s:
        row = s.get(Link, link_id)
        public = keys.unb64(row.copyPublicKey)
        way = keys.direction(
            keys.fingerprint(keys.unb64(row.peerKey)),
            keys.fingerprint(keys.public_of(s, server.keys.secrets)),
        )
    fid, item = ids.new_id("Rcpt"), ids.new_id("Acct")
    name = f"{fid}.mkr"
    path = lcopy.folder(server.config.data_dir, link_id) / "receipts" / name
    sealed.write(path, sealed.seal(public, sealed.RECEIPT, way, fid, [data]))
    from moolakata.receipts import sniff

    o = server.copies.get(link_id)
    with o.engine.begin() as conn:
        conn.execute(
            insert(copydb.Item).values(
                id=item,
                kind="account",
                name="Checking",
                ownerName="Candace Doe",
                viewers=json.dumps([jane_id] if viewers is None else viewers),
                version=1,
                asOf="2026-11-01",
            )
        )
        conn.execute(
            insert(copydb.File).values(
                id=fid,
                itemId=item,
                fileName=name,
                contentType=sniff(data[:16]) or "application/octet-stream",
                length=len(data),
                sha256=sha or hashlib.sha256(data).hexdigest(),
                meta="{}",
            )
        )
    return fid, path, item


def test_a_linked_receipt_is_served_whole_only_to_its_people_and_only_as_its_source_sent_it(
    server, setup
):
    # S11.9.6.4, S11.9.6.5: a receipt of more than one sealed piece streams whole; one of an
    # item not shared with the caller, one whose file can't be opened, and one that isn't what
    # its source sent are refused.
    from test_receipts import png

    from moolakata.links import sealed

    link_id, admin, jane, _ = setup
    words = admin.post(f"/ui/api/settings/links/{link_id}/copy-key").json()["words"]
    big = png() + bytes(3 * sealed.CHUNK)  # a PNG's bytes run past one sealed piece
    fid, _, item = _receipt_in_copy(server, link_id, words, jane, big)
    got = jane.get(f"/ui/api/linked/{link_id}/files/{fid}")
    assert got.status_code == 200 and got.content == big
    other, _, _ = _receipt_in_copy(server, link_id, words, jane, png(), viewers=[])
    r = jane.get(f"/ui/api/linked/{link_id}/files/{other}")
    assert (r.status_code, r.json()["code"], r.json()["detail"]) == (
        404,
        "not-shared",
        "That receipt isn't shared with you.",
    )
    listed = [x["id"] for x in jane.get(f"/ui/api/linked/{link_id}/items").json()["items"]]
    assert listed == [item], "an item of the copy that names someone else isn't listed"
    broken, path, _ = _receipt_in_copy(server, link_id, words, jane, png())
    path.write_bytes(b"not sealed")
    r = jane.get(f"/ui/api/linked/{link_id}/files/{broken}")
    assert (r.status_code, r.json()["code"], r.json()["detail"]) == (
        500,
        "receipt-unreadable",
        "The receipt's file can't be opened.",
    )
    changed, _, _ = _receipt_in_copy(server, link_id, words, jane, big, sha="0" * 64)
    with pytest.raises(sealed.SealError, match="not the one its source sent"):
        jane.get(f"/ui/api/linked/{link_id}/files/{changed}")


def test_a_linked_photo_is_shown_as_a_jpeg_or_refused_when_it_cant_be(server, setup, monkeypatch):
    # S9.8.4.2: a HEIC photo is decoded, as a local one is; one that can't be is refused.
    from moolakata import parsing

    link_id, admin, jane, _ = setup
    words = admin.post(f"/ui/api/settings/links/{link_id}/copy-key").json()["words"]
    heic = b"\x00\x00\x00\x18ftypheic\x00\x00" + b"h" * 100
    fid, _, _ = _receipt_in_copy(server, link_id, words, jane, heic)
    seen = []

    def as_jpeg(data, user):
        seen.append((data, user))
        return b"\xff\xd8jpeg"

    monkeypatch.setattr(parsing, "as_jpeg", as_jpeg)
    got = jane.get(f"/ui/api/linked/{link_id}/files/{fid}")
    jane_id = jane.get("/ui/api/session").json()["user"]["id"]
    assert got.status_code == 200 and got.headers["content-type"] == "image/jpeg"
    assert got.content == b"\xff\xd8jpeg" and seen == [(heic, f"{link_id}/{jane_id}")]

    def unreadable(data, user):
        raise parsing.ReadError("not a photo")

    monkeypatch.setattr(parsing, "as_jpeg", unreadable)
    r = jane.get(f"/ui/api/linked/{link_id}/files/{fid}")
    assert (r.status_code, r.json()["code"], r.json()["detail"]) == (
        415,
        "receipt-type",
        "That photo can't be shown.",
    )
