"""What a background task or a second call can do in the middle of an operation that writes
files or rows in more than one step (requirements S17.5.10). Each pair runs the competing work
at a named checkpoint (moolakata/checkpoints.py) inside the operation, so the race happens every
run, never by luck. The inventory names every task the server runs and the operations it
shares data with outside one transaction: a task added without its row fails here."""

import os
import threading
import time

import pytest
from conftest import make_user, sign_in
from test_links import _shared_receipt, admins, links_of, pair  # noqa: F401

from moolakata import checkpoints
from moolakata.links import copies, copy
from moolakata.links import manage as link_manage
from moolakata.receipts import retention

# Every background task (S13.4), what it touches, and the operations it could race outside one
# transaction, each with its test below; "" where it works in single transactions only.
INVENTORY = {
    "backups": "the database by SQLite's backup, consistent on its own: none",
    "pruning": "sessions and one-time tokens, in one transaction: none",
    "prices": "price rows, in transactions: none",
    "mail": "the mail folder's files, its own: none",
    "options": "expiries, in transactions: none",
    "bitcoin": "wallet rows, in transactions: none",
    "links": (
        "pulls: test_the_hourly_pull_and_pull_now_on_one_link, "
        "test_two_servers_pulling_each_other_at_once"
    ),
    "linked-copies": (
        "copies' receipts folders: test_the_sweep_during_a_pull, "
        "test_the_sweep_during_an_unlocks_apply, test_the_sweep_while_a_receipt_is_delivered"
    ),
    "alerts": "alert rows, in transactions: none",
    "host-events": "the host's events, read: none",
    "alert-summaries": "emails queued, in transactions: none",
}
# And what admins start by hand on the same data: the main receipts folder.
BY_HAND = {
    "Settings › Storage › Remove orphans": "test_remove_orphans_during_an_upload",
    "Settings › Storage › Prune": "test_a_prune_while_an_upload_reuses_the_file",
}


def test_every_task_is_in_the_inventory(server):
    from moolakata import runtime

    runtime.register_tasks(server)
    assert set(server.tasks._tasks) == set(INVENTORY)


def at(monkeypatch, name, fn):
    """Run `fn` at the named checkpoint, once."""
    done = []

    def hook():
        if not done:
            done.append(True)
            fn()

    monkeypatch.setitem(checkpoints.HOOKS, name, hook)
    return done


def age(folder):
    """Every file in it an hour old: past the sweep's grace, so only the rule keeps it."""
    hour_ago = time.time() - 3600
    for f in folder.iterdir():
        os.utime(f, (hour_ago, hour_ago))


def receipts_of(srv, link_id):
    return copy.folder(srv.config.data_dir, link_id) / "receipts"


def opened(carol, b_id, image):
    files = carol.get(f"/ui/api/linked/{b_id}/files").json()["items"]
    assert files and all(f["arrived"] for f in files)
    got = [carol.get(f"/ui/api/linked/{b_id}/files/{f['id']}").content for f in files]
    assert image in got


def shared_account(src, c_src, c_dst):
    """Alice on `src` shares an account, its receipts included, with Carol on the other
    server, whose copy has its access key; nothing pulled yet. Returns Alice, the words, the
    other side's link id and the account's id."""
    from edits import make, share
    from linkpair import linked

    make_user(src, "alice")
    alice = sign_in(src, "alice")
    src_id, dst_id = linked(c_src, c_dst)
    acct = make(alice, "Acct", name="Checking", type="checking").json()
    carol = next(u for u in links_of(c_src)["links"][0]["users"] if u["username"] == "carol")
    words = c_dst.post(f"/ui/api/settings/links/{dst_id}/copy-key").json()["words"]
    share(alice, "account", acct["id"], users={carol["id"]: "read"}, receipts={src_id: True})
    return alice, " ".join(words), dst_id, acct["id"]


def add_receipt(alice, acct_id: str, payee: str = "Blue Bottle") -> bytes:
    """A transaction on the account with a receipt of its own; the receipt's bytes."""
    from edits import attach, saved
    from test_accounts import add
    from test_receipts import png

    t = add(alice, acct_id, amount="-12.50", payee=payee)
    image = png((len(payee) * 7 % 256, 90, 160))  # its own bytes, so never one already kept
    rid = alice.post(
        "/ui/api/receipts", files={"file": ("r.png", image, "application/octet-stream")}
    ).json()["id"]
    saved(attach(alice, rid, t["id"]))
    return image


