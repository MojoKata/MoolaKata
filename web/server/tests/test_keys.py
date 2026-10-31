import os

import pytest

from moolakata.config import RefuseStart
from moolakata.keys import cli, master, phrase
from moolakata.store import maintenance


def test_phrase_matches_bip39_vectors():
    assert phrase.to_words(bytes(16)) == ["abandon"] * 11 + ["about"]
    assert " ".join(phrase.to_words(bytes([0x7F] * 16))) == (
        "legal winner thank year wave sausage worth useful legal winner thank yellow"
    )
    assert " ".join(phrase.to_words(bytes([0x80] * 16))) == (
        "letter advice cage absurd amount doctor acoustic avoid letter advice cage above"
    )


def test_phrase_reads_back_with_four_letter_prefixes_and_any_case():
    key = os.urandom(16)
    words = phrase.to_words(key)
    assert phrase.from_words(" ".join(words).upper()) == key
    assert phrase.from_words([w[:4] for w in words]) == key


def test_phrase_catches_mistakes():
    words = phrase.to_words(bytes(16))
    with pytest.raises(phrase.PhraseError, match="12 words"):
        phrase.from_words(words[:11])
    with pytest.raises(phrase.PhraseError, match="not in the word list"):
        phrase.from_words(["zzzz", *words[1:]])
    with pytest.raises(phrase.PhraseError, match="do not check out"):
        phrase.from_words(["zoo", *words[1:]])


def test_fingerprint_form():
    fp = master.fingerprint(bytes(16))
    assert fp.startswith("mk-") and "…" in fp and len(fp) == 12
    assert master.key_id(bytes(16)) == master.key_id(bytes(16))


def test_a_keyring_is_all_that_is_written_and_only_once(keyed_config, master_key, tmp_path):
    """S15.4: the master key is the phrase; nothing but the wrapped data key is written."""
    ring = keyed_config.keyring_path
    assert ring.exists() and os.stat(ring).st_mode & 0o777 == 0o600
    written = {p.name for p in tmp_path.rglob("*") if p.is_file()}
    assert written == {"keyring"}
    assert master_key.hex() not in ring.read_text()
    assert " ".join(phrase.to_words(master_key)) not in ring.read_text()
    with pytest.raises(RefuseStart, match="already exists"):
        master.create_keyring(keyed_config, os.urandom(16))
    assert master.unlock_keys(keyed_config, master_key).master_id == master.key_id(master_key)
    assert cli.fingerprint_of(keyed_config) == master.fingerprint(master_key)


def test_a_wrong_phrase_does_not_unlock_the_keys(keyed_config):
    with pytest.raises(master.WrongPhrase, match="wrapped by"):
        master.unlock_keys(keyed_config, os.urandom(16))


def test_verify_compares_without_changing_anything(keyed_config, master_key):
    seen = []
    before = keyed_config.keyring_path.read_bytes()
    assert cli.verify(
        keyed_config,
        ask=lambda _: " ".join(phrase.to_words(master_key)),
        say=lambda _: None,
        record=lambda kid, ok: seen.append(ok),
    )
    assert not cli.verify(
        keyed_config,
        ask=lambda _: " ".join(phrase.to_words(bytes(16))),
        say=lambda _: None,
        record=lambda kid, ok: seen.append(ok),
    )
    assert not cli.verify(keyed_config, ask=lambda _: "three words only", say=lambda _: None)
    assert seen == [True, False] and keyed_config.keyring_path.read_bytes() == before


