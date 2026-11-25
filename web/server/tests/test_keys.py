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
    # Until they are recorded the taken events stay, and are taken again; a line
    # appended meanwhile starts a new queue.
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
    """As its container's first process, Docker's log keeps what it prints."""
    import argparse

    from moolakata.store import cli as db_cli

    monkeypatch.setattr(db_cli, "configured", lambda _: keyed_config)
    monkeypatch.setattr(os, "getpid", lambda: 1)
    monkeypatch.setattr("builtins.input", lambda _: "n")
    monkeypatch.setattr(db_cli, "read_phrase", lambda: pytest.fail("asked for the phrase"))
    assert db_cli._shell(argparse.Namespace(config=None)) == 1


# ---------- the `keys` commands, run in-process on a data folder (S15.4, S15.6, S15.7) ----------


def _args(config, tmp_path, **flags):
    """The command line's arguments, with --config naming a file for this data folder."""
    import argparse

    path = tmp_path / "moolakata.toml"
    path.write_text(
        f'[server]\nname = "test"\n[paths]\ndata = "{config.data_dir}"\n'
        f'backups = "{config.backup_dir}"\nsocket = "{config.socket_path}"\n'
    )
    return argparse.Namespace(config=str(path), **flags)


def _queued(config) -> list[tuple[str, dict]]:
    taken = maintenance.take_host_events(config)
    maintenance.host_events_taken(config)
    return [(e["kind"], e["detail"]) for e in taken]


def _a_copy(config):
    """A backup on the host as the copies' list finds it: its keyring is all a choice needs."""
    import shutil

    copy = config.backup_dir / "moolakata-20261001-000000"
    copy.mkdir(parents=True)
    shutil.copy(config.keyring_path, copy / "keyring")
    return copy


def _typed(monkeypatch, words: str) -> None:
    """What is typed at the hidden prompt."""
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: words)


def test_keys_fingerprint_prints_it_and_queues_it(keyed_config, master_key, tmp_path, capsys):
    assert cli._fingerprint_cmd(_args(keyed_config, tmp_path)) == 0
    fp = master.fingerprint(master_key)
    assert capsys.readouterr().out == fp + "\n"
    assert _queued(keyed_config) == [("key.fingerprint-shown", {"fingerprint": fp})]


def test_keys_verify_says_whether_the_phrase_matches(
    keyed_config, master_key, tmp_path, monkeypatch, capsys
):
    args, fp = _args(keyed_config, tmp_path), master.fingerprint(master_key)
    _typed(monkeypatch, " ".join(phrase.to_words(master_key)))
    assert cli._verify_cmd(args) == 0
    assert capsys.readouterr().out == f"match: the phrase is the key {fp}\n"
    other = os.urandom(16)
    _typed(monkeypatch, " ".join(phrase.to_words(other)))
    assert cli._verify_cmd(args) == 1
    assert capsys.readouterr().out == (
        f"no match: these words are {master.fingerprint(other)}, not this server's key {fp}\n"
    )
    _typed(monkeypatch, "not a phrase")
    assert cli._verify_cmd(args) == 1
    assert capsys.readouterr().out.startswith("not a valid phrase: ")
    assert _queued(keyed_config) == [
        ("key.verified", {"fingerprint": fp}),
        ("key.verify-failed", {"fingerprint": fp}),
    ], "a phrase that isn't one names no key"
    said = []
    assert cli.verify(  # with nothing to record it to
        keyed_config, ask=lambda _: " ".join(phrase.to_words(master_key)), say=said.append
    )
    assert said == [f"match: the phrase is the key {fp}"]


def test_keys_unlock_and_break_glass_need_a_running_server(
    keyed_config, master_key, tmp_path, monkeypatch, capsys
):
    args = _args(keyed_config, tmp_path)
    _typed(monkeypatch, " ".join(phrase.to_words(master_key)))
    assert cli._unlock_cmd(args) == 1
    no_socket = f"refused: no server is running here (no socket at {keyed_config.socket_path})"
    assert capsys.readouterr().out == no_socket + "\n"
    assert _queued(keyed_config) == [("key.unlock-refused", {})]
    assert cli._break_glass_cmd(args) == 1
    assert capsys.readouterr().out == no_socket + "\n"
    assert _queued(keyed_config) == [], "the server records a break-glass code itself"


class _Answer:
    def __init__(self, status: int, body):
        self.status_code, self._body = status, body
        self.text = body if isinstance(body, str) else ""

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("not JSON")
        return self._body


def _host(monkeypatch, *answers):
    """The running server's socket, answering in turn; what was asked is kept."""
    from contextlib import contextmanager

    from moolakata import host

    asked, left = [], list(answers)

    class Client:
        def post(self, path, json=None):
            asked.append(("POST", path, json))
            return left.pop(0)

        def get(self, path):
            asked.append(("GET", path, None))
            return left.pop(0)

    @contextmanager
    def client(config, timeout=30):
        yield Client()

    monkeypatch.setattr(host, "client", client)
    return asked