# ---------- a linked copy's receipts (CR3-54)


def test_the_sweep_during_an_unlocks_apply(admins, monkeypatch):  # noqa: F811
    """A receipt pulled while the copy was locked is named only in the inbox until the
    unlock's apply writes its row: the sweep, run as the apply opens the inbox, keeps it."""
    a, b, ca, cb, _ = admins
    make_user(b, "carol")
    _alice, words, b_id, image = _shared_receipt(a, ca, cb)
    cb.post(f"/ui/api/settings/links/{b_id}/pull")  # waits in the inbox: the copy is locked
    age(receipts_of(b, b_id))
    swept = []
    ran = at(monkeypatch, "apply.opened", lambda: swept.append(copies.orphans(b, b_id)))
    carol = sign_in(b, "carol")
    assert carol.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)}).is_success
    assert ran and swept == [0], "the store was busy: nothing went"
    opened(carol, b_id, image)


def test_the_sweep_during_a_pull(admins, monkeypatch):  # noqa: F811
    """A pull's fetched receipts are named only in what it holds until its rows are written:
    the sweep, run as each arrives with the copy open, keeps them."""
    a, b, ca, cb, _ = admins
    make_user(b, "carol")
    alice, words, b_id, acct = shared_account(a, ca, cb)
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    carol = sign_in(b, "carol")
    assert carol.post(f"/ui/api/linked/{b_id}/unlock", json={"words": words}).is_success
    image = add_receipt(alice, acct)
    swept = []

    def sweep():
        age(receipts_of(b, b_id))
        swept.append(copies.orphans(b, b_id))

    ran = at(monkeypatch, "receipt.fetched", sweep)
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    assert ran and swept == [0], "the store was busy: nothing went"
    opened(carol, b_id, image)


def test_the_sweep_while_a_receipt_is_delivered(admins, monkeypatch):  # noqa: F811
    """A receipt the peer delivers with its change is kept, then named for the change that
    follows it: the sweep between the two keeps it."""
    a, b, ca, cb, _ = admins
    make_user(a, "carol")
    # B's Alice shares with A's Carol, and B makes the exchange, so B delivers to A.
    alice, words, a_id, acct = shared_account(b, cb, ca)
    b_id = links_of(cb)["links"][0]["id"]
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    carol = sign_in(a, "carol")
    assert carol.post(f"/ui/api/linked/{a_id}/unlock", json={"words": words}).is_success
    image = add_receipt(alice, acct)
    swept = []

    def sweep():
        age(receipts_of(a, a_id))
        swept.append(copies.orphans(a, a_id))

    ran = at(monkeypatch, "deliver.kept", sweep)
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    assert ran and swept == [0]
    opened(carol, a_id, image)


def test_a_receipt_whose_file_is_gone_by_the_unlock_is_asked_for_again(admins):  # noqa: F811
    """Decision 4's second line: whatever took the file, the receipt is one not yet arrived,
    and the next exchange fetches it, never a row naming a missing file."""
    a, b, ca, cb, _ = admins
    make_user(b, "carol")
    _alice, words, b_id, image = _shared_receipt(a, ca, cb)
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    for f in receipts_of(b, b_id).iterdir():
        f.unlink()
    carol = sign_in(b, "carol")
    assert carol.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)}).is_success
    (f,) = carol.get(f"/ui/api/linked/{b_id}/files").json()["items"]
    assert f["arrived"] is False
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    opened(carol, b_id, image)


# ---------- the main receipts folder (CR3-375)


def test_remove_orphans_during_an_upload(server, monkeypatch):
    """An upload writes its file before its row is committed (the thumbnail drawn between):
    Remove orphans then keeps it, and removes an old file no row names."""
    from conftest import new_client

    make_user(server, "alice")
    alice = sign_in(server, "alice")
    folder = server.config.receipts_dir
    folder.mkdir(parents=True, exist_ok=True)
    leftover = folder / ("0" * 32 + ".mkr")
    leftover.write_bytes(b"left by a restore")
    removed = []

    def remove():
        # Read only: the upload holds the write lock today (CR3-48); the rule, not the lock,
        # is what keeps its file once the thumbnail is drawn outside it.
        age(folder)
        with server.db.read() as s:
            removed.append(retention.remove_orphans(server, s))

    ran = at(monkeypatch, "receipt.written", remove)
    from test_receipts import png

    image = png()
    r = alice.post("/ui/api/receipts", files={"file": ("r.png", image, "application/octet-stream")})
    assert r.status_code == 201, r.text
    assert ran and removed[0][0] == 1, "the leftover went, the upload's file stayed"
    assert not leftover.exists()
    got = alice.get(f"/ui/api/receipts/{r.json()['id']}/file")
    assert got.status_code == 200 and got.content == image
    assert new_client  # the upload went through the app, as a browser's does


