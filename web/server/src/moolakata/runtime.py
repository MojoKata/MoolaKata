"""Starting and stopping the server: everything that happens before the first request and
after the last."""

import asyncio
import datetime as dt
import logging
import os
import signal

from sqlalchemy import delete, select

from . import clock, figures, listener, settings, timezones
from .app import Server, create_app
from .auth import sessions, users
from .config import Config, RefuseStart
from .keys import master
from .prices import refresh as pricing
from .store import maintenance
from .store.entities.core import TaskRun
from .store.entities.users import OneTimeToken
from .store.repos import ledger
from .tasks import Daily, Every, TaskContext, Tasks
from .tasks import TaskRun as Run

log = logging.getLogger("moolakata")


def record_run(server: Server):
    def record(name: str, run: Run) -> None:
        with server.db.tx(unscoped="runtime: record") as s:
            row = s.get(TaskRun, name)
            if row is None:
                s.add(
                    TaskRun(
                        name=name, startedAt=run.started, finishedAt=run.finished, error=run.error
                    )
                )
            else:
                row.startedAt, row.finishedAt, row.error = run.started, run.finished, run.error
        # Its name only: Settings › Backups and Key storage reload when theirs ends.
        server.events.publish("task", {"name": name})
        if name not in ("alerts", "alert-summaries", "linked-copies"):
            # A task's outcome can open or resolve an alert: look now, not in 15 minutes. The
            # copies' sweeper, every minute, raises none.
            server.tasks.run_now("alerts")

    return record


def last_runs(server: Server) -> dict[str, Run]:
    with server.db.read(unscoped="runtime: last runs") as s:
        return {r.name: Run(r.startedAt, r.finishedAt, r.error) for r in s.scalars(select(TaskRun))}


def register_tasks(server: Server) -> None:
    """The background tasks of S13.4 that this release has."""
    server.tasks = Tasks(record=record_run(server))
    last = last_runs(server)

    def setting_time(key: str):
        def at() -> tuple[dt.time, str]:
            with server.db.read(unscoped="runtime: at") as s:
                return settings.time_of(s, key), timezones.host_zone()

        return at

    def backup(ctx: TaskContext) -> None:
        # Never beside a re-encryption (S15.7.2): one would copy a keyring the other is
        # replacing. The lock makes one wait for the other.
        with server.maintenance_lock:
            maintenance.backup(server.config, server.store)
            with server.db.read(unscoped="runtime: backup") as s:
                keep = settings.get(s, "backupCopies")
            maintenance.prune(server.config, keep)

    server.tasks.register("backups", backup, Daily(setting_time("backupTime")), last.get("backups"))

    def prune(ctx: TaskContext) -> None:
        """Expired sessions and one-time tokens are removed outright (schema.md §4.4.1)."""
        with server.db.tx(unscoped="runtime: prune") as s:
            sessions.prune(s)
            s.execute(delete(OneTimeToken).where(OneTimeToken.expiresAt <= sessions.now()))

    server.tasks.register("pruning", prune, Every(3600), last.get("pruning"))

    def price_time() -> tuple[dt.time, str]:
        with server.db.read(unscoped="runtime: price time") as s:
            return settings.time_of(s, "priceRefreshTime"), settings.get(s, "priceRefreshZone")

    server.tasks.register(
        "prices", lambda ctx: pricing.refresh(server, ctx), Daily(price_time), last.get("prices")
    )

    def mail(ctx: TaskContext) -> None:
        """Send what the queue holds (S16.2): at once when an email is queued, and every five
        minutes for what could not go, until its link expires."""
        from .mail import expire_written, smtp_settings

        expire_written(server.config)
        mailer = server.services.mailer
        mailer.adopt_outbox()
        mailer.expire()
        if not mailer.waiting():
            return
        with server.db.read(unscoped="runtime: mail") as s:
            smtp = smtp_settings(s, server.keys.secrets)
        server.services.mailer.send_waiting(smtp, server.guard, ctx.stop)

    server.tasks.register("mail", mail, Every(300), last.get("mail"))

    def expire_options(ctx: TaskContext) -> None:
        """Options that expired out of the money end the day after (S3.6)."""
        from . import options

        with server.db.tx(unscoped="runtime: expire options") as s:
            options.expire_due(s, clock.today())

    server.tasks.register("options", expire_options, Every(3600), last.get("options"))

    def bitcoin(ctx: TaskContext) -> None:
        """Self-custody wallets read from the explorer or node (S1.6.2)."""
        from .bitcoin import sync

        sync.sync_all(server, ctx)

    server.tasks.register("bitcoin", bitcoin, Every(3600), last.get("bitcoin"))

    def links(ctx: TaskContext) -> None:
        """An exchange with each linked server (S11.4): hourly. Dev mode with stubs makes no
        outside calls, so its seeded link is left as it is."""
        from .links import manage

        if server.config.stubs:
            return
        # A new certificate key of this server's own, told to the peers first (§4.5).
        manage.announce_certificate(server)
        manage.exchange_all(server, ctx)

    server.tasks.register("links", links, Every(3600), last.get("links"))

    def lock_copies(ctx: TaskContext) -> None:
        """Lock each linked copy that has gone unused past its time (S11.9.4.2)."""
        from .links import copies as linked

        linked.sweep(server)

    server.tasks.register("linked-copies", lock_copies, Every(60), last.get("linked-copies"))

    from . import alerts

    server.tasks.register(
        "alerts", lambda ctx: alerts.evaluate(server), Every(900), last.get("alerts")
    )

    def host_events(ctx: TaskContext) -> None:
        # What the host's commands queued, within a quarter of an hour (S15.4.7); a phrase
        # checked on the host clears its alert at once.
        kinds = take_host_events(server)
        if kinds & {"key.verified", "key.verify-failed"}:
            server.tasks.run_now("alerts")

    server.tasks.register("host-events", host_events, Every(900), last.get("host-events"))
    server.tasks.register(
        "alert-summaries",
        lambda ctx: alerts.daily_summaries(server),
        Every(600),
        last.get("alert-summaries"),
    )
    server.services.mailer.notify = lambda: server.tasks.run_now("mail")


