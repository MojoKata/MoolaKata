"""The host commands' socket (S13.6, S15.4.2, S15.4.7, S15.5.2), its side in the server and the
command line's: refused when it would be anyone's but the server account's, and saying so
when nothing answers on it."""

import dataclasses
import os
import socket

import httpx
import pytest
from fastapi.testclient import TestClient

from moolakata import host
from moolakata.app import Server
from moolakata.config import RefuseStart


def test_a_locked_server_says_so_and_makes_no_backup(keyed_config):
    """S15.4.7: `keys unlock` reads the lock's state over the socket; `db backup` against a
    locked server is refused, saying what to do first."""
    c = TestClient(host.create_host_app(Server(config=keyed_config)), base_url="http://host")
    state = c.get("/host/unlock").json()
    assert state["locked"] is True
    r = c.post("/host/backup")
    assert r.status_code == 503
    assert (r.json()["code"], r.json()["detail"]) == ("locked", "Unlock the server first.")


def test_the_sockets_folder_is_made_the_servers_own(config):
    """S13.6: made 0700 when missing, and made 0700 again when others could open it."""
    folder = config.socket_path.parent
    assert host.prepare(config) == config.socket_path
    assert folder.stat().st_mode & 0o777 == 0o700
    folder.chmod(0o755)
    host.prepare(config)
    assert folder.stat().st_mode & 0o777 == 0o700


def test_a_socket_folder_that_cant_be_made_or_is_anothers_refuses_the_start(
    config, tmp_path, monkeypatch
):
    (tmp_path / "file").write_text("not a folder")
    blocked = dataclasses.replace(config, socket_path=tmp_path / "file" / "run" / "sock")
    with pytest.raises(RefuseStart) as e:
        host.prepare(blocked)
    assert str(e.value).startswith(f"the host commands' socket can't be made in {tmp_path}/file")
    assert "(the container needs a tmpfs there owned by its account" in str(e.value)
    monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 1)
    with pytest.raises(RefuseStart, match="belongs to another account: it must be this server"):
        host.prepare(config)


def test_the_command_line_says_when_no_server_answers(config):
    """`keys unlock` and `db backup` against no server: no socket at all, or one nobody
    listens on (a server that stopped without removing it)."""
    with pytest.raises(host.NotRunning, match="no server is running here"), host.client(config):
        pass
    config.socket_path.parent.mkdir(parents=True)
    left = socket.socket(socket.AF_UNIX)
    left.bind(str(config.socket_path))
    left.close()
    with (
        pytest.raises(host.NotRunning, match="the server isn't answering on"),
        host.client(config, timeout=2) as c,
    ):
        c.get("/host/unlock")


@pytest.mark.parametrize(
    ("answer", "said"),
    [
        (
            httpx.Response(503, json={"detail": "Unlock the server first."}),
            "Unlock the server first.",
        ),
        (httpx.Response(500, json={"code": "x"}), '{"code":"x"}'),
        (httpx.Response(502, text="Bad Gateway"), "Bad Gateway"),
    ],
)
def test_a_refusal_is_told_by_its_detail_or_else_its_text(answer, said):
    assert host.detail(answer) == said