def test_keys_unlock_and_break_glass_say_why_the_server_refused(keyed_config, monkeypatch):
    words = " ".join(phrase.to_words(os.urandom(16)))
    said = []
    _host(monkeypatch, _Answer(403, {"detail": "Those words are not this server's key."}))
    assert cli.unlock(keyed_config, ask=lambda _: words, say=said.append) == 1
    _host(monkeypatch, _Answer(503, "Service Unavailable"))
    assert cli.break_glass(keyed_config, say=said.append) == 1
    assert said == [
        "refused: Those words are not this server's key.",
        "refused: Service Unavailable",
    ]


def test_keys_unlock_hands_over_the_phrase_and_queues_nothing_itself(
    keyed_config, master_key, tmp_path, monkeypatch, capsys
):
    """The server records an unlock however it came (S15.4.7): the command adds nothing."""
    _typed(monkeypatch, " ".join(phrase.to_words(master_key)))
    _host(monkeypatch, _Answer(200, {"locked": False, "fingerprint": "mk-here"}))
    assert cli._unlock_cmd(_args(keyed_config, tmp_path)) == 0
    assert capsys.readouterr().out == "unlocked: mk-here\n"
    assert _queued(keyed_config) == []


def test_keys_unlock_follows_a_reencryption_to_its_end(keyed_config, master_key, monkeypatch):
    """S15.7.2: a re-encryption runs before the server serves; the command shows each stage
    and each hundredth of its progress once, and ends with how it ended."""
    import time

    monkeypatch.setattr(time, "sleep", lambda s: None)
    words = " ".join(phrase.to_words(master_key))

    def going(stage, done=0, total=0):
        return _Answer(200, {"reencrypting": {"stage": stage, "done": done, "total": total}})

    asked = _host(
        monkeypatch,
        going("database"),
        going("database"),  # no news: nothing said
        going("receipts", 120, 400),
        going("receipts", 150, 400),  # the same hundredth
        _Answer(200, {"locked": False, "fingerprint": "mk-new"}),
    )
    said = []
    assert cli.unlock(keyed_config, ask=lambda _: words, say=said.append) == 0
    assert said == [
        "the phrase opened the keyring: re-encrypting under a new data key first",
        "  database",
        "  receipts 120 of 400",
        "unlocked: mk-new",
    ]
    assert asked[0] == ("POST", "/host/unlock", {"phrase": words})
    assert {a[:2] for a in asked[1:]} == {("GET", "/host/unlock")}
    said.clear()
    _host(monkeypatch, going("database"), _Answer(200, {"locked": True, "error": "disk full"}))
    assert cli.unlock(keyed_config, ask=lambda _: words, say=said.append) == 1
    assert said[-1] == "refused: disk full"
    _host(monkeypatch, going("database"), _Answer(200, {"locked": True}))
    assert cli.unlock(keyed_config, ask=lambda _: words, say=said.append) == 1
    assert said[-1] == "refused: the re-encryption did not finish"


def test_keys_reencrypt_with_the_server_stopped(
    store, keyed_config, master_key, tmp_path, monkeypatch, capsys
):
    """`moolakata keys reencrypt` (S15.7.2): the phrase typed, each copy left, deleted or
    re-encrypted as the flag says, a receipt file under neither key set aside, and what it
    did queued for Activity."""
    copy = _a_copy(keyed_config)
    store.db.dispose()
    keyed_config.receipts_dir.mkdir(parents=True, exist_ok=True)
    (keyed_config.receipts_dir / "Rcpt_x.mkr").write_bytes(b"MKR1 not a receipt's file")
    before = keyed_config.keyring_path.read_text()
    _typed(monkeypatch, " ".join(phrase.to_words(master_key)))
    flags = {"reencrypt_all": False, "delete_old": False, "leave_all": True}
    assert cli._reencrypt_cmd(_args(keyed_config, tmp_path, **flags)) == 0
    lines = capsys.readouterr().out.splitlines()
    heading = "1 copies on this host (the host's own snapshots and backups are not here):"
    assert lines[:5] == [
        "",
        heading,
        "Re-encrypted under a new data key.",
        "  receipt file set aside, opening under neither key: Rcpt_x.mkr",
        f"  {copy.name}: left",
    ]
    # The backup the run makes first is re-encrypted with the rest (S15.7.2).
    (made,) = [p.name for p in maintenance.backups(keyed_config) if p != copy]
    assert lines[5:] == [f"  {made}: re-encrypted"]
    assert keyed_config.keyring_path.read_text() != before and copy.exists()
    ((kind, detail),) = _queued(keyed_config)
    assert kind == "keys.reencrypted"
    assert detail == {
        "why": "host",
        "receiptsSetAside": 1,
        "secretsSetAside": 0,
        "copies": {copy.name: "left", made: "re-encrypted"},
    }


