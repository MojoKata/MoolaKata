"""The store's machinery at its edges (requirements S14, S15.6, S15.7): the copies on the host,
backups, restores and re-encryption, in the cases the main tests (test_store.py) don't reach."""

import datetime as dt
import json
import os
import shutil

import pytest

from moolakata.config import RefuseStart
from moolakata.keys import files, master
from moolakata.store import copies, maintenance

# ---------- the copies on the host (S15.7) ----------


def _tiny(path, key: str) -> None:
    """A small database under a key, to stand for a copy's (a whole export takes seconds)."""
    from moolakata.store.db import connect

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path, key)
    conn.execute("CREATE TABLE t (x)")
    conn.close()


def _folder_copy(config, name: str):
    """A backup as the copies' list finds it: its keyring is all a choice needs."""
    folder = config.backup_dir / name
    folder.mkdir(parents=True)
    shutil.copy2(config.keyring_path, folder / "keyring")
    return folder


def _pre_upgrade(config, store, name: str, ring: master.Keyring | None) -> copies.Copy:
    """A copy made before a migration: the database, and its keyring beside it when given."""
    older = config.data_dir / "pre-upgrade"
    older.mkdir(exist_ok=True)
    db = older / f"moolakata-before-{name}-t.db"
    _tiny(db, store.keys.keys.sqlcipher_key)
    if ring is not None:
        master.write_keyring(db.with_suffix(".keyring"), ring)
    return copies.find(config, db.name)


def test_the_copies_list_passes_over_what_isnt_one(keyed_config):
    """S15.7: a backup still being written, a stray file, a before-restore file that isn't a
    folder or a set-aside keyring that isn't a file are no copies."""
    made = _folder_copy(keyed_config, "moolakata-20261001-000000")
    (keyed_config.backup_dir / "notes.txt").write_text("not a backup")
    (keyed_config.backup_dir / "moolakata-20260101-000000.part").mkdir()
    (keyed_config.data_dir / "before-restore-20260101-000000").write_text("not a folder")
    (keyed_config.data_dir / (copies.SET_ASIDE_RING + "20260101-000000")).mkdir()
    assert [c.name for c in copies.copies(keyed_config)] == [made.name]
    assert copies.find(keyed_config, "moolakata-20991231-000000") is None


def test_a_copy_says_how_it_opens_by_its_keyring(store, keyed_config, master_key):
    """S15.7: with this phrase and the data key the server holds (`current`), this phrase and
    an earlier data key (`phrase`), an earlier phrase (`previous`), or no readable keyring
    (`unknown`), which is when its manifest's time is unread too."""
    earlier_key = master.wrap(
        master_key, master.new_data_key(), master.now(), master.now(), store.keys.ring.previous
    )
    other = master.wrap(os.urandom(16), store.keys.data_key, master.now(), master.now(), ())
    assert copies.opens_with(_pre_upgrade(keyed_config, store, "0001", None), store.keys) == (
        "unknown"
    )
    assert copies.opens_with(
        _pre_upgrade(keyed_config, store, "0002", earlier_key), store.keys
    ) == ("phrase")
    assert copies.opens_with(_pre_upgrade(keyed_config, store, "0003", other), store.keys) == (
        "previous"
    )
    unread = keyed_config.backup_dir / "moolakata-20260102-000000"
    unread.mkdir(parents=True)
    (unread / "keyring").write_text("not a keyring")
    (unread / "manifest.json").write_text("{")
    c = copies.find(keyed_config, unread.name)
    assert c.ring is None and copies.opens_with(c, store.keys) == "unknown"
    assert c.made == dt.datetime.fromtimestamp(unread.stat().st_mtime, dt.UTC).replace(
        microsecond=0
    )


