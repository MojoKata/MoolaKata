"""`moolakata db …` (requirements S14.7): each asks for the recovery phrase, the only key
there is (S15.4)."""

from pathlib import Path

from ..config import configured
from ..keys.cli import read_phrase


def register(sub) -> None:
    d = sub.add_parser("db", help="the database")
    ds = d.add_subparsers(dest="db_command", required=True)
    ds.add_parser("shell", help="SQL against the encrypted database (on the host)").set_defaults(
        func=_shell
    )
    ds.add_parser("backup", help="make a verified backup now").set_defaults(func=_backup)
    v = ds.add_parser(
        "verify-backup",
        help="check a backup is whole and opens with the phrase (the newest by default)",
    )
    v.add_argument("path", nargs="?", help="a backup folder")
    v.set_defaults(func=_verify_backup)
    r = ds.add_parser("restore", help="restore a backup, with the server stopped")
    r.add_argument("path", help="the backup folder to restore, or a pre-upgrade/ copy's .db file")
    r.set_defaults(func=_restore)


def _shell(args) -> int:
    import os

    from .maintenance import queue_host_event, shell

    config = configured(args.config)
    # Run as its container's first process (`docker compose run`), what it shows goes to
    # Docker's log; under `exec` it doesn't (CR3-369). Asked first, not refused: `run` is the
    # way in when the server won't start.
    if os.getpid() == 1:
        answer = input(
            "Docker's log will keep what this shows (run with `docker compose exec` to keep it "
            "out); go on? [y/N] "
        )
        if answer.strip().lower() not in ("y", "yes"):
            return 1
    queue_host_event(config, "db.shell", {})
    return shell(config, read_phrase())


def _backup(args) -> int:
    """Through the running server when it is up, over its socket (S15.4.7); with the phrase
    typed when it is stopped."""
    from .. import host, settings
    from ..config import RefuseStart
    from .maintenance import backup, open_store, prune, queue_host_event

    config = configured(args.config)
    try:
        with host.client(config, timeout=600) as c:
            r = c.post("/host/backup")
    except host.NotRunning:
        r = None
    if r is not None:
        if r.status_code != 200:
            raise RefuseStart(f"the server refused the backup: {host.detail(r)}")
        print(r.json()["path"])
        return 0
    from .maintenance import lock_data_dir

    # The server stopped: the data directory locked, the database opened read only, nothing
    # pending run and nothing migrated (S15.4.7).
    lock = lock_data_dir(config, "the running server makes it: `docker compose exec`")
    try:
        store = open_store(config, read_phrase(), read_only=True)
        try:
            path = backup(config, store)
            with store.db.read() as s:
                keep = settings.get(s, "backupCopies")
        finally:
            store.db.dispose()
        prune(config, keep)
    finally:
        lock.close()
    queue_host_event(config, "db.backup", {"name": path.name})
    print(path)
    return 0


def _verify_backup(args) -> int:
    from .maintenance import made_of, queue_host_event, verify_backup

    config = configured(args.config)
    path = verify_backup(config, read_phrase(), Path(args.path) if args.path else None)
    queue_host_event(config, "db.verify-backup", {"name": path.name})
    made = made_of(path)
    when = f", made {made:%Y-%m-%d %H:%M:%S} UTC" if made else ""
    print(f"{path.name}{when}: whole, and opens with that phrase")
    return 0


def _restore(args) -> int:
    from .maintenance import queue_host_event, restore

    config = configured(args.config)

    def confirm(question: str) -> bool:
        return input(question + " [y/N] ").strip().lower() in ("y", "yes")

    def other_phrase(prompt: str) -> bytes:
        return read_phrase(prompt=prompt)

    aside = restore(config, Path(args.path), read_phrase(), confirm=confirm, ask=other_phrase)
    queue_host_event(config, "db.restore", {"name": Path(args.path).name, "aside": aside.name})
    print(f"restored {Path(args.path).name}; what it replaced is in {aside}")
    print("start the server and unlock it: it opens the restored database, migrating it if needed")
    return 0
