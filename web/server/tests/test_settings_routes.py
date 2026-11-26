"""Settings' routes and the save of a setting (requirements S16): who may save one, what a save
refuses at its key, and the sections' own routes' refusals, each with its code and words."""

from conftest import make_user, sign_in
from edits import save_settings
from test_save import create, new, post

from moolakata.keys import master


def _error(r, status: int):
    assert r.status_code == status, r.text
    return r.json()["errors"][0]


def test_only_an_admin_saves_a_setting(server, admin_client):
    make_user(server, "jane")
    jane = sign_in(server, "jane")
    e = _error(post(jane, [create("Setng", new("Setng"), key="serverName", value="x")]), 403)
    assert (e["code"], e["message"]) == ("admins-only", "Only admins can do this.")


def test_a_setting_is_saved_once_by_its_key_and_keeps_it(admin_client):
    """S16: a setting is one record per key, made once, then changed; its key never moves."""
    e = _error(post(admin_client, [create("Setng", new("Setng"), key="nope", value=1)]), 422)
    assert (e["field"], e["code"], e["message"]) == ("key", "setting-unknown", "Not a setting.")
    assert save_settings(admin_client, {"serverName": "doe-home"}).status_code == 200
    again = post(admin_client, [create("Setng", new("Setng"), key="serverName", value="x")])
    e = _error(again, 409)
    assert (e["field"], e["code"]) == ("key", "setting-saved")
    assert e["message"] == "It is saved: change it."
    ref = admin_client.get("/ui/api/settings").json()["records"]["serverName"]
    op = {"op": "update", "entity": "Setng", "id": ref["id"], "version": ref["version"]}
    e = _error(post(admin_client, [{**op, "fields": {"key": "smtpHost"}}]), 422)
    assert (e["field"], e["code"], e["message"]) == ("key", "setting-fixed",
                                                     "A setting keeps its key.")  # fmt: skip
    e = _error(post(admin_client, [{**op, "id": new("Setng")}]), 404)
    assert e["code"] == "not-found"


def test_a_password_setting_is_text_or_none(admin_client):
    """S14.4: a password is a string of 1 to 500 characters, or none to remove it."""
    for bad in ("", 7, "x" * 501):
        e = _error(save_settings(admin_client, {"smtpPassword": bad}), 422)
        assert (e["field"], e["code"], e["message"]) == ("value", "password-invalid",
                                                         "A password, or none.")  # fmt: skip


def _no_email(server, username: str) -> None:
    from sqlalchemy import select

    from moolakata.store.entities.users import User

    with server.db.tx(unscoped="test") as s:
        s.scalars(select(User).where(User.username == username)).one().email = None


def test_a_test_email_needs_an_address_to_send_to(server, admin_client):
    _no_email(server, "admin")
    r = admin_client.post("/ui/api/settings/email/test")
    assert r.status_code == 409 and r.json()["code"] == "no-email"
    assert r.json()["detail"] == "Your profile has no email address to send to."


def test_an_email_not_written_isnt_found(admin_client):
    r = admin_client.get("/ui/api/settings/email/written/20261001-120000-000000-0badcafe.eml")
    assert r.status_code == 404 and r.json()["detail"] == "No such email."


def test_the_bitcoin_test_allows_its_host_for_the_test_and_says_what_failed(
    server, admin_client, monkeypatch
):
    """S1.6, S13.5: Test reaches the saved node, allowed by the egress guard for the test even
    before a wallet needs it, and a failure is answered with its words; the guard is back to
    what Settings allow after."""
    from types import SimpleNamespace

    from moolakata.bitcoin import sources, sync

    seen = []

    def failing():
        seen.append(server.guard.snapshot()[1].get("bitcoin"))
        raise sources.SourceError("the node refused the RPC user")

    cfg = SimpleNamespace(hosts=lambda: ({"node.home.lan"}, ["node.home.lan"]))
    monkeypatch.setattr(sync, "config", lambda s, key: cfg)
    monkeypatch.setattr(sync, "source", lambda srv, s: SimpleNamespace(test=failing))
    assert not server.config.stubs
    r = admin_client.post("/ui/api/settings/bitcoin/test")
    assert r.status_code == 502 and r.json()["code"] == "source-failed"
    assert r.json()["detail"] == "the node refused the RPC user"
    assert seen == [{"node.home.lan"}], "allowed while it ran"
    assert "node.home.lan" not in (server.guard.snapshot()[1].get("bitcoin") or set())