def test_a_copy_rewritten_under_a_new_key_takes_its_receipts_and_keeps_its_manifest_true(
    store, keyed_config, master_key
):
    """S15.7.2, S15.6.8: a before-restore folder's receipt files are rewritten with it; a
    backup's manifest is signed again, even one whose database is gone; one whose manifest
    can't be read keeps it as it is; a set-aside keyring holds no database to rewrite."""
    old, new = store.keys.data_key, master.new_data_key()
    old_keys, new_keys = master.DataKeys.derive(old), master.DataKeys.derive(new)
    aside = keyed_config.data_dir / "before-restore-20260101-000000"
    (aside / "receipts").mkdir(parents=True)
    shutil.copy2(keyed_config.keyring_path, aside / "keyring")
    files.write(aside / "receipts" / "r.mkr", [b"ok"], old_keys.receipts.public_key(), "r")
    no_db = _folder_copy(keyed_config, "moolakata-20261001-000000")  # a backup, its file gone
    (no_db / "manifest.json").write_text(json.dumps({"made": "2026-10-01T00:00:00+00:00"}))
    bad = keyed_config.backup_dir / "moolakata-20260102-000000"
    bad.mkdir()
    shutil.copy2(keyed_config.keyring_path, bad / "keyring")
    (bad / "manifest.json").write_text("{")
    ring = keyed_config.data_dir / (copies.SET_ASIDE_RING + "20260101-000000")
    shutil.copy2(keyed_config.keyring_path, ring)
    for name in (aside.name, no_db.name, bad.name, ring.name):
        copies.reencrypt_with(copies.find(keyed_config, name), old, new, master_key)
    from moolakata.store import reencrypt

    assert reencrypt.opens(aside / "receipts" / "r.mkr", new_keys.receipts, "r")
    for name in (aside.name, no_db.name, bad.name, ring.name):
        assert copies.find(keyed_config, name).ring.data_key_id == master.data_key_id(new)
    manifest = json.loads((no_db / "manifest.json").read_text())
    assert list(manifest["files"]) == ["keyring"]
    assert manifest["mac"] == maintenance.manifest_mac(manifest, new)
    assert (bad / "manifest.json").read_text() == "{"


def test_a_file_made_as_root_is_given_to_the_servers_account(tmp_path, monkeypatch):
    """S14.2: a command run as root leaves what it writes to the server's own account."""
    given = []
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(os, "chown", lambda path, uid, gid: given.append((path, uid, gid)))
    copies.chown_to_server(tmp_path / "keyring.next")
    assert given == [(tmp_path / "keyring.next", 10001, 10001)]


def _journal(config, steps: dict, **more) -> None:
    from moolakata.store import reencrypt as journaled

    j = {"why": "settings", "scheduledAt": "2026-10-01T00:00:00+00:00", "by": None,
         "copies": {}, "steps": steps, **more}  # fmt: skip
    (config.data_dir / journaled.JOURNAL).write_text(json.dumps(j))


# ---------- opening, host events, backups and restores (S14.6, S15.4.7, S15.6.8) ----------


def test_a_database_that_fails_to_open_for_another_reason_refuses_the_start(
    keyed_config, master_key, monkeypatch
):
    """S15.4: a database that can't be opened at all says so by the kind of failure, never by
    what it holds."""

    class Engine:
        def connect(self):
            raise PermissionError("denied")

    monkeypatch.setattr(maintenance, "make_engine", lambda path, key: Engine())
    with pytest.raises(RefuseStart, match="cannot be opened: PermissionError"):
        maintenance.open_store(keyed_config, master_key)


def test_a_reencryption_already_scheduled_runs_as_scheduled(store, keyed_config, master_key):
    """S15.7.2: on the host, a run already in the journal is carried out with its own choices;
    the ones given now don't replace them."""
    from moolakata.store import reencrypt as journaled

    b = _folder_copy(keyed_config, "moolakata-20261001-000000")
    _journal(keyed_config, {"backup": None}, copies={b.name: "delete"})
    again = maintenance.reencrypt(keyed_config, store, master_key, {b.name: "leave"})
    assert journaled.report(keyed_config)["copies"][b.name] == "deleted"
    assert not b.exists()
    again.db.dispose()


def test_a_host_event_goes_to_the_queue_the_server_hasnt_taken(keyed_config, monkeypatch):
    """S15.7.4: a line is written to the file at the queue's name; one removed or taken while
    it waited for the lock is opened again. Root's queue is given to the server's account."""
    real_stat, gone = os.stat, []
    queue = keyed_config.data_dir / maintenance.HOST_EVENTS

    def stat(path, *a, **k):
        if path == queue and not gone:
            gone.append(path)
            raise FileNotFoundError(path)
        return real_stat(path, *a, **k)

    given = []
    monkeypatch.setattr(os, "stat", stat)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(os, "chown", lambda path, uid, gid: given.append((path, uid)))
    maintenance.queue_host_event(keyed_config, "db.shell", {})
    monkeypatch.undo()
    assert gone == [queue] and given == [(queue, 10001)]
    with open(queue, "a") as f:
        f.write("not json\n")
    assert [e["kind"] for e in maintenance.take_host_events(keyed_config)] == ["db.shell"]


