"""The server as main.py builds it at unlock: its background tasks and start-up work."""

import pytest

from moolakata import runtime
from moolakata.app import Server
from moolakata.runtime import build
from moolakata.store import maintenance


def test_build_registers_every_background_task(keyed_config, master_key):
    server = Server(config=keyed_config)
    build(server, master_key)
    try:
        assert set(server.tasks.status()) == {
            "backups",
            "pruning",
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
    """CR3-298: the server is locked again, not half open, and a restore's follow-up is kept
    for the next unlock."""
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