def test_host_commands_queue_what_they_did_for_activity(keyed_config):
    """A one-off container has no phrase to open the database with: what it did waits in a
    queue the server takes at its next unlock (S15.7.4)."""
    maintenance.queue_host_event(keyed_config, "key.verified", {"fingerprint": "mk-1"})
    maintenance.queue_host_event(keyed_config, "key.rotated", {"from": "mk-1", "to": "mk-2"})
    queued = keyed_config.data_dir / maintenance.HOST_EVENTS
    assert os.stat(queued).st_mode & 0o777 == 0o600
    taken = maintenance.take_host_events(keyed_config)
    assert [e["kind"] for e in taken] == ["key.verified", "key.rotated"]
    assert taken[1]["detail"] == {"from": "mk-1", "to": "mk-2"} and taken[0]["at"]
    assert not queued.exists()
    # Until they are recorded the taken events stay, and are taken again (CR3-355); a line
    # appended meanwhile starts a new queue (CR3-305).
    maintenance.queue_host_event(keyed_config, "db.backup", {"name": "b"})
    assert [e["kind"] for e in maintenance.take_host_events(keyed_config)] == [
        "key.verified",
        "key.rotated",
    ]
    maintenance.host_events_taken(keyed_config)
    assert [e["kind"] for e in maintenance.take_host_events(keyed_config)] == ["db.backup"]
    maintenance.host_events_taken(keyed_config)
    assert maintenance.take_host_events(keyed_config) == []


def test_rotate_through_the_running_server_needs_no_old_phrase(store, keyed_config, master_key):
    """S15.7.1: the running server holds the data key, so a lost phrase can be replaced while
    it is up; the keyring records the old key."""
    from moolakata.store import reencrypt as journaled

    new_key = os.urandom(16)
    store2, outcomes = maintenance.rotate_running(keyed_config, store, new_key)
    assert outcomes == {}
    assert journaled.journal(keyed_config)["why"] == "rotation", "it re-encrypts at the unlock"
    assert store2.keys.master_id == master.key_id(new_key) and store2.db is store.db
    ring = master.read_keyring(keyed_config.keyring_path)
    assert [p.master_id for p in ring.previous] == [master.key_id(master_key)]
    assert master.unlock_keys(keyed_config, new_key).keys.database == store.keys.keys.database
    with pytest.raises(master.WrongPhrase):
        master.unlock_keys(keyed_config, master_key)
    with pytest.raises(RefuseStart, match="re-encryption is pending"):
        maintenance.rotate_running(keyed_config, store2, os.urandom(16))


def test_reencrypt_offline_asks_each_copy_its_choice():
    """`keys reencrypt` with the server stopped (S15.7.2): Enter re-encrypts, 'd' deletes, 'l'
    leaves."""
    answers = iter(["", "d", "l"])
    found = [
        {"name": n, "kind": "backup", "made": "2026-10-01T00:00:00", "bytes": 0, "opens": "current"}
        for n in ("a", "b", "c")
    ]
    assert cli.ask_copies(found, ask=lambda _: next(answers), say=lambda _: None) == {
        "a": "reencrypt",
        "b": "delete",
        "c": "leave",
    }


def test_a_break_glass_code_works_once_for_fifteen_minutes(monkeypatch):
    """S15.5.2: the code stands in for a lost phrase once; typed any case, with or without its
    dashes; a new one replaces the last; it expires."""
    import time

    from moolakata.keys import breakglass

    bg = breakglass.BreakGlass()
    assert not bg.use("BG-0000-0000")
    code, _ = bg.issue()
    assert code.startswith("BG-") and len(code) == 12
    assert not bg.use("BG-AAAA-AAAA")
    assert bg.use(code.lower().replace("-", " "))
    assert not bg.use(code), "used once"
    first, _ = bg.issue()
    second, _ = bg.issue()
    assert not bg.use(first) and bg.use(second)
    late, _ = bg.issue()
    now = time.monotonic()
    monkeypatch.setattr(breakglass.time, "monotonic", lambda: now + breakglass.LIFE + 1)
    assert not bg.use(late)


def test_db_shell_under_run_asks_before_it_shows_anything(keyed_config, monkeypatch):
    """CR3-369: as its container's first process, Docker's log keeps what it prints."""
    import argparse

    from moolakata.store import cli as db_cli

    monkeypatch.setattr(db_cli, "configured", lambda _: keyed_config)
    monkeypatch.setattr(os, "getpid", lambda: 1)
    monkeypatch.setattr("builtins.input", lambda _: "n")
    monkeypatch.setattr(db_cli, "read_phrase", lambda: pytest.fail("asked for the phrase"))
    assert db_cli._shell(argparse.Namespace(config=None)) == 1