def test_a_backups_time_comes_from_its_manifest(keyed_config):
    """S14.6: a copy with no manifest has no time of its own; a manifest that doesn't say
    when, or a backup named with no time, is refused."""
    assert maintenance.made_of(keyed_config.data_dir) is None
    b = _folder_copy(keyed_config, "moolakata-20261001-000000")
    manifest = {"made": "2026-10-01T00:00:00+00:00", "files": {}}
    (b / "manifest.json").write_text(json.dumps({k: v for k, v in manifest.items() if k != "made"}))
    with pytest.raises(RefuseStart, match="manifest doesn't say when it was made"):
        maintenance.made_of(b)
    (b / "manifest.json").write_text(json.dumps(manifest))
    renamed = b.with_name("moolakata-latest")
    b.rename(renamed)
    with pytest.raises(RefuseStart, match="not when its name says"):
        maintenance.made_of(renamed)
    # A folder not named as a backup (one a restore set aside) goes by its manifest alone.
    aside = renamed.rename(keyed_config.data_dir / "before-restore-20261001-000000")
    assert maintenance.made_of(aside).isoformat() == "2026-10-01T00:00:00+00:00"


def test_verifying_with_no_backup_says_there_is_none(keyed_config, master_key):
    with pytest.raises(RefuseStart, match="there is no backup in"):
        maintenance.verify_backup(keyed_config, master_key)


def test_an_interrupted_restore_carries_on_from_its_journal(store, keyed_config, master_key):
    """S15.6.8: a restore that stopped after copying in is finished by the next, into the same
    before-restore folder."""
    store.db.dispose()
    b = _folder_copy(keyed_config, "moolakata-20261001-000000")
    aside = keyed_config.data_dir / "before-restore-20261001-000000"
    aside.mkdir()
    (keyed_config.data_dir / maintenance.RESTORE_JOURNAL).write_text(
        json.dumps({"aside": aside.name, "source": b.name})
    )
    assert maintenance.restore(keyed_config, b, master_key) == aside
    assert not (keyed_config.data_dir / maintenance.RESTORE_JOURNAL).exists()
    restored = json.loads((keyed_config.data_dir / maintenance.RESTORED_MARK).read_text())
    assert restored["source"] == b.name


def test_a_pre_upgrade_copy_under_another_phrase_is_refused_by_name(store, keyed_config):
    """S15.6.8: a copy made before a migration opens with the phrase of its day, or not at all."""
    older = keyed_config.data_dir / "pre-upgrade"
    older.mkdir()
    db = older / "moolakata-before-0009-t.db"
    _tiny(db, store.keys.keys.sqlcipher_key)
    shutil.copy2(keyed_config.keyring_path, db.with_suffix(".keyring"))
    store.db.dispose()
    with pytest.raises(RefuseStart, match=f"{db.name} does not open with that phrase"):
        maintenance.restore(keyed_config, db, os.urandom(16))


def test_a_restore_onto_a_folder_with_no_keyring_asks_nothing(store, keyed_config, master_key):
    """S15.6.8: with no keyring in place there is no phrase it replaces, so nothing to ask."""
    b = maintenance.backup(keyed_config, store)
    store.db.dispose()
    keyed_config.keyring_path.unlink()
    aside = maintenance.restore(keyed_config, b, master_key, confirm=lambda q: pytest.fail(q))
    assert keyed_config.keyring_path.exists() and not (aside / "keyring").exists()


def _sealed(config, keys: master.DataKeys, name: str) -> None:
    config.receipts_dir.mkdir(parents=True, exist_ok=True)
    files.write(config.receipts_dir / f"{name}.mkr", [b"a receipt"], keys.receipts.public_key(),
                name)  # fmt: skip


