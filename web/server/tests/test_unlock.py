"""The locked start (requirements S13.6, S15.4.3): the server comes up with no key anywhere
and answers only what unlocking needs, until the phrase is entered on the unlock page (or by
`keys unlock`, which posts the same way); wrong phrases count toward the lockout."""

import os

import pytest
from conftest import LOOPBACK, ORIGIN
from fastapi.testclient import TestClient

from moolakata.app import Server, create_app
from moolakata.dev.waits import eventually
from moolakata.keys import master, phrase
from moolakata.store import maintenance
from moolakata.store.entities.core import Activity


@pytest.fixture
def locked(keyed_config):
    srv = Server(config=keyed_config)
    with TestClient(create_app(srv), base_url=ORIGIN, client=LOOPBACK) as c:
        yield srv, c
    if srv.store is not None:
        srv.tasks.stop()
        srv.reader.stop()
        srv.db.dispose()


def test_a_locked_server_answers_only_what_unlocking_needs(locked):
    _, c = locked
    r = c.get("/healthz")
    assert r.status_code == 503 and r.json() == {"status": "locked"}
    for path in ("/ui/api/session", "/mcp", "/link/v1/hello", "/connector/v1/hello"):
        r = c.get(path)
        assert r.status_code == 503 and r.json()["code"] == "locked", path
        assert r.headers["retry-after"] == "30"
    assert c.get("/ui/").status_code == 200 and c.get("/ui/settings").status_code == 200
    assert c.get("/demo").status_code in (200, 404)  # the mockup, when installed
    state = c.get("/ui/api/unlock").json()
    assert state["locked"] is True and state["fingerprint"].startswith("mk-")


def test_between_the_unlock_and_readiness_only_what_unlocking_needs_answers(locked, master_key):
    """S13.6, S13.8.4: once the store is open and before the server is ready (its categories,
    guard and tasks still being set up), everything but the open paths answers 503
    `starting`, to be asked again shortly."""
    srv, c = locked
    words = " ".join(phrase.to_words(master_key))
    r = c.post("/ui/api/unlock", json={"phrase": words}, headers={"Origin": ORIGIN})
    assert r.status_code == 200, r.text
    srv.ready = False  # the store open, the rest of the unlock still running
    try:
        assert c.get("/healthz").json()["status"] == "starting"
        for path in ("/ui/api/session", "/mcp", "/link/v1/hello", "/connector/v1/hello"):
            r = c.get(path)
            assert r.status_code == 503 and r.json()["code"] == "starting", path
            assert r.headers["retry-after"] == "5" and r.headers["cache-control"] == "no-store"
        assert c.get("/ui/").status_code == 200
    finally:
        srv.ready = True
    assert c.get("/ui/api/unlock").status_code == 200
    assert c.get("/link/v1/hello").status_code == 200


