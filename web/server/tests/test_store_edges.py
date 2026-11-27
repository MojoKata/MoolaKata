"""The store's machinery at its edges (requirements S14, S15.6, S15.7): the copies on the host,
backups, restores and re-encryption, in the cases the main tests (test_store.py) don't reach."""

import datetime as dt
import json
import os
import shutil

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