# What start() answers when the server stops in order to start again (main.py re-executes it).
RESTART = 75


def restart(server: Server, after: float = 1.0) -> None:
    """Stop cleanly, then start again in this same process, locked (S15.7.2): a re-encryption
    or a rotation, once scheduled, runs at the unlock that follows, with the phrase typed there.
    Nothing of a key crosses the restart. The answer to the request that asked for it goes out
    first."""
    server.restarting = True
    log.info("restarting, so the re-encryption runs at the next unlock")
    loop = server.loop
    if loop is not None:
        loop.call_soon_threadsafe(loop.call_later, after, os.kill, os.getpid(), signal.SIGTERM)


class AlreadyUnlocked(Exception):
    pass


def build(server: Server, master_key: bytes) -> None:
    """Open the store with the phrase's key and make the server whole (S15.4.3), carrying any
    re-encryption pending to its end first, before anything is served (S15.7.2). The master
    key is used here and not kept. A failure part-way leaves the server locked, as it was,
    with nothing it did half kept (CR3-298)."""
    from .store import reencrypt

    config = server.config
    was_pending = reencrypt.pending(config)
    store = maintenance.open_store(config, master_key, progress=server.reencrypting)
    pricing.install()
    server.store = store
    try:
        _build(server, was_pending)
    except BaseException:
        relock(server)
        raise
    reencrypt.tidy(config)


def relock(server: Server) -> None:
    """Back to locked after an unlock that failed part-way: the store closed, the tasks
    registered or started dropped (CR3-298)."""
    store, server.store, server.ready = server.store, None, False
    server.tasks.stop()
    server.tasks = Tasks()
    if server.reader is not None:
        server.reader.stop()
        server.reader = None
    if store is not None:
        store.db.dispose()


def _build(server: Server, was_pending: bool) -> None:
    config = server.config
    with server.db.tx(unscoped="runtime: build") as s:
        if not users.has_users(s):
            log.info("no users yet: the page sets up the first admin (S10.1.2)")
        ledger.ensure_categories(s)
        figures.ensure_benchmarks(s)
    if config.dev and config.stubs:
        from .dev import devmode

        devmode.enable_stub_prices(server)
    register_tasks(server)
    from .ui.prices import apply_egress

    apply_egress(server)
    take_host_events(server)
    restored = maintenance.after_restore(config)
    if restored is not None:
        check_restored(server, restored)
        maintenance.restore_checked(config)
    load_copy_folders(server)
    if was_pending:
        record_reencryption(server)


