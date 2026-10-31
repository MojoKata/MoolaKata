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
    make_user(server, "alice")
    make_user(server, "bob")
    alice, bob = sign_in(server, "alice"), sign_in(server, "bob")
    alice_id = alice.get("/ui/api/session").json()["user"]["id"]
    with server.db.tx() as s:
        link = Link(
            id=ids.new_id("Link"),
            state="active",
            role="joiner",
            peerName="griffin-parents",
            householdName="Margaret & Tom",
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
                ownerName="Margaret Griffin",
                sharedAt=clock.now(),
                viewers=json.dumps([alice_id]),
                createdAt=clock.now(),
            )
        )
        link_id = link.id
    return link_id, admin_client, alice, bob


def test_an_admin_makes_the_words_and_a_named_person_unlocks_with_them(server, setup):
    link_id, admin, alice, bob = setup
    assert alice.get("/ui/api/linked").json()["items"][0]["items"] == 1
    assert bob.get("/ui/api/linked").json()["items"] == [], "bob is named by nothing"
    st = alice.get(f"/ui/api/linked/{link_id}").json()
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
    with server.db.read() as s:
        row = s.get(Link, link_id)
        assert row.copyPublicKey and " ".join(words) not in str(vars(row))
    assert alice.get(f"/ui/api/linked/{link_id}").json()["household"]["locked"]
    r = alice.post(f"/ui/api/linked/{link_id}/unlock", json={"words": " ".join(words)})
    assert r.status_code == 200, r.text
    st = r.json()
    assert not st["household"]["locked"] and st["unlockedBy"] and st["locksInSeconds"] > 3500
    # Open already, it still takes only its own words (S11.9.4).
    other = " ".join(lcopy.phrase.to_words(bytes(16)))
    r = alice.post(f"/ui/api/linked/{link_id}/unlock", json={"words": other})
    assert r.status_code == 422 and r.json()["code"] == "words-wrong"
    assert (
        bob.post(f"/ui/api/linked/{link_id}/unlock", json={"words": " ".join(words)}).status_code
        == 404
    )
    r = alice.post(f"/ui/api/linked/{link_id}/lock")
    assert r.json()["household"]["locked"]
    texts = [e["text"] for e in admin.get("/ui/api/activity").json()["items"]]
    assert any("created a linked copy's access key" in t for t in texts)
    assert any("unlocked a linked copy" in t for t in texts)
    assert any("locked a linked copy (Lock now)" in t for t in texts)


def test_wrong_words_are_limited(server, setup):
    link_id, admin, alice, _ = setup
    words = admin.post(f"/ui/api/settings/links/{link_id}/copy-key").json()["words"]
    other = lcopy.phrase.to_words(bytes(16))
    for _ in range(4):
        r = alice.post(f"/ui/api/linked/{link_id}/unlock", json={"words": " ".join(other)})
        assert r.status_code == 422 and r.json()["code"] == "words-wrong"
    assert (
        alice.post(f"/ui/api/linked/{link_id}/unlock", json={"words": "not words"}).status_code
        == 422
    )
    r = alice.post(f"/ui/api/linked/{link_id}/unlock", json={"words": " ".join(words)})
    assert r.status_code == 429 and r.json()["code"] == "too-many-wrong"
    assert int(r.headers["retry-after"]) > 800


def test_an_unused_copy_locks_and_reset_starts_again(server, setup):
    link_id, admin, alice, _ = setup
    words = admin.post(f"/ui/api/settings/links/{link_id}/copy-key").json()["words"]
    now = [1000.0]
    server.copies.clock = lambda: now[0]
    alice.post(f"/ui/api/linked/{link_id}/unlock", json={"words": " ".join(words)})
    from moolakata.links import copies

    now[0] += 59 * 60
    assert copies.sweep(server) == []
    alice.get(f"/ui/api/linked/{link_id}")  # a look at the state isn't a use
    now[0] += 2 * 60
    assert copies.sweep(server) == [link_id]
    assert alice.get(f"/ui/api/linked/{link_id}").json()["household"]["locked"]
    job = admin.post(f"/ui/api/settings/links/{link_id}/reset-copy")
    assert job.status_code == 202 and job.headers["Location"] == f"/ui/api/jobs/{job.json()['id']}"
    assert wait_job(admin, job.json())["state"] == "done", "a reset copy is a job (S13.8.7)"
    out = admin.get("/ui/api/settings/links").json()["links"][0]
    assert out["linkedCopy"]["keyMadeAt"] is None
    assert not lcopy.folder(server.config.data_dir, link_id).exists()
    r = alice.post(f"/ui/api/linked/{link_id}/unlock", json={"words": " ".join(words)})
    assert r.status_code == 422 and r.json()["code"] == "no-key"


def test_files_no_row_names_are_swept_once_old_enough(server, setup):
    # N11: a crash's leftovers go; a file still arriving, or delivered for a change to come,
    # stays (S11.9.6.6).
    import os
    import time

    from moolakata.links import copies
    from moolakata.links.routes import DELIVERED

    link_id, admin, alice, _ = setup
    words = admin.post(f"/ui/api/settings/links/{link_id}/copy-key").json()["words"]
    alice.post(f"/ui/api/linked/{link_id}/unlock", json={"words": " ".join(words)})
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
    # N11: the receiving side records who viewed linked data (S11.8).
    from moolakata.ui import linked

    link_id, admin, alice, _ = setup
    words = admin.post(f"/ui/api/settings/links/{link_id}/copy-key").json()["words"]
    alice.post(f"/ui/api/linked/{link_id}/unlock", json={"words": " ".join(words)})
    linked._viewed.clear()
    for _ in range(3):
        assert alice.get(f"/ui/api/linked/{link_id}/items").status_code == 200
    feed = admin.get("/ui/api/activity").json()["items"]
    seen = [x["text"] for x in feed if "viewed what" in x["text"]]
    assert seen == ["Alice viewed what Margaret & Tom shares"], seen
