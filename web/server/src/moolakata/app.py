"""The ASGI application: routes, middleware and the server's run-time state."""

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from . import errors, middleware, net, paths, ratelimit, settings, static
from .auth.users import Services
from .config import Config
from .events import STREAM_SECONDS, Broker
from .jobs import Jobs
from .keys.welcome import Phrases
from .links.copy import Copies
from .links.signing import Nonces
from .mail import Mailer
from .store.maintenance import Store
from .tasks import Tasks
from .ui.conventions import Idempotency

log = logging.getLogger("moolakata")


@dataclass
class Server:
    """Everything a request may reach, built once at start (main.py) and kept on app.state."""

    config: Config
    # None while the server is locked: the phrase has not been entered since it started.
    store: Store | None = None
    version: str = field(default_factory=paths.version)
    ready: bool = False
    # Taken while the phrase is being tried (runtime.unlock); an asyncio.Lock made at start.
    unlocking: Any = None
    # A re-encryption under way at the unlock, before the server serves (S15.7.2): its
    # progress for the locked screen, and why the last unlock failed, if it did.
    reencrypting: Any = None
    unlock_error: str | None = None
    # A new server's welcome: the phrases on offer until one is confirmed (S15.4.4).
    phrases: Phrases = field(default_factory=Phrases)
    background: set = field(default_factory=set)
    # Backups and re-encryption never run at the same time (S15.7.2).
    maintenance_lock: threading.Lock = field(default_factory=threading.Lock)
    upload_limit: int = 25 * 1024 * 1024
    # The receipt reader (S9.8.4), started with the server; tests run without one.
    reader: object | None = None
    stream_seconds: float = STREAM_SECONDS
    events: Broker = field(default_factory=Broker)
    tasks: Tasks = field(default_factory=Tasks)
    jobs: Jobs = field(default_factory=Jobs)
    idempotency: Idempotency = field(default_factory=Idempotency)
    guard: net.Guard = field(default_factory=net.Guard)
    api_limit: ratelimit.Window = field(default_factory=lambda: ratelimit.Window(600, 60))
    upload_rate: ratelimit.Window = field(default_factory=lambda: ratelimit.Window(60, 3600))
    sign_in: ratelimit.SignInGuard = field(default_factory=ratelimit.SignInGuard)
    # Password resets, re-authentications, reactivations: 30 in 15 minutes per address.
    password_asks: ratelimit.Window = field(default_factory=lambda: ratelimit.Window(30, 15 * 60))
    # Nonces of linked servers' calls, so none is accepted twice (S11.1.3).
    link_nonces: Nonces = field(default_factory=Nonces)
    # The paired connector's calls (S18.4.3): its nonces, and 60 calls a minute (S13.7.5.4).
    conn_nonces: Nonces = field(default_factory=Nonces)
    conn_limit: ratelimit.Window = field(default_factory=lambda: ratelimit.Window(60, 60))
    # Linked servers' calls (S13.7.5.4): 60 a minute per link, and those not yet signed by a
    # known key 60 a minute per address, counted before a body is read.
    link_limit: ratelimit.Window = field(default_factory=lambda: ratelimit.Window(60, 60))
    link_unknown: ratelimit.Window = field(default_factory=lambda: ratelimit.Window(60, 60))
    # The unlocked linked copies, in memory only (S11.9.3).
    copies: Copies = field(default_factory=Copies)
    # This server's link key's public half and fingerprint, once worked out (S11.1).
    link_public: tuple[bytes, str] | None = None

    def __post_init__(self) -> None:
        self.jobs = Jobs(
            announce=lambda job: self.events.publish(
                "job", {"id": job.id, "state": job.state}, users=[job.userId]
            )
        )
        self.services = Services(
            self.config, Mailer(self.config, lambda: self.store.db if self.store else None)
        )

    def badges(self, caller) -> dict[str, int]:
        """The navigation's counts (S12.1.1), sent on the live stream; they grow with the
        screens that have them. Keys are the entries' labels, lowercased."""
        counts: dict[str, int] = {}
        if self.store is None:
            return counts
        from . import alerts, clock, gifts
        from .auth import signup

        with self.db.read() as s:
            unseen = alerts.unseen(s, caller.id, caller.admin)
            waiting = len(signup.waiting(s)) if caller.admin else 0
            # Occasions inside their reminder time with nothing bought yet (S7.7.3).
            due = sum(
                1
                for u in gifts.upcoming(s, caller.id, clock.today())
                if u.inLead and not any(g.status in gifts.SPENT for g in u.gifts)
            )
        if due:
            counts["gifts"] = due
        if unseen:
            counts["alerts"] = unseen
        if waiting:
            counts["users and groups"] = waiting
        return counts

    def upload_cap(self) -> int:
        """The largest upload a request may carry: the larger of the import and receipt size
        limits in Settings (S13.7.6)."""
        if self.store is None:
            return self.upload_limit
        with self.db.read() as s:
            mb = max(settings.get(s, "importMaxMb"), settings.get(s, "receiptMaxMb"))
        # A file of the limit, with the form around it.
        return (mb + 1) * 1024 * 1024

    def network_ranges(self) -> dict[str, list[str]]:
        """Settings › Network (S16.14), read for each request."""
        if self.store is None:
            return {}
        with self.db.read() as s:
            return {
                "app": settings.get(s, "networkAppRanges"),
                "link": settings.get(s, "networkLinkRanges"),
                "connector": settings.get(s, "networkConnectorRanges"),
            }

    def session_max_age(self) -> int:
        if self.store is None:
            return 30 * 86400
        with self.db.read() as s:
            return settings.get(s, "sessionAbsoluteDays") * 86400

    @property
    def db(self):
        assert self.store is not None, "this server was made without a database"
        return self.store.db

    @property
    def keys(self):
        assert self.store is not None
        return self.store.keys.keys

    def http(self) -> net.Client:
        """A client for outbound calls, behind the egress guard (S13.5)."""
        return net.Client(self.guard)