def test_a_prune_while_an_upload_reuses_the_file(server, monkeypatch):
    """Bob uploads the bytes of Alice's receipt as it is pruned: the file Bob's receipt reuses
    stays, though Alice's no longer needs it."""
    from test_receipts import png

    from moolakata.store.entities.receipts import Receipt

    make_user(server, "alice")
    make_user(server, "bob")
    alice, bob = sign_in(server, "alice"), sign_in(server, "bob")
    image = png()
    first = alice.post(
        "/ui/api/receipts", files={"file": ("r.png", image, "application/octet-stream")}
    )
    freed = []
    with server.db.read() as s:
        name = f"{s.get(Receipt, first.json()['id']).fileId}.mkr"

    def prune():
        # What prune_files does with the file once no live receipt needs it (S14.10.5).
        freed.append(server.files.of(server.config.receipts_dir).remove(name))

    ran = at(monkeypatch, "receipt.reused", prune)
    second = bob.post(
        "/ui/api/receipts", files={"file": ("r.png", image, "application/octet-stream")}
    )
    assert second.status_code == 201, second.text
    assert ran and freed == [0], "held for Bob's receipt"
    got = bob.get(f"/ui/api/receipts/{second.json()['id']}/file")
    assert got.status_code == 200 and got.content == image


# ---------- two pulls of one link


def test_the_hourly_pull_and_pull_now_on_one_link(admins, monkeypatch):  # noqa: F811
    """CR3-376: the hourly task's pull and an admin's Pull now on the same link at once. The
    second, started while the first is between its call and its rows, waits its turn: the link
    comes out as two pulls in a row leave it, nothing asked for again in full."""
    from moolakata.store.entities.links import Link

    a, b, ca, cb, _ = admins
    make_user(b, "carol")
    alice, words, b_id, acct = shared_account(a, ca, cb)
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    carol = sign_in(b, "carol")
    assert carol.post(f"/ui/api/linked/{b_id}/unlock", json={"words": words}).is_success
    image = add_receipt(alice, acct)
    errors, threads = [], []

    def run():
        try:
            link_manage.exchange(b, b_id)
        except Exception as e:
            errors.append(e)

    def second():
        t = threading.Thread(target=run)
        t.start()
        threads.append(t)

    ran = at(monkeypatch, "exchange.called", second)
    link_manage.exchange(b, b_id)
    threads[0].join(30)
    assert ran and not threads[0].is_alive(), "the second pull ran once the first was done"
    assert errors == []
    link = next(x for x in links_of(cb)["links"] if x["id"] == b_id)
    assert link["lastError"] is None
    with b.db.read() as s:
        assert not s.get(Link, b_id).needsFull, "no change was taken twice or out of order"
    opened(carol, b_id, image)


def test_two_servers_pulling_each_other_at_once(admins, monkeypatch):  # noqa: F811
    """CR3-376: while B pulls from A, A's pull from B is refused `busy` at once, never kept
    waiting (both waiting would hold both); it is no failure, and A's next pull goes through."""
    from moolakata.links.client import LinkError

    a, b, ca, cb, _ = admins
    make_user(b, "carol")
    alice, _words, b_id, acct = shared_account(a, ca, cb)
    a_id = links_of(ca)["links"][0]["id"]
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    add_receipt(alice, acct)
    refused = []

    def a_pulls():
        def run():
            try:
                link_manage.exchange(a, a_id)
            except LinkError as e:
                refused.append(e.code)

        t = threading.Thread(target=run)
        t.start()
        t.join(30)
        assert not t.is_alive(), "answered at once, never kept waiting"

    ran = at(monkeypatch, "exchange.called", a_pulls)
    link_manage.exchange(b, b_id)
    assert ran and refused == ["busy"]
    link = next(x for x in links_of(ca)["links"] if x["id"] == a_id)
    assert link["lastError"] and link["failingSince"] is None, "named, not alerted"
    link_manage.exchange(a, a_id)
    link = next(x for x in links_of(ca)["links"] if x["id"] == a_id)
    assert link["lastError"] is None


@pytest.fixture(autouse=True)
def no_hooks_left():
    yield
    checkpoints.HOOKS.clear()
