"""Host commands' way in (requirements S13.6, S15.4.2, S15.4.7, S15.5.2): a Unix socket,
`/run/moolakata/sock`, in a 0700 directory of the server's account, where `keys unlock`,
`keys break-glass` and `db backup`, run inside the server's container, reach the running
server. It is no network listener: only the server's own account (or root) inside the
container can open it. That gives nothing new to whoever opens it: on an unlocked server they
could already read the data key from the process's memory (S15.7.1). Nothing that reaches the
listener, a forged `X-Forwarded-For` included, reaches these routes."""

import logging
import os
import stat
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from hypercorn.config import Config as HypercornConfig

from . import errors
from .config import Config, RefuseStart
from .errors import Problem
from .ui.conventions import ExactRoute, Model
from .ui.deps import server

log = logging.getLogger("moolakata.host")
router = APIRouter(prefix="/host", route_class=ExactRoute)
# The address the sign-in lockout and the log give a host command.
CALLER = "host"


class Phrase(Model):
    phrase: str


@router.get("/unlock")
def lock_state(request: Request):
    from .ui.unlock import state

    return state(server(request)).model_dump(mode="json")


@router.post("/unlock")
async def unlock(body: Phrase, request: Request):
    """`moolakata keys unlock` (S15.4.2): the same unlock as the locked screen's."""
    from .ui.unlock import try_unlock

    return (await try_unlock(server(request), body.phrase, CALLER)).model_dump(mode="json")


@router.post("/keys/break-glass")
def break_glass(request: Request):
    """`moolakata keys break-glass` (S15.5.2): a code that stands in for a lost phrase at
    Settings › Key storage › Rotate, for 15 minutes and once. Every admin is told."""
    from . import activity

    srv = server(request)
    if srv.store is None:
        raise Problem(503, "locked", "Unlock the server first: a locked server issues no code.")
    code, until = srv.break_glass.issue()
    with srv.db.tx(unscoped="host: break glass") as s:
        activity.record(
            s,
            "keys.break-glass",
            actor=None,
            via="host",
            for_admins=True,
            detail={"until": until.isoformat()},
        )
    srv.tasks.run_now("alerts")
    log.info("a break-glass code was issued, until %s", until.isoformat())
    return {"code": code, "expiresAt": until.isoformat()}


@router.post("/backup")
def backup(request: Request):
    """`moolakata db backup` against the running server (S14.6): a verified backup now, and
    the oldest beyond the number kept pruned, as the daily task does."""
    from . import activity, settings
    from .store import maintenance

    srv = server(request)
    if srv.store is None:
        raise Problem(503, "locked", "Unlock the server first.")
    with srv.maintenance_lock:
        path = maintenance.backup(srv.config, srv.store)
        with srv.db.read(unscoped="host: backup") as s:
            keep = settings.get(s, "backupCopies")
        maintenance.prune(srv.config, keep)
    with srv.db.tx(unscoped="host: backup") as s:
        activity.record(
            s, "db.backup", actor=None, via="host", for_admins=True, detail={"name": path.name}
        )
    return {"name": path.name, "path": str(path)}


def create_host_app(srv) -> FastAPI:
    app = FastAPI(title="MoolaKata host", openapi_url=None, docs_url=None, redoc_url=None)
    app.state.server = srv
    errors.install(app)
    app.include_router(router)
    return app


def prepare(config: Config) -> Path:
    """The socket's directory: made 0700 when missing, and refused when another account owns it
    or others may open it, since whoever opens the socket is trusted as the host."""
    folder = config.socket_path.parent
    try:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        st = folder.stat()
    except OSError as e:
        raise RefuseStart(
            f"the host commands' socket can't be made in {folder}: {e.strerror} (the container "
            f"needs a tmpfs there owned by its account, as compose.yaml gives it)"
        ) from None
    if st.st_uid != os.geteuid():
        raise RefuseStart(f"{folder} belongs to another account: it must be this server's own")
    if stat.S_IMODE(st.st_mode) & 0o077:
        os.chmod(folder, 0o700)
    return config.socket_path


def hypercorn_config(config: Config) -> HypercornConfig:
    hc = HypercornConfig()
    hc.bind = [f"unix:{prepare(config)}"]
    hc.umask = 0o177  # the socket itself 0600
    hc.graceful_timeout = 5
    hc.accesslog = None
    hc.errorlog = logging.getLogger("hypercorn.error")
    hc.include_server_header = False
    return hc


class NotRunning(Exception):
    """No server answers on this host's socket."""


@contextmanager
def client(config: Config, timeout: float = 30):
    """The command line's side: HTTP over the socket, never the network."""
    import httpx

    if not config.socket_path.exists():
        raise NotRunning(f"no server is running here (no socket at {config.socket_path})")
    transport = httpx.HTTPTransport(uds=str(config.socket_path))
    with httpx.Client(transport=transport, base_url="http://host", timeout=timeout) as c:
        try:
            yield c
        except httpx.TransportError as e:
            raise NotRunning(f"the server isn't answering on {config.socket_path}: {e}") from None


def detail(r) -> str:
    try:
        return r.json().get("detail") or r.text
    except ValueError:
        return r.text