def create_app(server: Server) -> FastAPI:
    # An upload is held in memory, never spooled to a temporary file (S13.7.6): uploads stop
    # at Settings' size, at most 100 MB, well inside this.
    from starlette.formparsers import MultiPartParser

    MultiPartParser.spool_max_size = 128 * 1024 * 1024
    app = FastAPI(
        title="MoolaKata",
        version=server.version,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    app.state.server = server
    errors.install(app)

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        """`ok` once unlocked and ready; `uninitialised` until the welcome makes the key
        (S15.4.4), `locked` until the phrase is entered (S15.4.3), and `starting` in between:
        all 503, which an uptime monitor reports."""
        status = (
            "ok"
            if server.ready
            else "re-encrypting"
            if server.reencrypting is not None
            else "starting"
            if server.store is not None
            else "locked"
            if server.config.keyring_path.exists()
            else "uninitialised"
        )
        return JSONResponse(
            {"status": status, "version": server.version},
            status_code=200 if server.ready else 503,
            headers={"Cache-Control": "no-store"},
        )

    from .ui import (
        accounts,
        activity,
        alerts,
        budgets,
        connections,
        dashboard,
        education,
        gifts,
        giving,
        imports,
        items,
        linked,
        links,
        loans,
        options,
        people,
        portfolios,
        positions,
        prices,
        profile,
        projections,
        receipts,
        reimbursements,
        rules,
        save,
        session,
        sharing,
        strategies,
        taxes,
        taxpanels,
        tokens,
        transactions,
        unlock,
        users,
        wallets,
        welcome,
    )
    from .ui import (
        connector as connector_settings,
    )
    from .ui import settings as settings_routes

    for module in (
        unlock,
        welcome,
        session,
        users,
        profile,
        tokens,
        settings_routes,
        links,
        connector_settings,
        connections,
        linked,
        accounts,
        transactions,
        rules,
        imports,
        prices,
        sharing,
        portfolios,
        positions,
        strategies,
        options,
        wallets,
        activity,
        alerts,
        budgets,
        reimbursements,
        receipts,
        projections,
        loans,
        items,
        education,
        people,
        gifts,
        giving,
        taxes,
        taxpanels,
        dashboard,
        save,
    ):
        app.include_router(module.router)
    from . import mcp
    from .connector import routes as connector_routes
    from .links import routes as link_routes

    app.include_router(mcp.router)
    app.include_router(link_routes.router)
    app.include_router(connector_routes.router)
    # Last: its catch-alls answer for paths no route above has.
    app.include_router(static.router(static.Static(server.version, server.config.dev)))

    # The last added runs first: the client's address, then the log, the headers, the Origin
    # check, the body limit, and last the gate that answers for a locked server.
    # Locked: no store and not ready. A test's bare server (no store, ready) is not locked.
    app.add_middleware(middleware.Created)
    app.add_middleware(middleware.Locked, locked=lambda: server.store is None and not server.ready)
    app.add_middleware(middleware.SessionCookie, max_age=server.session_max_age)
    app.add_middleware(middleware.BodyLimit, upload_limit=server.upload_cap)
    app.add_middleware(middleware.OriginCheck)
    app.add_middleware(middleware.SecurityHeaders, tls=server.config.mode == "tls")
    app.add_middleware(middleware.AccessLog)
    app.add_middleware(middleware.AddressRanges, ranges=server.network_ranges)
    app.add_middleware(
        middleware.ClientAddress, mode=server.config.mode, trusted=server.config.trusted_proxies
    )
    return app