def test_receipts_under_another_key_with_no_replaced_keyring_are_set_aside(
    keyed_config, master_key
):
    """S15.6.8: receipt files the restored key doesn't open, with no keyring replaced to open
    them with, are set aside rather than lost."""
    from moolakata.store import reencrypt

    _sealed(keyed_config, master.DataKeys.derive(master.new_data_key()), "lost")
    aside = keyed_config.data_dir / "before-restore-20261001-000000"
    aside.mkdir()
    assert maintenance._rewrap_restored(keyed_config, aside, master_key, None) == ["lost.mkr"]
    assert (keyed_config.data_dir / reencrypt.SET_ASIDE / "lost.mkr").exists()


def test_receipts_under_a_replaced_keyring_of_another_phrase_take_that_phrase(
    keyed_config, master_key
):
    """S15.6.8: the replaced keyring's phrase is asked for by its fingerprint; without a way to
    ask, or with a phrase that doesn't open it, the restore stops and says so."""
    from moolakata.store import reencrypt

    other, data = os.urandom(16), master.new_data_key()
    _sealed(keyed_config, master.DataKeys.derive(data), "kept")
    aside = keyed_config.data_dir / "before-restore-20261001-000000"
    aside.mkdir()
    master.write_keyring(
        aside / "keyring", master.wrap(other, data, master.now(), master.now(), ())
    )
    with pytest.raises(RefuseStart, match="its phrase is needed to re-wrap them"):
        maintenance._rewrap_restored(keyed_config, aside, master_key, None)
    with pytest.raises(RefuseStart, match="that phrase doesn't open the replaced keyring"):
        maintenance._rewrap_restored(keyed_config, aside, master_key, lambda q: os.urandom(16))
    asked = []
    assert (
        maintenance._rewrap_restored(
            keyed_config, aside, master_key, lambda q: asked.append(q) or other
        )
        == []
    )
    assert asked == [f"the replaced keyring's phrase ({master.fingerprint(other)}): "]
    target = master.DataKeys.derive(master.unlock_keys(keyed_config, master_key).data_key)
    assert reencrypt.opens(keyed_config.receipts_dir / "kept.mkr", target.receipts, "kept")


def test_the_maintenance_shell_runs_each_statement_and_shows_its_rows(
    store, keyed_config, master_key, monkeypatch, capsys
):
    """S14.7: a statement ends at its semicolon, over as many lines as it takes; a failing one
    says why and the shell goes on; Ctrl-D ends it."""
    store.db.dispose()
    lines = iter(["SELECT 1 AS one,", "NULL AS none;", "CREATE TEMP TABLE t (x);",
                  "SELECT * FROM nothing_here;"])  # fmt: skip

    def typed(prompt):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", typed)
    assert maintenance.shell(keyed_config, master_key) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[1:] == ["one | none", "1 | ", "error: no such table: nothing_here", ""]


def test_the_maintenance_shell_refuses_a_wrong_phrase_or_a_database_it_cant_open(
    store, keyed_config, master_key
):
    store.db.dispose()
    with pytest.raises(RefuseStart, match="the data key was wrapped by"):
        maintenance.shell(keyed_config, os.urandom(16))
    keyed_config.db_path.write_bytes(b"not a database at all" * 100)
    with pytest.raises(RefuseStart, match="does not open with this key"):
        maintenance.shell(keyed_config, master_key)


def test_a_rotation_says_what_each_copy_will_meet(store, keyed_config, master_key):
    """S15.7.1: a copy whose keyring can't be read is left, and one under an earlier phrase
    needs that phrase; a set-aside keyring is only ever left."""
    unread = keyed_config.backup_dir / "moolakata-20260102-000000"
    unread.mkdir(parents=True)
    (unread / "keyring").write_text("not a keyring")
    other = os.urandom(16)
    older = keyed_config.data_dir / "pre-upgrade"
    older.mkdir()
    db = older / "moolakata-before-0009-t.db"
    _tiny(db, store.keys.keys.sqlcipher_key)
    ring = master.wrap(other, store.keys.data_key, master.now(), master.now(), ())
    master.write_keyring(db.with_suffix(".keyring"), ring)
    aside_ring = keyed_config.data_dir / (copies.SET_ASIDE_RING + "20260101-000000")
    shutil.copy2(keyed_config.keyring_path, aside_ring)
    store2, outcomes = maintenance.rotate_running(keyed_config, store, os.urandom(16))
    assert outcomes == {
        unread.name: "left: its keyring cannot be read",
        db.name: f"left: needs the phrase of {master.fingerprint(other)}",
        aside_ring.name: "left",
    }
    store2.db.dispose()