def test_keys_reencrypt_asks_for_the_right_phrase_and_each_copys_choice(
    keyed_config, master_key, monkeypatch
):
    from moolakata.store import reencrypt

    copy = _a_copy(keyed_config)
    run = []
    monkeypatch.setattr(
        reencrypt, "at_once", lambda *a: run.append(a[2:]) or {"copies": {copy.name: "deleted"}}
    )
    with pytest.raises(RefuseStart, match="not a valid phrase: "):
        cli.reencrypt_offline(keyed_config, ask_hidden=lambda _: "three words only")
    other = " ".join(phrase.to_words(os.urandom(16)))
    with pytest.raises(RefuseStart, match="wrapped by"):
        cli.reencrypt_offline(keyed_config, ask_hidden=lambda _: other)
    said, prompts = [], []
    done = cli.reencrypt_offline(
        keyed_config,
        ask=lambda p: prompts.append(p) or "d",
        say=said.append,
        ask_hidden=lambda _: " ".join(phrase.to_words(master_key)),
    )
    assert prompts == ["    [R]e-encrypt, [d]elete or [l]eave (R): "]
    assert said[0] == "\n1 copies on this host (the host's own snapshots and backups are not here):"
    assert said[1].startswith(f"  {copy.name} (backup, ")
    assert said[1].endswith(": can be re-encrypted")
    assert run == [({copy.name: "delete"}, "host")]
    assert said[2:] == ["Re-encrypted under a new data key.", f"  {copy.name}: deleted"]
    assert done == {"copies": {copy.name: "deleted"}}
    # One already scheduled runs with the choices made then, asking none.
    reencrypt.schedule(keyed_config, {copy.name: "leave"}, None, "settings")
    prompts.clear()
    cli.reencrypt_offline(
        keyed_config,
        ask=prompts.append,
        say=lambda _: None,
        ask_hidden=lambda _: " ".join(phrase.to_words(master_key)),
    )
    assert prompts == [] and run[-1] == ({}, "host")


def test_each_copy_is_described_by_how_it_opens():
    """The copies' list (S15.7.1): none asks nothing; `--…-all` answers for each unasked; an
    unknown answer re-encrypts, the default."""
    said = []
    assert cli.ask_copies([], ask=None, say=said.append) == {}
    assert said == []
    found = [
        {"name": n, "kind": "backup", "made": "2026-10-01T00:00:00", "bytes": 3 << 20, "opens": o}
        for n, o in (("a", "phrase"), ("b", "previous"), ("c", "unknown"))
    ]
    found[1]["masterKey"] = "mk-old"
    every = cli.ask_copies(found, ask=None, say=said.append, all_="leave")
    assert every == dict.fromkeys("abc", "leave")
    assert len(said) == 1, "the heading alone"
    said.clear()
    asked = cli.ask_copies(found, ask=lambda _: "x", say=said.append)
    assert asked == dict.fromkeys("abc", "reencrypt")
    assert said[1:] == [
        "  a (backup, 2026-10-01, 3 MB): under an earlier data key, this phrase: can be "
        "re-encrypted",
        "  b (backup, 2026-10-01, 3 MB): under an earlier phrase (mk-old): left or deleted",
        "  c (backup, 2026-10-01, 3 MB): its keyring cannot be read",
    ]


# ---------- the keyring, the phrase and the welcome's offers at their edges (S15.4) ----------


def test_a_keyring_that_isnt_one_refuses_the_start(keyed_config):
    path = keyed_config.keyring_path
    for text, why in (
        ('{"format": "something else"}', "not a MoolaKata keyring"),
        ("{not json", "Expecting property name"),
        ('{"format": "' + master.KEYRING_FORMAT + '"}', "'masterKeyId'"),
    ):
        path.write_text(text)
        with pytest.raises(RefuseStart, match=f"the keyring {path} cannot be read: ") as e:
            master.read_keyring(path)
        assert why in str(e.value), text


def test_a_keyring_changed_on_disk_does_not_unwrap(keyed_config, master_key):
    """The right phrase over a wrapped key that was changed: refused, never a wrong key."""
    import dataclasses

    ring = master.read_keyring(keyed_config.keyring_path)
    flipped = bytes([ring.wrapped[0] ^ 1]) + ring.wrapped[1:]
    with pytest.raises(ValueError, match="the master key does not unwrap the data key"):
        master.unwrap(master_key, dataclasses.replace(ring, wrapped=flipped))


def test_a_keyring_written_for_the_servers_account_is_given_to_it(keyed_config, monkeypatch):
    """Written by a one-off container as root, it is handed to the server's account."""
    given = []
    monkeypatch.setattr(master.os, "chown", lambda p, u, g: given.append((p.name, u, g)))
    ring = master.read_keyring(keyed_config.keyring_path)
    master.write_keyring(keyed_config.keyring_path, ring, owner=cli.SERVER_UID)
    assert given == [(keyed_config.keyring_path.name + ".new", 10001, 10001)]
    assert master.read_keyring(keyed_config.keyring_path) == ring


def test_a_phrase_is_of_128_bits_from_the_shipped_list_only(monkeypatch):
    with pytest.raises(ValueError, match="a recovery phrase holds exactly 128 bits"):
        phrase.to_words(bytes(15))
    monkeypatch.setattr(phrase, "WORDS_SHA256", "0" * 64)
    phrase.wordlist.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="the shipped BIP39 word list has been changed"):
            phrase.wordlist()
    finally:
        monkeypatch.undo()
        phrase.wordlist.cache_clear()
    assert len(phrase.wordlist()) == 2048