def check_restored(server: Server, restored: dict) -> None:
    """The first unlock after a restore (S15.6.8): each link's copy starts again, pulled in
    full (S11.9.9), and every receipt file and secret the restored keys can't open is reported
    in Settings › Key storage and in Activity."""
    from sqlalchemy import select as sql_select

    from . import activity
    from .keys import secrets as sealing
    from .store import reencrypt
    from .store.entities.core import Secret
    from .store.entities.links import Link
    from .store.entities.receipts import Receipt

    keys = server.store.keys.keys
    folder = server.config.receipts_dir
    unopened = []
    with server.db.read(unscoped="runtime: check restored") as s:
        for r in s.scalars(
            sql_select(Receipt).where(Receipt.deleted.is_(False), Receipt.filePrunedAt.is_(None))
        ):
            path = folder / f"{r.fileId}.mkr"
            if not reencrypt.opens(path, keys.receipts, r.fileId):
                unopened.append(r.id)
        secrets = []
        for row in s.scalars(sql_select(Secret)):
            try:
                sealing.open_sealed(
                    keys.secrets,
                    sealing.Sealed(row.ciphertext, row.nonce, row.wrappedKey),
                    row.recordType,
                    row.recordId,
                    row.field,
                )
            except sealing.SecretError:
                secrets.append(f"{row.recordType}/{row.field}")
    with server.db.tx(unscoped="runtime: check restored") as s:
        for link in s.scalars(sql_select(Link).where(Link.deleted.is_(False))):
            link.copyPublicKey = link.copyKeyAt = link.copyKeyById = link.copyFolder = None
            link.inboxAsOf = None
            link.needsFull = True
        report = {
            "at": restored.get("at"),
            "source": restored.get("source"),
            "receiptsSetAside": restored.get("receiptsSetAside") or [],
            "receiptsUnopened": unopened,
            "secretsUnopened": secrets,
        }
        maintenance.write_restore_report(server.config, report)
        activity.record(
            s,
            "db.restore-checked",
            actor=None,
            for_admins=True,
            detail={
                "receipts": len(unopened),
                "secrets": len(secrets),
                "setAside": len(report["receiptsSetAside"]),
            },
        )


def record_reencryption(server: Server) -> None:
    """A re-encryption the unlock carried out, in Activity with what it set aside (S15.7.2)."""
    from . import activity
    from .store import reencrypt

    done = reencrypt.report(server.config)
    if not done:
        return
    with server.db.tx(unscoped="runtime: record reencryption") as s:
        activity.record(
            s,
            "keys.reencrypted",
            actor=None,
            for_admins=True,
            detail={
                "why": done.get("why"),
                "receiptsSetAside": len(done.get("receiptsSetAside") or []),
                "secretsSetAside": len(done.get("secretsSetAside") or []),
                "copies": done.get("copies") or {},
            },
        )


def load_copy_folders(server: Server) -> None:
    """Each link's copy folder, by its random name (S11.9.1), for the copies' paths."""
    from sqlalchemy import select

    from .links import copy as linked
    from .store.entities.links import Link

    with server.db.read(unscoped="runtime: load copy folders") as s:
        for link_id, name in s.execute(
            select(Link.id, Link.copyFolder).where(Link.copyFolder.is_not(None))
        ):
            linked.NAMES[link_id] = name


def take_host_events(server: Server) -> set[str]:
    """What the host's one-off commands queued (every `keys` and `db` command), into Activity;
    returns the kinds taken."""
    from . import activity

    events = maintenance.take_host_events(server.config)
    if not events:
        maintenance.host_events_taken(server.config)
        return set()
    with server.db.tx(unscoped="runtime: take host events") as s:
        for e in events:
            activity.record(
                s,
                str(e.get("kind", "host")),
                actor=None,
                via="host",
                for_admins=True,
                detail={**(e.get("detail") or {}), "at": e.get("at")},
            )
    maintenance.host_events_taken(server.config)
    return {str(e.get("kind")) for e in events}


class Reencrypting(Exception):
    """The phrase opened the keyring, and a re-encryption runs before the server serves."""


