"""The server as main.py builds it at unlock: its background tasks and start-up work."""

import pytest

from moolakata import runtime
from moolakata.app import Server
from moolakata.config import RefuseStart
from moolakata.runtime import build
from moolakata.store import maintenance


def test_build_registers_every_background_task(keyed_config, master_key):
    server = Server(config=keyed_config)
    build(server, master_key)
    try:
        assert set(server.tasks.status()) == {
            "backups",
            "pruning",
            "certificate",
            "prices",
            "mail",
            "alerts",
            "alert-summaries",
            "options",
            "bitcoin",
            "links",
            "linked-copies",
            "host-events",
        }
        assert server.tasks.run_now("prices")
    finally:
        server.db.dispose()


def test_a_failure_after_the_store_opens_leaves_the_server_locked(
    keyed_config, master_key, monkeypatch
):
    """The server is locked again, not half open, and a restore's follow-up is kept for the next
    unlock."""
    (keyed_config.data_dir / maintenance.RESTORED_MARK).write_text('{"at": null}')

    def fail(*a):
        raise RuntimeError("a secret that won't open")

    monkeypatch.setattr(runtime, "check_restored", fail)
    server = Server(config=keyed_config)
    with pytest.raises(RuntimeError):
        build(server, master_key)
    assert server.store is None and not server.ready
    assert (keyed_config.data_dir / maintenance.RESTORED_MARK).exists()
    monkeypatch.undo()
    build(server, master_key)
    try:
        assert server.store is not None
        assert not (keyed_config.data_dir / maintenance.RESTORED_MARK).exists()
        assert maintenance.restore_report(keyed_config) is not None
    finally:
        server.tasks.stop()
        server.db.dispose()


def _task(server, name):
    """A registered background task's body, run once here, as the tasks run it."""
    import threading

    from moolakata.tasks import TaskContext

    runtime.register_tasks(server)
    stop = threading.Event()
    server.tasks._tasks[name].run(TaskContext(name, stop, server.tasks.limits))
    return stop


def test_the_mail_task_sends_what_waits_with_smtp_as_settings_have_it(server, monkeypatch):
    """S16.2: with emails waiting, the task sends them by Settings › Email's SMTP, stopping
    when the server does; with none, it asks nothing of SMTP."""
    from moolakata import settings

    mailer = server.services.mailer
    sent = []
    monkeypatch.setattr(mailer, "send_waiting", lambda smtp, guard, stop: sent.append((smtp, stop)))
    _task(server, "mail")
    assert sent == [], "nothing waiting"
    with server.db.tx(unscoped="test") as s:
        settings.put(s, "smtpHost", "smtp.home.lan", None)
    monkeypatch.setattr(mailer, "waiting", lambda: ["an email"])
    stop = _task(server, "mail")
    [(smtp, given)] = sent
    assert smtp.host == "smtp.home.lan" and given is stop


def test_a_phrase_checked_on_the_host_reruns_the_alerts_at_once(server, monkeypatch):
    """S15.4.7: a key.verified (or verify-failed) event from the host clears or raises its
    alert without waiting for the alerts' own run; other events wait for it."""
    asked = []
    monkeypatch.setattr(runtime.Tasks, "run_now", lambda tasks, name: asked.append(name))
    for kinds, expected in (
        ({"db.backup"}, []),
        ({"key.verified"}, ["alerts"]),
        ({"key.verify-failed", "db.backup"}, ["alerts"]),
    ):
        monkeypatch.setattr(runtime, "take_host_events", lambda srv, k=kinds: k)
        _task(server, "host-events")
        assert asked == expected, kinds
        asked.clear()


def test_relocking_stops_the_reader_and_is_safe_with_no_store(config):
    """An unlock that failed part-way: the receipt reader stops, and with no store open there
    is nothing to close."""
    stopped = []

    class Reader:
        def stop(self):
            stopped.append(True)

    server = Server(config=config)
    server.reader = Reader()
    runtime.relock(server)
    assert stopped == [True] and server.reader is None and server.store is None
    runtime.relock(server)  # nothing open: nothing to do
    assert not server.ready


def test_the_first_unlock_after_a_restore_reports_what_its_keys_cant_open(server):
    """S15.6.8: a receipt whose file the restored keys can't open, and a secret sealed under
    other keys, are each reported, by id and by where the secret was."""
    from moolakata import ids
    from moolakata.store.entities.receipts import Receipt
    from moolakata.store.entities.users import User
    from moolakata.store.repos import secrets as secret_repo

    with server.db.tx(unscoped="test") as s:
        admin = s.query(User).one()
        receipt = Receipt(
            id=ids.new_id("Rcpt"), ownerId=admin.id, fileName="r.pdf", mediaType="application/pdf",
            size=3, sha256="0" * 64, fileId="gone",
        )  # fmt: skip
        s.add(receipt)
        secret_repo.put(s, b"k" * 32, "Setting", "smtp", "password", "pw", None)
    runtime.check_restored(server, {"at": "2026-11-01T00:00:00Z", "source": "b.db"})
    report = maintenance.restore_report(server.config)
    assert report["receiptsUnopened"] == [receipt.id]
    assert report["secretsUnopened"] == ["Setting/password"]
    assert report["receiptsSetAside"] == [] and report["source"] == "b.db"


def test_no_reencryption_done_records_nothing(server):
    from moolakata.store.entities.core import Activity

    runtime.record_reencryption(server)
    with server.db.read(unscoped="test") as s:
        assert s.query(Activity).filter_by(kind="keys.reencrypted").count() == 0


