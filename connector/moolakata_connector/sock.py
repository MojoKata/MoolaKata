"""The admin's way in (requirements S18.2.2, S18.3.2): a Unix socket inside the container,
where `moolakata-connector unlock`, `pair`, `connect`, `unpair`, `reset` and `status` hand
their words to the running connector. It listens on no network port; nothing outside the
container reaches the socket."""

import json
import os
import socket
import threading
from pathlib import Path

from .client import ServerError
from .vault import VaultError


def serve(core, path: Path) -> threading.Thread:
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(str(path))
    os.chmod(path, 0o600)
    s.listen(4)

    def loop() -> None:
        while True:
            conn, _ = s.accept()
            with conn:
                try:
                    request = json.loads(_recv(conn))
                    answer = handle(core, request)
                except Exception as e:
                    answer = {"error": f"{type(e).__name__}: {e}"}
                conn.sendall(json.dumps(answer).encode() + b"\n")

    t = threading.Thread(target=loop, name="connector-socket", daemon=True)
    t.start()
    return t


def _recv(conn) -> bytes:
    buf = b""
    while not buf.endswith(b"\n"):
        piece = conn.recv(65536)
        if not piece:
            break
        buf += piece
    return buf


def handle(core, request: dict) -> dict:
    """What each command does in the running connector; the words and credentials never go
    anywhere but the vault."""
    what = request.get("command")
    try:
        if what == "status":
            return core.status()
        if what == "unlock":
            core.unlock(request.get("words", ""))
            return {"ok": True, "locked": False}
        if what == "lock":
            core.lock()
            return {"ok": True, "locked": True}
        if what == "pair":
            return {"ok": True, "fingerprint": core.pair(request.get("code", ""))}
        if what == "unpair":
            return {"ok": True, "cleared": core.unpair(request.get("words") or None)}
        if what == "goes-to":
            return {"ok": True, **core.goes_to(request["id"])}
        if what == "connect":
            if "host" not in request:
                return {"error": "confirm the host first: moolakata-connector connect <id>"}
            core.connect(request["id"], request.get("credentials") or {}, request["host"])
            return {"ok": True}
        if what == "reset":
            fingerprint, told = core.reset(request.get("words", ""))
            return {"ok": True, "fingerprint": fingerprint, "told": told}
    except (VaultError, ServerError) as e:
        return {"error": str(e)}
    return {"error": f"unknown command {what!r}"}


def ask(path: Path, request: dict) -> dict:
    """The command line's side: one request, one answer."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
        try:
            c.connect(str(path))
        except OSError:
            raise SystemExit(
                f"the connector isn't running (no socket at {path}); start it first"
            ) from None
        c.sendall(json.dumps(request).encode() + b"\n")
        return json.loads(_recv(c))
