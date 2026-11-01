"""The server with no network (requirements S17.2.1, S13.5): run by `web/dev.sh audit` inside
`unshare -U -n`, a network namespace with no interface, so nothing can reach out. The server
starts in-process, reads a receipt in its worker, refreshes prices from the stubs, makes a
backup and runs every task; any socket opened to a non-loopback address, by Python or by
native code, fails the test. Deselected from an ordinary run (`-m audit`)."""

import socket
from pathlib import Path

import pytest

pytestmark = pytest.mark.audit


def _peers() -> set[str]:
    out = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6", "/proc/net/udp", "/proc/net/udp6"):
        try:
            lines = Path(table).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            remote = line.split()[2]
            host, port = remote.split(":")
            if int(port, 16) == 0 or host.endswith("0100007F") or host.endswith("00000000"):
                continue
            if host == "00000000000000000000000001000000":  # ::1
                continue
            out.add(f"{host}:{int(port, 16)}")
    return out


@pytest.fixture
def watched(monkeypatch):
    """Every connect a Python socket attempts, recorded; a non-loopback one fails."""
    attempts: list[str] = []
    real = socket.socket.connect

    def connect(self, address, *a, **k):
        if isinstance(address, tuple):
            host = str(address[0])
            if not host.startswith(("127.", "::1", "localhost")):
                attempts.append(f"{host}:{address[1]}")
        return real(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", connect)
    return attempts


def test_nothing_leaves_the_server_with_no_network(server, admin_client, watched, tmp_path):
    from moolakata import alerts, settings
    from moolakata.prices import refresh
    from moolakata.store import maintenance

    with server.db.tx(unscoped="test") as s:
        settings.put(s, "readReceipts", True, None)
    # A receipt read in the worker process (native OCR), a price refresh (the stub source
    # only), a backup, and every alert check.
    from test_reading import _png, draw

    from moolakata.receipts.reading import Worker

    w = Worker()
    try:
        status, lines, _, _ = w.read(_png(draw(["KROGER", "TOTAL 12.34"])), "image/png")
    finally:
        w.stop()
    assert status == "ok" and lines
    from moolakata.dev import devmode

    devmode.enable_stub_prices(server)
    from moolakata.tasks import TaskContext

    refresh.refresh(server, TaskContext("prices", __import__("threading").Event(), None))
    maintenance.backup(server.config, server.store)
    alerts.evaluate(server)
    assert admin_client.get("/ui/api/dashboard").status_code == 200
    assert watched == [], f"a socket was opened to {watched}"
    assert _peers() == set(), f"native code reached {_peers()}"