# ---------- the re-encryption's journal (S15.7.2) ----------


def test_a_journal_that_cant_be_read_refuses_the_start(keyed_config):
    from moolakata.store import reencrypt as journaled

    (keyed_config.data_dir / journaled.JOURNAL).write_text("{")
    with pytest.raises(RefuseStart, match="cannot be read: set it aside and start again"):
        journaled.journal(keyed_config)
    _journal(keyed_config, {})
    assert journaled.started_at(keyed_config).isoformat() == "2026-10-01T00:00:00+00:00"
    (keyed_config.data_dir / journaled.JOURNAL).write_text(json.dumps({"steps": {}}))
    assert journaled.started_at(keyed_config) is None
    (keyed_config.data_dir / journaled.JOURNAL).unlink()
    assert journaled.started_at(keyed_config) is None


def test_a_run_that_lost_its_old_keyring_or_its_new_one_stops_and_names_the_backup(
    store, keyed_config, master_key
):
    """S15.7.2: a keyring already under the journal's new data key needs `keyring.old` to go on;
    a journal that names a new data key whose keyring is gone never makes another."""
    from moolakata.store import reencrypt as journaled

    store.db.dispose()
    ring = master.read_keyring(keyed_config.keyring_path)
    _journal(keyed_config, {"backup": "moolakata-20261001-000000", "next": ring.data_key_id})
    with pytest.raises(RefuseStart, match=r"keyring.old is missing: set reencrypt.json aside and "
                       "restore the backup moolakata-20261001-000000"):  # fmt: skip
        journaled.run(keyed_config, master_key)
    _journal(keyed_config, {"backup": None, "next": "dk-another"})
    with pytest.raises(RefuseStart, match=r"new keyring keyring.next is missing.*made before it"):
        journaled.run(keyed_config, master_key)


def test_a_run_given_another_phrase_is_refused(store, keyed_config, master_key):
    from moolakata.store import reencrypt as journaled

    store.db.dispose()
    journaled.schedule(keyed_config, {}, None, "settings")
    with pytest.raises(master.WrongPhrase, match="not this server's key"):
        journaled.run(keyed_config, os.urandom(16))
    assert journaled.pending(keyed_config)


def test_a_pending_runs_old_keyring_stays_and_its_phrase_carries_it(keyed_config, master_key):
    """S15.7.2: `keyring.old` stays while a run is pending; a `keyring.next` under this phrase
    lets it carry the run."""
    from moolakata.store import reencrypt as journaled

    journaled.schedule(keyed_config, {}, None, "settings")
    old = keyed_config.data_dir / journaled.OLD
    shutil.copy2(keyed_config.keyring_path, old)
    journaled.tidy(keyed_config)
    assert old.exists()
    shutil.copy2(keyed_config.keyring_path, journaled.next_keyring(keyed_config))
    journaled.check_phrase(keyed_config, master_key)


def test_a_new_server_with_no_database_only_changes_its_key(keyed_config, master_key):
    """S15.7.2: before the welcome made the database there is nothing to back up or rewrite."""
    from moolakata.store import reencrypt as journaled

    before = master.read_keyring(keyed_config.keyring_path).data_key_id
    done = journaled.at_once(keyed_config, master_key, {}, "host")
    assert done["backup"] is None and done["secretsSetAside"] == []
    assert master.read_keyring(keyed_config.keyring_path).data_key_id != before


def test_a_database_under_neither_key_stops_the_run(store, keyed_config, master_key, monkeypatch):
    """S15.7.2: a database already re-keyed takes no backup; one that opens under neither
    key stops the run and says so."""
    from moolakata.store import reencrypt as journaled

    store.db.dispose()
    journaled.schedule(keyed_config, {}, None, "settings")
    monkeypatch.setattr(journaled, "_opens_db", lambda config, key: False)
    with pytest.raises(RefuseStart, match="opens under neither data key"):
        journaled.run(keyed_config, master_key)
    assert journaled.journal(keyed_config)["steps"]["backup"] is None


