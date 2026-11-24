"""The folders of files that rows name (S9.7, S11.9.6.6): what the sweep and a removal do when a
file or its folder is already gone, and a file held until its transaction ends."""

import os

from moolakata.filestore import FileStore


def test_removing_a_file_already_gone_frees_nothing(tmp_path):
    store = FileStore(tmp_path)
    (tmp_path / "a.mkr").write_bytes(b"12345")
    assert store.remove("a.mkr") == 5
    assert store.remove("a.mkr") == 0


def test_a_store_is_busy_while_an_operation_names_files_in_bulk(tmp_path):
    store = FileStore(tmp_path)
    assert not store.is_busy()
    with store.busy():
        assert store.is_busy()
        assert store.sweep(lambda: set(), (".mkr",), grace=0) == []
    assert not store.is_busy()


def test_a_sweep_of_a_folder_not_made_yet_or_of_a_file_gone_meanwhile_removes_nothing(tmp_path):
    """No receipt yet: no folder, nothing to sweep. A file that goes as the sweep reads it (a
    link to nothing stands for it here) is passed over."""
    assert FileStore(tmp_path / "receipts").sweep(lambda: set(), (".mkr",), grace=0) == []
    os.symlink(tmp_path / "nowhere.mkr", tmp_path / "gone.mkr")
    (tmp_path / "old.mkr").write_bytes(b"123")
    os.utime(tmp_path / "old.mkr", (0, 0))
    store = FileStore(tmp_path)
    assert store.sweep(lambda: set(), (".mkr",), grace=60) == [("old.mkr", 3)]


def test_a_file_held_for_a_transaction_is_let_go_once_whichever_way_it_ends(tmp_path, monkeypatch):
    """Kept from the sweep until its transaction commits or rolls back; the other ending, had
    it come too, lets nothing go twice."""
    from sqlalchemy import event

    endings = {}
    monkeypatch.setattr(
        event, "listen", lambda session, name, fn, once: endings.setdefault(name, fn)
    )
    store = FileStore(tmp_path)
    with store.writing("b.mkr"):
        store.hold_until_done(object(), "b.mkr")
        endings["after_commit"](None)
        endings["after_rollback"](None)
        assert store._writing["b.mkr"] == 1, "the block's own hold stays"
    assert "b.mkr" not in store._writing