async def unlock(server: Server, master_key: bytes, seed: bool = False, wait: bool = True) -> None:
    """The phrase given (from the unlock page, `keys unlock`, or dev mode): the server opens
    its store and starts its tasks. Once per start; a restart locks it again (S15.4.3). With a
    re-encryption pending (S15.7.2), the phrase is checked at once and the run carries on in
    the background, its progress on the locked screen; `wait=False` returns then."""
    from .store import reencrypt

    if server.unlocking is None:
        server.unlocking = asyncio.Lock()
    if server.reencrypting is not None:
        raise Reencrypting
    async with server.unlocking:
        if server.store is not None:
            raise AlreadyUnlocked
        if reencrypt.pending(server.config):
            await asyncio.to_thread(reencrypt.check_phrase, server.config, master_key)
            server.reencrypting = reencrypt.Progress()
            server.unlock_error = None
            task = asyncio.get_running_loop().create_task(_complete(server, master_key, seed))
            server.background.add(task)
            task.add_done_callback(server.background.discard)
            if wait:
                await task
            return
        await _open(server, master_key, seed)


async def _complete(server: Server, master_key: bytes, seed: bool) -> None:
    try:
        await _open(server, master_key, seed)
    except Exception as e:
        server.unlock_error = str(e) if isinstance(e, RefuseStart) else type(e).__name__
        # The log names what failed (a file, a step), which the locked screen doesn't show.
        log.error("the re-encryption at the unlock failed: %s: %s", type(e).__name__, e)
    finally:
        server.reencrypting = None


async def _open(server: Server, master_key: bytes, seed: bool) -> None:
    await asyncio.to_thread(build, server, master_key)
    try:
        await _serve(server, seed)
    except BaseException:
        relock(server)
        raise


async def _serve(server: Server, seed: bool) -> None:
    # Every unlock is a check of the recovery phrase: a copy that unlocks is a good copy
    # (S15.6.5).
    from . import activity
    from .keys import master

    with server.db.tx(unscoped="runtime: serve") as s:
        activity.record(
            s,
            "key.unlocked",
            actor=None,
            for_admins=True,
            detail={"fingerprint": master.fingerprint(server.store.keys.master_id)},
        )
    if server.config.dev:
        from .dev import devmode

        await asyncio.to_thread(devmode.after_start, server, seed)
    from .receipts.reading import Reader

    server.reader = Reader(server)
    server.tasks.start()
    server.reader.start()
    server.ready = True
    log.info("unlocked: %s", server.store.keys.master_id and server.version)


async def start(config: Config, seed: bool = False) -> int:
    dev_key: bytes | None = None
    if config.dev:
        from .dev import devmode

        dev_key = devmode.prepare(config)
    from .store.maintenance import lock_data_dir

    lock = lock_data_dir(config, "only one server may use a data directory")  # noqa: F841 - held while running
    maintenance.clear_parts(config)  # a backup a stop cut off (CR3-299)
    # No keyring: the server starts uninitialised and its page makes the key (S15.4.4). One
    # it can't read, or a database without one, refuses the start (S15.4.5).
    master.refuse_a_database_without_its_keyring(config)
    if config.keyring_path.exists():
        master.read_keyring(config.keyring_path)
    # No other process of this account reads the server's memory, keys and all (S9.8.4.2);
    # the reader's workers are kept out of the data directory.
    from . import parsing, sandbox

    sandbox.not_dumpable()
    parsing.use_data_dir(config.data_dir)
    server = Server(config=config)
    server.unlocking = asyncio.Lock()
    server.loop = asyncio.get_running_loop()
    app = create_app(server)
    from .host import create_host_app

    host_app = create_host_app(server)
    server.events.bind(asyncio.get_running_loop())
    if dev_key is not None:
        await unlock(server, dev_key, seed=seed)

    async def on_stop() -> None:
        server.ready = False
        await server.events.close_all()
        if server.store is not None:
            server.tasks.stop()
            server.reader.stop()
        parsing.stop()

    scheme = "https" if config.mode == "tls" else "http"
    log.info(
        "MoolaKata %s%s listening on %s://%s:%s%s",
        server.version,
        " (dev)" if config.dev else "",
        scheme,
        config.host,
        config.port,
        ""
        if server.store is not None
        else ": locked until the recovery phrase is entered"
        if config.keyring_path.exists()
        else ": uninitialised, the page makes the key (S15.4.4)",
    )
    try:
        await listener.run(app, config, on_stop, host_app)
    finally:
        if server.store is not None:
            server.db.dispose()
    log.info("stopped")
    return RESTART if server.restarting else 0