def test_key_storage_answers_what_isnt_there(server, admin_client, master_key, monkeypatch):
    """S15.7.1, S15.8, S16.12: a rotation's phrase no longer on offer, a copy or a previous key
    that isn't there, and Backup Now when the task can't run are each answered as such; a
    phrase that isn't twelve words is a wrong phrase."""
    from moolakata.keys import phrase

    body = {"token": "gone", "words": {"1": "abandon"}, "phrase": "x"}
    r = admin_client.post("/ui/api/settings/keys/rotate", json=body)
    assert r.status_code == 410 and r.json()["code"] == "phrase-gone"
    assert r.json()["detail"] == "That phrase isn't on offer now: show a new one."
    path = "/ui/api/settings/keys/copies/moolakata-20260101-000000"
    r = admin_client.request("DELETE", path, json={"phrase": "not twelve words"})
    assert r.status_code == 403 and r.json()["errors"][0]["code"] == "phrase-wrong"
    words = " ".join(phrase.to_words(master_key))
    r = admin_client.request("DELETE", path, json={"phrase": words})
    assert r.status_code == 404 and r.json()["detail"] == "No such copy."
    r = admin_client.delete("/ui/api/settings/keys/previous/0000-0000")
    assert r.status_code == 404 and r.json()["detail"] == "No such previous key."
    monkeypatch.setattr(server.tasks, "run_now", lambda *a, **k: False)
    r = admin_client.post("/ui/api/settings/backups/run")
    assert r.status_code == 503 and r.json()["code"] == "not-available"
    assert r.json()["detail"] == "Backups can't run right now."


def test_a_setting_changed_or_put_back_only_by_an_admin(server, admin_client):
    """S16: a user who isn't an admin changes no setting; a setting saved again as it is
    records nothing in Activity; one deleted is back to its default."""
    from sqlalchemy import func, select

    from moolakata.store.entities.core import Activity

    def changes():
        with server.db.read(unscoped="test") as s:
            q = select(func.count()).where(Activity.kind == "settings.changed")
            return s.scalar(q.select_from(Activity))

    assert save_settings(admin_client, {"serverName": "doe-home"}).status_code == 200
    before = changes()
    assert save_settings(admin_client, {"serverName": "doe-home"}).status_code == 200
    assert changes() == before, "nothing changed, nothing recorded"
    ref = admin_client.get("/ui/api/settings").json()["records"]["serverName"]
    make_user(server, "jane")
    jane = sign_in(server, "jane")
    op = {"op": "update", "entity": "Setng", "id": ref["id"], "version": ref["version"],
          "fields": {"value": "mine"}}  # fmt: skip
    e = _error(post(jane, [op]), 403)
    assert (e["code"], e["message"]) == ("admins-only", "Only admins can do this.")
    gone = {"op": "delete", "entity": "Setng", "id": ref["id"], "version": ref["version"]}
    assert post(admin_client, [gone]).status_code == 200
    assert admin_client.get("/ui/api/settings").json()["values"]["serverName"] != "doe-home"


def test_a_sign_in_over_none_saved_before_lets_other_settings_save(server, admin_client):
    """S16.2: security None with a username, from before the rule, refuses only a save of
    Email's sign-in keys; any other setting still saves."""
    from moolakata import settings

    with server.db.tx(unscoped="test") as s:
        settings.put(s, "smtpSecurity", "none", None)
        settings.put(s, "smtpUsername", "money@home.lan", None)
    assert save_settings(admin_client, {"serverName": "doe-home"}).status_code == 200
    e = _error(save_settings(admin_client, {"smtpUsername": "m@home.lan"}), 422)
    assert e["code"] == "sign-in-needs-tls"