def test_a_rotation_whose_keyring_kept_the_old_phrase_says_so(store, keyed_config, master_key):
    """S15.7.2: the run re-encrypts under the phrase given, and its report says the rotation
    didn't finish."""
    from moolakata.store import reencrypt as journaled

    store.db.dispose()
    _journal(keyed_config, {"backup": None}, why="rotation", to=master.key_id(os.urandom(16)))
    done = journaled.at_once(keyed_config, master_key, {}, "rotation")
    assert done["rotationUnfinished"] == master.fingerprint(master_key)


def test_each_copy_is_rewritten_left_or_named_by_what_its_keyring_holds(
    store, keyed_config, master_key
):
    """S15.7.2: a copy under this phrase with an earlier data key is rewritten; one under
    another phrase, or with a keyring that can't be read, is left and says why."""
    from moolakata.store import reencrypt as journaled

    older = keyed_config.data_dir / "pre-upgrade"
    older.mkdir()
    earlier, other = master.new_data_key(), os.urandom(16)
    made = {}
    for name, ring in (
        ("0001", master.wrap(master_key, earlier, master.now(), master.now(), ())),
        ("0002", master.wrap(other, earlier, master.now(), master.now(), ())),
    ):
        db = older / f"moolakata-before-{name}-t.db"
        _tiny(db, master.DataKeys.derive(earlier).sqlcipher_key)
        master.write_keyring(db.with_suffix(".keyring"), ring)
        made[name] = db.name
    unread = keyed_config.backup_dir / "moolakata-20260102-000000"
    unread.mkdir(parents=True)
    (unread / "keyring").write_text("not a keyring")
    choices = {made["0001"]: "reencrypt", made["0002"]: "reencrypt", unread.name: "reencrypt"}
    store.db.dispose()
    _journal(keyed_config, {"backup": None}, copies=choices)
    done = journaled.at_once(keyed_config, master_key, choices, "host")
    assert {k: done["copies"][k] for k in choices} == {
        made["0001"]: "re-encrypted",
        made["0002"]: f"left: needs the phrase of {master.fingerprint(other)}",
        unread.name: "left: its keyring cannot be read",
    }


def test_a_run_stopped_among_the_copies_redoes_none_already_done(
    store, keyed_config, master_key, monkeypatch
):
    """S15.7.2: each copy's outcome is journaled as it is reached; a resumed run starts at the
    next one."""
    from moolakata.store import reencrypt as journaled

    first = _folder_copy(keyed_config, "moolakata-20261001-000000")
    second = _folder_copy(keyed_config, "moolakata-20261002-000000")
    store.db.dispose()
    real, calls = journaled._copy, []

    def once(c, *a):
        calls.append(c.name)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return real(c, *a)

    monkeypatch.setattr(journaled, "_copy", once)
    _journal(keyed_config, {"backup": None}, copies={first.name: "leave", second.name: "leave"})
    with pytest.raises(KeyboardInterrupt):
        journaled.run(keyed_config, master_key)
    calls.clear()
    done = journaled.run(keyed_config, master_key)
    assert calls == [second.name]
    assert done["copies"] == {first.name: "left", second.name: "left"}


# ---------- the column types (S14.9, R1.9) ----------


@pytest.mark.parametrize(
    "kind, value, error",
    [
        ("Cents", 1.5, "money is never a float"),
        ("Dec", 1.5, "quantities are never floats"),
        ("Dec", "0.0000000000000000001", "has more than 18 places"),
        ("UtcTimestamp", "2026-10-01T00:00:00Z", "timestamps must be timezone-aware"),
        ("UtcTimestamp", dt.datetime(2026, 10, 1), "timestamps must be timezone-aware"),
        ("Day", dt.datetime(2026, 10, 1, tzinfo=dt.UTC), "dates are datetime.date"),
        ("Day", "2026-10-01", "dates are datetime.date"),
    ],
)
def test_a_column_refuses_a_value_of_the_wrong_kind(kind, value, error):
    """R1.9, S14.9: money and quantities are never floats, a quantity holds 18 places at
    most, a moment knows its time zone and a day is a date."""
    from moolakata.store import types

    with pytest.raises((TypeError, ValueError), match=error):
        getattr(types, kind)().process_bind_param(value, None)


def test_the_stores_clock_is_the_servers():
    from moolakata import clock
    from moolakata.store import types

    at = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
    clock.fix(at)
    try:
        assert types.utcnow() == at
    finally:
        clock.fix(None)