def test_every_state_healthz_answers_is_in_operations_and_deploy():
    """An uptime monitor set up from either page meets no state it doesn't name (S13.6)."""
    import ast
    import inspect
    import re
    import textwrap

    from moolakata import app, paths

    source = textwrap.dedent(inspect.getsource(app.create_app))
    route = next(
        n
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "healthz"
    )
    assign = next(n for n in route.body if isinstance(n, ast.Assign))
    states = {
        n.value
        for n in ast.walk(assign.value)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert {"ok", "starting", "locked", "uninitialised", "re-encrypting"} == states
    for doc in ("operations.md", "DEPLOY.md"):
        text = (paths.ROOT / "docs" / doc).read_text()
        missing = [s for s in states if not re.search(rf'[`"]{s}[`"]', text)]
        assert missing == [], doc


def test_a_database_from_a_newer_release_is_refused_at_the_unlock(
    locked, master_key, monkeypatch, caplog
):
    """S13.6: the database is read only once the phrase opens it, so a newer release's is
    refused at the unlock, said in a `refusing to unlock:` line, and the server stays locked."""
    from moolakata.store import migrate

    srv, c = locked
    monkeypatch.setattr(migrate, "current", lambda engine: "9999")
    words = " ".join(phrase.to_words(master_key))
    r = c.post("/ui/api/unlock", json={"phrase": words}, headers={"Origin": ORIGIN})
    assert (r.status_code, r.json()["code"]) == (503, "cannot-unlock"), r.text
    assert any(
        m.startswith("refusing to unlock: ") and "from a newer MoolaKata" in m
        for m in caplog.messages
    )
    assert srv.store is None and c.get("/healthz").json() == {"status": "locked"}


def test_the_phrase_unlocks_once_and_wrong_ones_are_counted(locked, master_key):
    srv, c = locked
    headers = {"Origin": ORIGIN}
    r = c.post("/ui/api/unlock", json={"phrase": "not a phrase"}, headers=headers)
    assert r.status_code == 422 and r.json()["code"] == "phrase-invalid"
    other = " ".join(phrase.to_words(os.urandom(16)))
    r = c.post("/ui/api/unlock", json={"phrase": other}, headers=headers)
    assert r.status_code == 403 and r.json()["code"] == "phrase-wrong"
    assert srv.store is None and c.get("/healthz").status_code == 503
    # No Origin: refused before the phrase is even read (S13.7.4).
    assert c.post("/ui/api/unlock", json={"phrase": other}).status_code == 403
    # Something a host command queued while the server was down reaches Activity at unlock.
    maintenance.queue_host_event(srv.config, "key.verified", {"fingerprint": "mk-x"})
    words = " ".join(phrase.to_words(master_key))
    r = c.post("/ui/api/unlock", json={"phrase": words}, headers=headers)
    assert r.status_code == 200 and r.json()["locked"] is False, r.text
    assert srv.store is not None and srv.ready
    assert c.get("/healthz").status_code == 200
    assert c.get("/ui/api/session").status_code == 401  # open, and nobody signed in yet
    r = c.post("/ui/api/unlock", json={"phrase": words}, headers=headers)
    assert r.status_code == 409
    with srv.db.read(unscoped="test") as s:
        kinds = [a.kind for a in s.query(Activity)]
    assert "key.verified" in kinds


def test_ten_wrong_phrases_lock_the_unlock_out(locked):
    """S16.3: Settings can't be read while locked, so the unlock counts by the defaults: the
    tenth wrong phrase is still judged, and locks the address for 15 minutes."""
    _, c = locked
    other = " ".join(phrase.to_words(os.urandom(16)))
    for _ in range(10):
        r = c.post("/ui/api/unlock", json={"phrase": other}, headers={"Origin": ORIGIN})
        assert r.status_code == 403 and r.json()["code"] == "phrase-wrong"
    r = c.post("/ui/api/unlock", json={"phrase": other}, headers={"Origin": ORIGIN})
    assert r.status_code == 429 and 14 * 60 < int(r.headers["retry-after"]) <= 15 * 60 + 1


def test_phrases_being_judged_count_toward_the_lockout(locked, master_key):
    """S13.7.5.1: ten phrases still being judged leave no room for an eleventh, even the right
    one, until they are done."""
    from contextlib import ExitStack

    srv, c = locked
    right = " ".join(phrase.to_words(master_key))
    with ExitStack() as held:
        for _ in range(10):
            held.enter_context(srv.sign_in.attempt(LOOPBACK[0]))
        r = c.post("/ui/api/unlock", json={"phrase": right}, headers={"Origin": ORIGIN})
        assert r.status_code == 429 and srv.store is None
    r = c.post("/ui/api/unlock", json={"phrase": right}, headers={"Origin": ORIGIN})
    assert r.status_code == 200 and srv.store is not None


def test_break_glass_and_backups_go_over_the_host_socket_only(locked, master_key):
    """Host commands reach the running server over its Unix socket (S13.6); the listener has
    no route for them, whatever address a request claims to come from. A locked server issues
    no break-glass code (S15.5.2)."""
    from moolakata.host import create_host_app

    srv, c = locked
    host = TestClient(create_host_app(srv), base_url="http://host")
    words = " ".join(phrase.to_words(master_key))
    r = host.post("/host/keys/break-glass")
    assert r.status_code == 503 and r.json()["code"] == "locked"
    r = host.post("/host/unlock", json={"phrase": words})
    assert r.status_code == 200 and r.json()["locked"] is False, r.text
    r = host.post("/host/keys/break-glass")
    assert r.status_code == 200 and r.json()["code"].startswith("BG-")
    assert srv.break_glass.use(r.json()["code"])
    r = host.post("/host/backup")
    assert r.status_code == 200 and (srv.config.backup_dir / r.json()["name"]).is_dir()
    with srv.db.read(unscoped="test") as s:
        kinds = [a.kind for a in s.query(Activity)]
    assert "keys.break-glass" in kinds and "db.backup" in kinds
    # The listener has none of it: not from loopback, not with a forged forwarding header.
    forged = {"Origin": ORIGIN, "X-Forwarded-For": "127.0.0.1"}
    for path in ("/ui/api/keys/break-glass", "/host/keys/break-glass", "/host/backup"):
        assert c.post(path, json={}, headers=forged).status_code in (404, 405)


def test_keys_unlock_hands_the_phrase_over_the_socket(locked, master_key):
    """`moolakata keys unlock` against a server serving its host socket (S15.4.2): the socket
    is the server account's alone, and the phrase never crosses the network."""
    import asyncio
    import stat
    import threading

    from hypercorn.asyncio import serve

    from moolakata import host
    from moolakata.keys import cli as keys_cli

    srv, _ = locked
    said: list[str] = []
    assert keys_cli.unlock(srv.config, ask=lambda _: "x", say=said.append) == 1  # not a phrase
    words = " ".join(phrase.to_words(master_key))
    assert keys_cli.unlock(srv.config, ask=lambda _: words, say=said.append) == 1
    assert "no socket" in said[-1]
    stop = threading.Event()
    loop = asyncio.new_event_loop()

    async def until_stopped():
        await asyncio.to_thread(stop.wait)

    hc = host.hypercorn_config(srv.config)
    t = threading.Thread(
        target=lambda: loop.run_until_complete(
            serve(host.create_host_app(srv), hc, shutdown_trigger=until_stopped)
        ),
        daemon=True,
    )
    t.start()
    try:
        for _ in range(100):
            if srv.config.socket_path.exists():
                break
            threading.Event().wait(0.05)
        assert stat.S_IMODE(srv.config.socket_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(srv.config.socket_path.parent.stat().st_mode) == 0o700
        assert keys_cli.unlock(srv.config, ask=lambda _: words, say=said.append) == 0, said
        assert said[-1].startswith("unlocked: mk-") and srv.store is not None
        said.clear()
        assert keys_cli.break_glass(srv.config, say=said.append) == 0, said
        assert said[0].startswith("BG-") and "Settings › Key Storage › Rotate" in said[0]
    finally:
        stop.set()
        t.join(10)


def test_a_scheduled_reencryption_runs_at_the_unlock_before_the_server_serves(locked, master_key):
    """S15.7.2: scheduled, it runs when the phrase is given, the locked screen following its
    progress and /healthz answering re-encrypting, then the server serves under a new key."""

    from moolakata.store import reencrypt

    srv, c = locked
    maintenance.open_store(srv.config, master_key).db.dispose()  # a database to re-encrypt
    before = srv.config.keyring_path.read_text()
    reencrypt.schedule(srv.config, {}, None, "settings")
    words = " ".join(phrase.to_words(master_key))
    wrong = " ".join(phrase.to_words(os.urandom(16)))
    r = c.post("/ui/api/unlock", json={"phrase": wrong}, headers={"Origin": ORIGIN})
    assert r.status_code == 403, "the phrase is checked before anything starts"
    r = c.post("/ui/api/unlock", json={"phrase": words}, headers={"Origin": ORIGIN})
    assert r.status_code == 200, r.text
    seen = []

    def unlocked() -> bool:
        state = c.get("/ui/api/unlock").json()
        seen.append((state["locked"], state["reencrypting"], c.get("/healthz").json()["status"]))
        return not state["locked"]

    eventually(unlocked, timeout=60, what="unlocked, re-encrypted")
    assert seen[-1][0] is False and c.get("/healthz").status_code == 200
    assert reencrypt.journal(srv.config) is None and reencrypt.report(srv.config)["backup"]
    assert srv.config.keyring_path.read_text() != before
    with srv.db.read(unscoped="test") as s:
        assert "keys.reencrypted" in [a.kind for a in s.query(Activity)]


def test_reencrypt_now_schedules_it_and_restarts_never_running_while_serving(server, admin_client):
    """S15.7.2: Settings › Key Storage's Re-encrypt now, after the password again, schedules it and
    restarts the server; the unlock that follows runs it. Once scheduled it is neither withdrawn nor
    replaced."""
    from conftest import stale

    from moolakata.store import reencrypt

    b = maintenance.backup(server.config, server.store)
    stale(server)
    r = admin_client.post("/ui/api/settings/keys/reencrypt", json={"copies": {}})
    assert r.status_code == 403 and r.json()["code"] == "reauth-required"
    admin_client.post("/ui/api/session/reauth", json={"password": "a long admin passphrase"})
    r = admin_client.post("/ui/api/settings/keys/reencrypt", json={"copies": {"x": "bogus"}})
    assert r.status_code == 422
    r = admin_client.post("/ui/api/settings/keys/reencrypt", json={"copies": {}})
    assert r.status_code == 200 and r.json()["restarting"] is True, r.text
    assert r.json()["copies"] == {b.name: "reencrypt"}, "re-encrypt, the default"
    assert server.restarting and reencrypt.pending(server.config)
    assert not reencrypt.next_keyring(server.config).exists(), "nothing runs while serving"
    r = admin_client.post("/ui/api/settings/keys/reencrypt", json={"copies": {b.name: "leave"}})
    assert r.status_code == 409 and r.json()["code"] == "reencrypt-pending"
    assert reencrypt.journal(server.config)["copies"] == {b.name: "reencrypt"}
    assert admin_client.delete("/ui/api/settings/keys/reencrypt").status_code in (404, 405)


def _offered_words(offer: dict) -> dict:
    return {str(n): offer["words"][n - 1] for n in offer["check"]}


def test_rotate_in_settings_with_the_phrase_or_a_break_glass_code(server, admin_client, master_key):
    """S15.7.1, S15.5.2: Rotate takes the password again and the current phrase, or a
    break-glass code from the host; three words of the new phrase typed back; then the keyring
    is under the new key, the re-encryption journaled and the server restarting. A wrong
    phrase or code is refused and counted."""
    from moolakata.store import reencrypt

    offer = admin_client.post("/ui/api/settings/keys/rotate/phrase").json()
    assert len(offer["words"]) == 12 and len(offer["check"]) == 3
    wrong = " ".join(phrase.to_words(os.urandom(16)))
    body = {"token": offer["token"], "words": _offered_words(offer), "phrase": wrong}
    r = admin_client.post("/ui/api/settings/keys/rotate", json=body)
    assert r.status_code == 403 and r.json()["code"] == "phrase-wrong"
    r = admin_client.post(
        "/ui/api/settings/keys/rotate", json={**body, "phrase": None, "code": "BG-AAAA-AAAA"}
    )
    assert r.status_code == 403 and r.json()["code"] == "code-wrong"
    r = admin_client.post(
        "/ui/api/settings/keys/rotate", json={**body, "words": {"1": "zzzz"}, "phrase": wrong}
    )
    assert r.status_code == 422 and r.json()["code"] == "words-wrong"
    with server.db.read(unscoped="test") as s:
        assert [a.kind for a in s.query(Activity)].count("signin.failed") == 2
    assert not server.restarting and not reencrypt.pending(server.config)
    code, _ = server.break_glass.issue()
    r = admin_client.post(
        "/ui/api/settings/keys/rotate", json={**body, "phrase": None, "code": code}
    )
    assert r.status_code == 200, r.text
    assert r.json()["fingerprint"] == offer["fingerprint"] and server.restarting
    ring = master.read_keyring(server.config.keyring_path)
    assert master.fingerprint(ring.master_id) == offer["fingerprint"]
    assert [p.master_id for p in ring.previous] == [master.key_id(master_key)]
    j = reencrypt.journal(server.config)
    assert j["why"] == "rotation" and j["to"] == ring.master_id
    with server.db.read(unscoped="test") as s:
        rotated = s.query(Activity).filter(Activity.kind == "key.rotated").one()
    assert '"break-glass"' in rotated.detail
    # Once rotated, a second rotation waits for the restart.
    again = admin_client.post("/ui/api/settings/keys/rotate/phrase").json()
    r = admin_client.post(
        "/ui/api/settings/keys/rotate",
        json={
            "token": again["token"],
            "words": _offered_words(again),
            "phrase": " ".join(phrase.to_words(master_key)),
        },
    )
    assert r.status_code in (403, 409)


def test_removing_a_copy_asks_for_the_phrase_too(server, admin_client, master_key):
    """S16.13, S13.7.2: Remove takes the password again and the recovery phrase, so an admin's
    session alone deletes no backup; a wrong phrase is refused and counted."""
    b = maintenance.backup(server.config, server.store)
    path = f"/ui/api/settings/keys/copies/{b.name}"
    wrong = " ".join(phrase.to_words(os.urandom(16)))
    r = admin_client.request("DELETE", path, json={"phrase": wrong})
    assert r.status_code == 403 and r.json()["code"] == "phrase-wrong"
    assert b.exists()
    words = " ".join(phrase.to_words(master_key))
    r = admin_client.request("DELETE", path, json={"phrase": words})
    assert r.status_code == 200, r.text
    assert not b.exists()
    with server.db.read(unscoped="test") as s:
        assert "signin.failed" in [a.kind for a in s.query(Activity)]


def test_fewer_backup_days_than_are_kept_takes_the_phrase(server, admin_client, master_key):
    """*Copies kept* lowered below the days of backups there are deletes some at the next backup, so
    it takes the password again and the recovery phrase; never below 3."""
    import datetime as dt

    from edits import save_settings

    t0 = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
    for i in range(5):
        maintenance.backup(server.config, server.store, t0 + dt.timedelta(days=i))
    r = save_settings(admin_client, {"backupCopies": 4})
    assert r.status_code == 403 and r.json()["errors"][0]["code"] == "phrase-needed", r.text
    assert save_settings(admin_client, {"backupCopies": 2}).status_code == 422
    r = admin_client.post("/ui/api/settings/backups/copies", json={"copies": 4})
    assert r.status_code == 422 and r.json()["code"] == "phrase-needed"
    wrong = " ".join(phrase.to_words(os.urandom(16)))
    r = admin_client.post("/ui/api/settings/backups/copies", json={"copies": 4, "phrase": wrong})
    assert r.status_code == 403 and r.json()["code"] == "phrase-wrong"
    words = " ".join(phrase.to_words(master_key))
    r = admin_client.post("/ui/api/settings/backups/copies", json={"copies": 2, "phrase": words})
    assert r.status_code == 422
    r = admin_client.post("/ui/api/settings/backups/copies", json={"copies": 4, "phrase": words})
    assert r.status_code == 200 and r.json()["copies"] == 4, r.text
    with server.db.read(unscoped="test") as s:
        kinds = [a.kind for a in s.query(Activity)]
    assert "signin.failed" in kinds and "settings.changed" in kinds
    # More days than there are backups for asks nothing.
    r = admin_client.post("/ui/api/settings/backups/copies", json={"copies": 30})
    assert r.status_code == 200 and r.json()["copies"] == 30
    assert save_settings(admin_client, {"backupCopies": 31}).status_code == 200


# ---------- the unlock's rarer answers (S15.4.3, S15.7.2) ----------


def _unlock(c, key: bytes):
    return c.post(
        "/ui/api/unlock",
        json={"phrase": " ".join(phrase.to_words(key))},
        headers={"Origin": ORIGIN},
    )


def test_a_phrase_while_a_reencryption_runs_is_asked_to_wait(locked, master_key):
    from moolakata.store import reencrypt

    srv, c = locked
    srv.reencrypting = reencrypt.Progress()
    try:
        r = _unlock(c, master_key)
    finally:
        srv.reencrypting = None
    assert r.status_code == 409 and r.json()["code"] == "re-encrypting"
    assert r.json()["detail"] == "MoolaKata is re-encrypting: wait for it." and srv.store is None


def test_a_phrase_beaten_by_another_unlock_is_told_it_is_unlocked(locked, master_key, monkeypatch):
    """Two phrases at once: the one that finds the store opened meanwhile is told so."""
    from moolakata import runtime

    srv, c = locked

    async def opened_meanwhile(server, key, seed=False, wait=True):
        raise runtime.AlreadyUnlocked

    monkeypatch.setattr(runtime, "unlock", opened_meanwhile)
    r = _unlock(c, master_key)
    assert r.status_code == 409 and r.json()["code"] == "unlocked-already"
    assert r.json()["detail"] == "MoolaKata is already unlocked." and srv.store is None


def test_a_rotation_pending_under_another_phrase_names_it(locked, master_key):
    """S15.7.2: a rotation's re-encryption finishes only with the new phrase; the old one is
    told which."""
    from moolakata.store import reencrypt

    srv, c = locked
    new = os.urandom(16)
    ring = master.read_keyring(srv.config.keyring_path)
    data_key = master.unwrap(master_key, ring)
    later = master.wrap(new, data_key, ring.master_created, ring.data_key_created)
    reencrypt.schedule(srv.config, {}, None, "rotation", to=master.key_id(new))
    master.write_keyring(reencrypt.next_keyring(srv.config), later)
    r = _unlock(c, master_key)
    assert r.status_code == 409 and r.json()["code"] == "reencrypt-pending"
    assert r.json()["detail"] == (
        f"A re-encryption is pending under {master.fingerprint(new)}: unlock with that phrase "
        "so it can finish."
    )


def test_a_database_that_wont_open_is_answered_without_its_reason(locked, master_key):
    """The reason is in the server's log; the page says only that it can't (S13.7.9)."""
    srv, c = locked
    srv.config.db_path.write_bytes(b"not a database" * 100)
    r = _unlock(c, master_key)
    assert r.status_code == 503 and r.json()["code"] == "cannot-unlock"
    assert r.json()["detail"] == "The server cannot open its data: see its log."
    assert srv.store is None