def test_re_read_all_queues_every_receipt_for_the_reader(server, admin_client, monkeypatch):
    """S9.8.6: Re-read all hands every receipt to the reader at once."""
    from test_receipts import png, upload

    make_user(server, "jane")
    rid = upload(sign_in(server, "jane"), png((1, 2, 3))).json()["id"]
    queued = []
    monkeypatch.setattr(
        server, "reader", type("R", (), {"queue": lambda self, x: queued.append(x)})()
    )
    r = admin_client.post("/ui/api/settings/receipts/reread")
    assert r.status_code == 200, r.text
    assert queued == [rid]


def test_key_storage_shows_a_restore_a_scheduled_and_a_last_re_encryption(
    admin_client, monkeypatch
):
    """S15.7.2, S14.6: what the host's files say of a restore, a re-encryption waiting for the
    restart and the last one finished is shown in Key Storage."""
    from moolakata.store import maintenance, reencrypt

    restore = {"at": "2026-10-01T03:00:00+00:00", "source": "b1"}
    journal = {"scheduledAt": "2026-10-02T03:00:00+00:00", "steps": [1]}
    report = {"finishedAt": "2026-10-03T03:00:00+00:00", "why": "rotation"}
    monkeypatch.setattr(maintenance, "restore_report", lambda c: restore)
    monkeypatch.setattr(reencrypt, "journal", lambda c: journal)
    monkeypatch.setattr(reencrypt, "report", lambda c: report)
    v = admin_client.get("/ui/api/settings/keys").json()
    assert v["lastRestore"]["source"] == "b1"
    assert v["lastRestore"]["at"].startswith("2026-10-01")
    assert v["scheduled"]["why"] == "settings" and v["scheduled"]["started"] is True
    assert v["lastReencryption"]["why"] == "rotation" and v["lastReencryption"]["copies"] == {}
    monkeypatch.setattr(maintenance, "restore_report", lambda c: {"source": "b2"})
    assert admin_client.get("/ui/api/settings/keys").json()["lastRestore"]["at"] is None


def test_verify_key_waits_out_a_failing_names_slowing(server, admin_client, monkeypatch):
    """S13.7.5.1: a login that keeps failing is slowed before its phrase is checked."""
    waited = []
    monkeypatch.setattr(server.sign_in, "delay", lambda *a: waited.append(a) or 0.001)
    r = admin_client.post("/ui/api/settings/keys/verify", json={"phrase": "not a phrase"})
    assert r.status_code == 422 and waited


def test_the_key_test_says_which_part_fails(server, admin_client, monkeypatch):
    """S15.6: Test names what doesn't open: a keyring wrapped under another key, a secret that
    won't open; and says so when a secret does."""
    from types import SimpleNamespace

    from moolakata.keys import master
    from moolakata.keys import secrets as sealing

    assert save_settings(admin_client, {"smtpPassword": "app password"}).status_code == 200
    t = admin_client.post("/ui/api/settings/keys/test").json()
    assert t["ok"] and {"name": "Secrets", "ok": True, "detail": "a secret opens"} in t["checks"]
    real = master.read_keyring(server.config.keyring_path)
    other = SimpleNamespace(master_id=b"\x01" * 16, previous=real.previous)
    monkeypatch.setattr(master, "read_keyring", lambda p: other)

    def broken(*a):
        raise sealing.SecretError("no")

    monkeypatch.setattr(sealing, "open_sealed", broken)
    t = admin_client.post("/ui/api/settings/keys/test").json()
    named = {x["name"]: x for x in t["checks"]}
    assert not t["ok"] and not named["Key storage"]["ok"]
    assert named["Key storage"]["detail"].startswith("the keyring on disk is wrapped under ")
    assert named["Secrets"] == {"name": "Secrets", "ok": False, "detail": "a secret does not open"}


def _offer(admin_client):
    offer = admin_client.post("/ui/api/settings/keys/rotate/phrase").json()
    return {"token": offer["token"],
            "words": {str(n): offer["words"][n - 1] for n in offer["check"]}}  # fmt: skip