def test_each_links_copy_folder_is_known_by_its_name_at_the_unlock(server):
    """S11.9.1: a link's copy folder, by its random name, is loaded for its copy's paths."""
    from moolakata import ids
    from moolakata.links import copy as linked
    from moolakata.store.entities.links import Link

    with server.db.tx(unscoped="test") as s:
        link = Link(id=ids.new_id("Link"), state="active", role="inviter", copyPublicKey="k")
        link.copyFolder = "f1a2"
        s.add(link)
    runtime.load_copy_folders(server)
    try:
        assert linked.NAMES[link.id] == "f1a2"
    finally:
        linked.NAMES.pop(link.id, None)


def test_an_unlock_while_reencrypting_or_once_open_is_refused(server, master_key):
    """S15.4.3: the phrase opens the store once per start; while a re-encryption runs, a second
    phrase is refused as one."""
    import asyncio

    with pytest.raises(runtime.AlreadyUnlocked):
        asyncio.run(runtime.unlock(server, master_key))
    server.reencrypting = object()
    with pytest.raises(runtime.Reencrypting):
        asyncio.run(runtime.unlock(server, master_key))


@pytest.mark.parametrize(
    ("error", "shown"),
    [
        (
            RefuseStart("the database is from a newer release"),
            "the database is from a newer release",
        ),
        (OSError("/data/moolakata.db: no space left"), "OSError"),
    ],
)
def test_a_reencryption_that_fails_at_the_unlock_says_why_on_the_locked_screen(
    config, monkeypatch, caplog, error, shown
):
    """S15.7.2: a refusal's own words are shown; any other failure only by its kind, its
    detail (a path) in the log; and the re-encryption is no longer running."""
    import asyncio

    from moolakata.store import reencrypt

    async def fail(*a):
        raise error

    monkeypatch.setattr(reencrypt, "pending", lambda config: True)
    monkeypatch.setattr(reencrypt, "check_phrase", lambda config, key: None)
    monkeypatch.setattr(runtime, "_open", fail)
    server = Server(config=config)
    asyncio.run(runtime.unlock(server, b"key", wait=True))
    assert server.unlock_error == shown and server.reencrypting is None
    assert f"the re-encryption at the unlock failed: {type(error).__name__}: {error}" in caplog.text


def test_a_failure_once_the_store_is_open_locks_the_server_again(config, monkeypatch):
    import asyncio

    relocked = []

    async def fail(server, seed):
        raise RuntimeError("the reader would not start")

    monkeypatch.setattr(runtime, "build", lambda server, key: None)
    monkeypatch.setattr(runtime, "_serve", fail)
    monkeypatch.setattr(runtime, "relock", lambda server: relocked.append(server))
    server = Server(config=config)
    with pytest.raises(RuntimeError, match="would not start"):
        asyncio.run(runtime._open(server, b"key", False))
    assert relocked == [server]


def test_stopping_an_unlocked_server_stops_its_tasks_and_reader_and_closes_its_store(
    keyed_config, store, monkeypatch, caplog
):
    """The server as main.py starts it: once unlocked, the first signal (on_stop) marks it not
    ready and stops its tasks and the receipt reader; when the listener ends, its database is
    closed."""
    import asyncio
    import logging

    from moolakata import listener, sandbox

    stopped = []

    class Reader:
        def stop(self):
            stopped.append("reader")

    async def serve(app, config, on_stop, host_app):
        server = app.state.server
        server.store, server.reader, server.ready = store, Reader(), True
        await on_stop()
        assert not server.ready
        stopped.append("tasks" if server.tasks._stop.is_set() else "-")

    monkeypatch.setattr(sandbox, "not_dumpable", lambda: None)  # never this test process's
    monkeypatch.setattr(listener, "run", serve)
    caplog.set_level(logging.INFO, "moolakata")
    assert asyncio.run(runtime.start(keyed_config)) == 0
    assert stopped == ["reader", "tasks"]
    assert "listening on http://" in caplog.text and "locked until" in caplog.text
    assert "stopped" in caplog.messages


def test_a_server_stopped_while_locked_or_uninitialised_has_nothing_to_stop(
    config, monkeypatch, caplog
):
    """S15.4.4: with no keyring the server starts uninitialised, the page making the key; a stop
    before any unlock ends the streams alone, and a restart asked for is answered as one."""
    import asyncio
    import logging

    from moolakata import listener, sandbox

    async def serve(app, config, on_stop, host_app):
        await on_stop()
        app.state.server.restarting = True

    monkeypatch.setattr(sandbox, "not_dumpable", lambda: None)
    monkeypatch.setattr(listener, "run", serve)
    caplog.set_level(logging.INFO, "moolakata")
    assert asyncio.run(runtime.start(config)) == runtime.RESTART
    assert "uninitialised, the page makes the key (S15.4.4)" in caplog.text


def test_the_certificate_task_loads_a_renewed_one_on_the_listeners_loop(server, monkeypatch):
    """S13.3: the daily look at the self-signed certificate hands the load to the event loop
    the listener runs on, or does it in place when there is none (a test's server)."""
    from moolakata import listener

    seen = []
    monkeypatch.setattr(listener, "renew", lambda config, call: seen.append(call))
    _task(server, "certificate")

    class Loop:
        def call_soon_threadsafe(self, f, *a):
            pass

    server.loop = Loop()
    _task(server, "certificate")
    assert seen == [None, server.loop.call_soon_threadsafe]
