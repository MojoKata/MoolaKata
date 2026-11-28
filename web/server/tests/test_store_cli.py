"""`moolakata db …` (requirements S14.7, S15.4.7), run in-process on a data folder: each command
asks for the phrase, says what it did, and queues what it did for Activity."""

import argparse
import contextlib
import os
from pathlib import Path

import pytest

from moolakata import host
from moolakata.config import RefuseStart
from moolakata.store import cli as db_cli
from moolakata.store import maintenance


@pytest.fixture
def stopped(store, keyed_config, master_key, monkeypatch):
    """The server stopped: its store closed, the commands pointed at its data folder and given
    its phrase as typed."""
    store.db.dispose()
    monkeypatch.setattr(db_cli, "configured", lambda _: keyed_config)
    monkeypatch.setattr(db_cli, "read_phrase", lambda prompt=None: master_key)
    return keyed_config


def _args(**flags) -> argparse.Namespace:
    return argparse.Namespace(config=None, **flags)


def _queued(config) -> list[tuple[str, dict]]:
    taken = maintenance.take_host_events(config)
    maintenance.host_events_taken(config)
    return [(e["kind"], e["detail"]) for e in taken]


class _Answer:
    def __init__(self, status: int, body: dict) -> None:
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self) -> dict:
        return self._body


def _running(monkeypatch, answer: _Answer) -> list[str]:
    """A server running on the host's socket, answering a backup with `answer`."""
    asked: list[str] = []

    class Client:
        def post(self, path):
            asked.append(path)
            return answer

    @contextlib.contextmanager
    def client(config, timeout=30):
        yield Client()

    monkeypatch.setattr(host, "client", client)
    return asked


def test_db_backup_with_the_server_stopped_makes_one_read_only_and_says_where(stopped, capsys):
    """S15.4.7: no server on the socket, so the backup is made here: the data folder locked,
    the database opened read only, the copies pruned to the setting, and Activity told."""
    assert db_cli._backup(_args()) == 0
    made = maintenance.backups(stopped)
    assert len(made) == 1
    assert capsys.readouterr().out.strip() == str(made[0])
    assert _queued(stopped) == [("db.backup", {"name": made[0].name})]


def test_db_backup_with_the_data_folder_in_use_is_refused(stopped):
    """S15.4.7: a running server holds the folder; a stopped one's backup can't be made beside
    it, and says how to make it through the server."""
    held = maintenance.lock_data_dir(stopped, "a test holds it")
    try:
        with pytest.raises(RefuseStart, match="the running server makes it"):
            db_cli._backup(_args())
    finally:
        held.close()
    assert maintenance.backups(stopped) == []


def test_db_backup_with_the_server_running_asks_it_over_its_socket(stopped, monkeypatch, capsys):
    """S15.4.7: the running server makes the backup; the command prints where it went."""
    asked = _running(monkeypatch, _Answer(200, {"path": "/backups/moolakata-20261001-000000"}))
    assert db_cli._backup(_args()) == 0
    assert asked == ["/host/backup"]
    assert capsys.readouterr().out.strip() == "/backups/moolakata-20261001-000000"
    assert maintenance.backups(stopped) == []


def test_db_backup_the_running_server_refuses_says_why(stopped, monkeypatch):
    _running(monkeypatch, _Answer(409, {"detail": "a backup is being made"}))
    with pytest.raises(RefuseStart, match="the server refused the backup: a backup is being made"):
        db_cli._backup(_args())


def test_db_verify_backup_names_the_newest_or_the_one_given(stopped, capsys):
    """S14.7: the newest backup by default, or the folder named; it says when it was made."""
    store = maintenance.open_store(stopped, db_cli.read_phrase(), read_only=True)
    first = maintenance.backup(stopped, store)
    store.db.dispose()
    assert db_cli._verify_backup(_args(path=None)) == 0
    made = maintenance.made_of(first)
    assert capsys.readouterr().out.strip() == (
        f"{first.name}, made {made:%Y-%m-%d %H:%M:%S} UTC: whole, and opens with that phrase"
    )
    assert db_cli._verify_backup(_args(path=str(first))) == 0
    assert _queued(stopped) == [("db.verify-backup", {"name": first.name})] * 2


def test_db_restore_asks_its_questions_on_the_terminal(stopped, monkeypatch, capsys):
    """S15.6.8: the restore's question is answered y or n, and the replaced keyring's phrase is
    typed when it is asked for; what it did is printed and queued."""
    seen: dict = {}

    def restore(config, path, master_key, confirm, ask):
        seen["answers"] = [confirm("Go on?"), confirm("Again?")]
        seen["phrase"] = ask("the replaced keyring's phrase: ")
        return config.data_dir / "before-restore-20261001-000000"

    answers = iter(["y", " NO "])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    monkeypatch.setattr(maintenance, "restore", restore)
    assert db_cli._restore(_args(path="/backups/moolakata-20261001-000000")) == 0
    assert seen["answers"] == [True, False]
    assert seen["phrase"] == db_cli.read_phrase()
    out = capsys.readouterr().out
    assert "restored moolakata-20261001-000000; what it replaced is in" in out
    assert _queued(stopped) == [
        ("db.restore", {"name": "moolakata-20261001-000000",
                        "aside": "before-restore-20261001-000000"}),
    ]  # fmt: skip


@pytest.mark.parametrize("pid, answer", [(1, "yes"), (4242, None)])
def test_db_shell_goes_on_when_told_or_when_not_the_containers_first(
    stopped, monkeypatch, pid, answer
):
    """S14.7: under `docker compose exec` it opens at once; as a one-off container's first
    process it opens once told to. Activity hears of it either way."""
    opened = []
    monkeypatch.setattr(os, "getpid", lambda: pid)
    monkeypatch.setattr("builtins.input", lambda _: answer)
    monkeypatch.setattr(maintenance, "shell", lambda config, key: opened.append(key) or 0)
    assert db_cli._shell(_args()) == 0
    assert opened == [db_cli.read_phrase()]
    assert _queued(stopped) == [("db.shell", {})]


def test_the_db_commands_are_registered_with_their_arguments():
    parser = argparse.ArgumentParser()
    db_cli.register(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["db", "verify-backup"])
    assert (args.func, args.path) == (db_cli._verify_backup, None)
    args = parser.parse_args(["db", "restore", "/b/moolakata-20261001-000000"])
    assert (args.func, Path(args.path).name) == (db_cli._restore, "moolakata-20261001-000000")
    assert parser.parse_args(["db", "shell"]).func is db_cli._shell
    assert parser.parse_args(["db", "backup"]).func is db_cli._backup