def test_a_rotation_refused_by_its_phrase_or_a_pending_re_encryption(
    server, admin_client, master_key, monkeypatch
):
    """S15.7.1: a phrase that isn't twelve words is a wrong one; a rotation while a
    re-encryption waits for the restart is refused; in dev mode a rotation's phrase is kept
    for the next start."""
    import dataclasses

    from moolakata import runtime
    from moolakata.config import RefuseStart
    from moolakata.dev import devmode
    from moolakata.keys import phrase
    from moolakata.store import maintenance

    r = admin_client.post("/ui/api/settings/keys/rotate",
                          json={**_offer(admin_client), "phrase": "not twelve words"})  # fmt: skip
    assert r.status_code == 403 and r.json()["errors"][0]["code"] == "phrase-wrong"
    words = " ".join(phrase.to_words(master_key))

    def pending(*a):
        raise RefuseStart("a re-encryption waits for the restart")

    monkeypatch.setattr(maintenance, "rotate_running", pending)
    r = admin_client.post("/ui/api/settings/keys/rotate",
                          json={**_offer(admin_client), "phrase": words})  # fmt: skip
    assert r.status_code == 409 and r.json()["code"] == "reencrypt-pending"
    assert r.json()["detail"] == "a re-encryption waits for the restart"
    kept = []
    monkeypatch.setattr(maintenance, "rotate_running", lambda cfg, store, *a: (store, {}))
    monkeypatch.setattr(runtime, "restart", lambda srv: None)
    monkeypatch.setattr(devmode, "remember_phrase", lambda cfg, key: kept.append(key))
    monkeypatch.setattr(server, "config", dataclasses.replace(server.config, dev=True))
    r = admin_client.post("/ui/api/settings/keys/rotate",
                          json={**_offer(admin_client), "phrase": words})  # fmt: skip
    assert r.status_code == 200, r.text
    assert len(kept) == 1 and master.fingerprint(kept[0]) == r.json()["fingerprint"]


def test_a_previous_key_forgotten_is_recorded(server, admin_client, monkeypatch):
    """S15.7.1: a previous key nothing needs is dropped from the keyring's list."""
    from sqlalchemy import select

    from moolakata.store import copies
    from moolakata.store.entities.core import Activity

    monkeypatch.setattr(copies, "forget_previous", lambda cfg, fp: True)
    r = admin_client.delete("/ui/api/settings/keys/previous/AAAA-BBBB")
    assert r.status_code == 200 and r.json()["deleted"]["id"] == "AAAA-BBBB"
    with server.db.read(unscoped="test") as s:
        kinds = s.scalars(select(Activity.kind)).all()
    assert "keys.previous-forgotten" in kinds


def test_backups_pass_over_a_copy_they_cant_read_and_backup_now_starts(
    server, admin_client, monkeypatch
):
    """S16.12: a backup whose manifest can't be read isn't listed; fewer days than are kept
    takes the phrase, and words that aren't one are a wrong phrase; Backup Now starts the
    task and records it."""
    import datetime as dt
    import json

    from moolakata.store import maintenance

    # Four days of backups, as the backup task leaves them: a folder each with its manifest.
    made = []
    for day in range(1, 5):
        b = server.config.backup_dir / f"{maintenance.BACKUP_PREFIX}202610{day:02}-031500"
        b.mkdir(parents=True)
        at = dt.datetime(2026, 10, day, 3, 15, tzinfo=dt.UTC).isoformat()
        (b / "manifest.json").write_text(json.dumps({"made": at, "files": {}}))
        made.append(b)
    (made[0] / "manifest.json").unlink()
    names = [b["name"] for b in admin_client.get("/ui/api/settings/backups").json()["backups"]]
    assert made[0].name not in names and len(names) == 3
    r = admin_client.post("/ui/api/settings/backups/copies", json={"copies": 3, "phrase": "x y"})
    assert r.status_code == 403 and r.json()["errors"][0]["code"] == "phrase-wrong"
    monkeypatch.setattr(server.tasks, "run_now", lambda *a, **k: True)
    r = admin_client.post("/ui/api/settings/backups/run")
    assert r.status_code == 202, r.text


def test_re_read_all_needs_reading_on(admin_client):
    """S9.8.7: with Read receipts off, Re-read all is refused, never queued for later."""
    assert save_settings(admin_client, {"readReceipts": False}).status_code == 200
    r = admin_client.post("/ui/api/settings/receipts/reread")
    assert r.status_code == 409 and r.json()["code"] == "reading-off"
    assert r.json()["detail"] == "Turn on Read receipts first."
