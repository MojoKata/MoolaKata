"""Opening the database at start, backups (requirements S14.6), restoring one (S15.6.8), the
data directory's lock, and the maintenance shell (S14.7)."""

import datetime as dt
import fcntl
import hashlib
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .. import clock
from ..config import Config, RefuseStart
from ..keys import master
from . import copy, mapping, migrate
from .db import Database, WrongKey, connect, make_engine

log = logging.getLogger("moolakata.store")
BACKUP_PREFIX = "moolakata-"
LOCK_FILE = "moolakata.lock"
# What a restore replaces in the data directory. Linked copies go too: they are left out of
# backups and pulled again from their sources (S11.9.9). The receipts stay in place: a backup
# is the database and its keyring only, the host backs up the files (S14.6). The TLS pair, the
# mail folder and the pre-upgrade copies stay.
RESTORED = (
    "moolakata.db",
    "moolakata.db-wal",
    "moolakata.db-shm",
    "keyring",
    "links",
    # A re-encryption the replaced database had pending belongs with it (S15.7.2).
    "keyring.next",
    "keyring.old",
    "reencrypt.json",
)
RESTORE_JOURNAL = "restore.json"
RESTORED_MARK = "restored.json"
RESTORE_REPORT = "restore-report.json"


def lock_data_dir(config: Config, why: str):
    """Hold the data directory's lock: the server holds it while it runs, and a restore takes
    it, so neither starts while the other has the directory. Returns the open lock file; the
    lock lasts until it is closed or the process ends."""
    config.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    f = open(config.data_dir / LOCK_FILE, "a")  # noqa: SIM115 - held for the process's life
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        raise RefuseStart(f"{config.data_dir} is in use by a running MoolaKata; {why}") from None
    return f


@dataclass
class Store:
    db: Database
    keys: master.Unlocked


def next_keyring(config: Config) -> Path:
    from .reencrypt import next_keyring as nxt

    return nxt(config)


def open_store(
    config: Config,
    master_key: bytes,
    migrate_copies: bool = True,
    progress=None,
    read_only: bool = False,
) -> Store:
    """Unwrap the data key with the phrase's key, carry any re-encryption pending to its end
    (S15.7.2), open the database with it, and bring it to this release. The master key is
    used here and not kept. `read_only`, for a backup on the host with the server stopped:
    nothing pending is run and nothing is migrated."""
    from . import reencrypt

    mapping.map_all()
    config.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if read_only:
        if reencrypt.pending(config):
            raise RefuseStart(
                "a re-encryption is pending: start and unlock the server so it finishes first"
            )
    else:
        reencrypt.run(config, master_key, progress)
    unlocked = master.unlock_keys(config, master_key)
    key = unlocked.keys.sqlcipher_key
    engine = make_engine(config.db_path, key)
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except WrongKey:
        raise RefuseStart(
            f"{config.db_path} does not open with the data key from {config.keyring_path.name}"
        ) from None
    except Exception as e:
        raise RefuseStart(f"{config.db_path} cannot be opened: {type(e).__name__}") from None
    if read_only:
        return Store(Database(engine), unlocked)
    if config.db_path.exists():
        os.chmod(config.db_path, 0o600)
    migrate.upgrade(
        engine,
        config.db_path,
        key,
        config.data_dir / "pre-upgrade" if migrate_copies else None,
        config.keyring_path,
    )
    return Store(Database(engine), unlocked)


def reencrypt(
    config: Config, store: Store, master_key: bytes, choices: dict[str, str] | None = None
) -> Store:
    """A re-encryption now (S15.7.2), for a store nothing else is serving: its database closed,
    the journal run, and the store opened again under the new data key."""
    from . import reencrypt as journaled

    if master.key_id(master_key) != store.keys.master_id:
        raise master.WrongPhrase("those words are not this server's key")
    store.db.dispose()
    if journaled.journal(config) is None:
        journaled.schedule(config, choices or {}, None, "host")
    journaled.run(config, master_key)
    return open_store(config, master_key)


HOST_EVENTS = "host-events.jsonl"


def queue_host_event(config: Config, kind: str, detail: dict) -> None:
    """A command run on the host, queued for Activity (S15.7.4): a one-off container has no
    phrase to open the database with, so the running server takes the queue at its next
    unlock and every quarter hour (`take_host_events`). The line is appended under the file's
    lock, to the file still at the queue's name: one the server took meanwhile is left for a
    new one (CR3-305)."""
    config.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    line = json.dumps({"kind": kind, "at": clock.now().isoformat(), "detail": detail})
    path = config.data_dir / HOST_EVENTS
    while True:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                same = os.fstat(f.fileno()).st_ino == os.stat(path).st_ino
            except FileNotFoundError:
                same = False
            if same:
                f.write(line + "\n")
                break
    if os.geteuid() == 0:
        os.chown(path, 10001, 10001)


def take_host_events(config: Config) -> list[dict]:
    """The queued host events, moved aside under a private name first, so a line appended
    meanwhile starts a new queue (CR3-305). The moved file stays until `host_events_taken`,
    once the events are recorded, so a failed record loses none (CR3-355); a file left from
    such a failure is taken again first."""
    path = config.data_dir / HOST_EVENTS
    taking = config.data_dir / (HOST_EVENTS + ".taking")
    if not taking.exists():
        try:
            os.replace(path, taking)
        except FileNotFoundError:
            return []
    with open(taking) as f:
        fcntl.flock(f, fcntl.LOCK_EX)  # a writer that opened it before the move finishes
        text = f.read()
    out = []
    for line in text.splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def host_events_taken(config: Config) -> None:
    (config.data_dir / (HOST_EVENTS + ".taking")).unlink(missing_ok=True)


# ---------- backups ----------


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def backup(config: Config, store: Store, now: dt.datetime | None = None) -> Path:
    """One verified, coherent copy of the database with its keyring (S14.6). Never the receipt
    files: the host backs up the data directory, and this copy exists so that the live
    database the host picks up has a consistent twin beside it. It opens only with the
    phrase."""
    now = now or clock.now()
    config.backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    # A backup's name is when it was made, to the second, and its manifest must agree. Two
    # made within one second (a fast host, a test) would share it: the later one takes the
    # next free second, which its manifest then records.
    while (config.backup_dir / (BACKUP_PREFIX + now.strftime("%Y%m%d-%H%M%S"))).exists():
        now += dt.timedelta(seconds=1)
    name = BACKUP_PREFIX + now.strftime("%Y%m%d-%H%M%S")
    clear_parts(config)
    part = config.backup_dir / (name + ".part")
    part.mkdir(mode=0o700)
    key = store.keys.keys.sqlcipher_key
    copy.export(store.db.engine, part / "moolakata.db", key)
    copy.verify(part / "moolakata.db", key)
    shutil.copy2(config.keyring_path, part / "keyring")
    os.chmod(part / "keyring", 0o600)
    files = {
        str(p.relative_to(part)): {"bytes": p.stat().st_size, "sha256": _sha256(p)}
        for p in sorted(part.rglob("*"))
        if p.is_file()
    }
    manifest = {
        "format": "moolakata-backup-1",
        "made": now.isoformat(),
        "server": config.name,
        "masterKey": master.fingerprint(store.keys.master_id),
        "revision": migrate.current(store.db.engine),
        "files": files,
    }
    write_manifest(part / "manifest.json", manifest, store.keys.data_key)
    final = config.backup_dir / name
    os.replace(part, final)
    log.info("backup %s made and verified", name)
    return final


def clear_parts(config: Config) -> None:
    """A backup cut off part-way (a stop, a full disk) is removed: at the next backup and at
    the server's start, never listed nor kept under an old key (CR3-299). Only one process
    makes backups at a time, under the data directory's lock or the maintenance lock."""
    if not config.backup_dir.is_dir():
        return
    for p in config.backup_dir.glob(BACKUP_PREFIX + "*.part"):
        shutil.rmtree(p, ignore_errors=True)
        log.info("backup %s, cut off part-way, removed", p.name)


def backups(config: Config) -> list[Path]:
    if not config.backup_dir.is_dir():
        return []
    return sorted(
        p
        for p in config.backup_dir.iterdir()
        if p.is_dir() and p.name.startswith(BACKUP_PREFIX) and not p.name.endswith(".part")
    )


KEEP_AT_LEAST = 3


def _day(p: Path) -> str:
    return p.name[len(BACKUP_PREFIX) :].split("-")[0]  # YYYYMMDD, in UTC


def backup_days(config: Config) -> int:
    """How many days have a backup: what *Copies kept* counts (S16.12)."""
    return len({_day(p) for p in backups(config)})


def prune(config: Config, keep: int) -> list[Path]:
    """Every backup of the `keep` most recent days that have one is kept, and the rest go
    (S14.6): a second backup the same day, *Back up now*, never pushes out an earlier day's,
    and never fewer than three days are kept (CR3-63)."""
    found = backups(config)
    days = sorted({_day(p) for p in found})[-max(keep, KEEP_AT_LEAST) :]
    gone = [p for p in found if _day(p) not in days]
    for p in gone:
        shutil.rmtree(p)
        log.info("backup %s pruned", p.name)
    return gone


def manifest_mac(manifest: dict, data_key: bytes) -> str:
    """The manifest's authentication code (S14.6): HMAC-SHA256 under a key derived from the
    data key, over everything but the code itself, so a backup swapped for an older one, or a
    manifest rewritten to match a changed file, is caught by whoever holds the phrase."""
    import hmac

    body = json.dumps({k: v for k, v in manifest.items() if k != "mac"}, sort_keys=True)
    return hmac.new(
        master.hkdf(data_key, "moolakata backup manifest"), body.encode(), hashlib.sha256
    ).hexdigest()


def write_manifest(path: Path, manifest: dict, data_key: bytes) -> None:
    manifest = {k: v for k, v in manifest.items() if k != "mac"}
    manifest["mac"] = manifest_mac(manifest, data_key)
    path.write_text(json.dumps(manifest, indent=2) + "\n")


def check_backup(path: Path, master_key: bytes) -> None:
    """A backup is whole, its manifest is its own, and it opens with this master key: the
    restore a check rehearses."""
    manifest = json.loads((path / "manifest.json").read_text())
    for rel, meta in manifest["files"].items():
        if _sha256(path / rel) != meta["sha256"]:
            raise RuntimeError(f"{rel} in {path.name} has changed since the backup")
    ring = master.read_keyring(path / "keyring")
    data_key = master.unwrap(master_key, ring)
    import hmac

    if not hmac.compare_digest(manifest.get("mac", ""), manifest_mac(manifest, data_key)):
        raise RuntimeError(f"the manifest of {path.name} is not the one its backup wrote")
    # Opened from a scratch copy: opening sets the journal mode, which rewrites the file's
    # header, and the backup must stay as its manifest describes it.
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "moolakata.db"
        shutil.copy2(path / "moolakata.db", scratch)
        copy.verify(scratch, master.DataKeys.derive(data_key).sqlcipher_key)


def made_of(path: Path) -> dt.datetime | None:
    """When a backup was made, by its manifest; a folder whose name says another time is
    refused, so a backup renamed to a newer one's name passes for nothing. None for a copy with
    no manifest (a pre-upgrade `.db`)."""
    manifest = path / "manifest.json"
    if not path.is_dir() or not manifest.exists():
        return None
    try:
        made = dt.datetime.fromisoformat(json.loads(manifest.read_text())["made"])
    except (OSError, KeyError, TypeError, ValueError) as e:
        raise RefuseStart(f"{path.name}'s manifest doesn't say when it was made: {e}") from None
    if path.name.startswith(BACKUP_PREFIX):
        try:
            named = dt.datetime.strptime(path.name[len(BACKUP_PREFIX) :], "%Y%m%d-%H%M%S")
        except ValueError:
            named = None
        if named is None or named.replace(tzinfo=dt.UTC) != made.replace(microsecond=0):
            raise RefuseStart(
                f"{path.name} was made {made:%Y-%m-%d %H:%M:%S} UTC, not when its name says: "
                "it was renamed"
            )
    return made


def verify_backup(config: Config, master_key: bytes, path: Path | None = None) -> Path:
    """`moolakata db verify-backup`: a backup (the newest by default) is whole and opens with
    the phrase typed, which may be a previous one for a backup made before a rotation: the
    drill operations.md asks for."""
    if path is None:
        made = backups(config)
        if not made:
            raise RefuseStart(f"there is no backup in {config.backup_dir}")
        path = made[-1]
    made_of(path)
    try:
        check_backup(path, master_key)
    except ValueError as e:
        raise RefuseStart(f"{path.name} does not open with that phrase: {e}") from None
    return path


def _source(path: Path) -> tuple[Path, Path, dict | None]:
    """A restore's database and keyring: a backup folder's, or a pre-upgrade copy's `.db`
    with the `.keyring` beside it (S15.6.8, S16.13)."""
    if path.is_file() and path.suffix == ".db":
        return path, path.with_suffix(".keyring"), None
    return path / "moolakata.db", path / "keyring", json.loads((path / "manifest.json").read_text())


def restore(
    config: Config,
    backup_path: Path,
    master_key: bytes,
    now: dt.datetime | None = None,
    confirm=None,
    ask=None,
) -> Path:
    """`moolakata db restore`, with the server stopped (S15.6.8): check the copy opens with
    the phrase typed; name the phrase it restores under, and ask before reviving an earlier
    one; move what it replaces aside into `before-restore-<time>/`; copy it in; and re-wrap the
    receipt files to its data key when a re-encryption came between, a journaled step, asking
    for the replaced keyring's phrase when it is another. The next unlock opens it, migrates
    it if it is from an earlier release, starts each link's copy again and reports what it
    can't open. Returns the folder the replaced files went to."""
    lock = lock_data_dir(config, "stop the server before restoring")
    try:
        journal_path = config.data_dir / RESTORE_JOURNAL
        if journal_path.exists():
            j = json.loads(journal_path.read_text())
            aside = config.data_dir / j["aside"]
        else:
            aside = _copy_in(config, backup_path, master_key, now, confirm)
            j = {"aside": aside.name, "source": backup_path.name}
            journal_path.write_text(json.dumps(j))
        j["receiptsSetAside"] = _rewrap_restored(config, aside, master_key, ask)
        (config.data_dir / RESTORED_MARK).write_text(
            json.dumps({**j, "at": (now or clock.now()).isoformat()})
        )
        journal_path.unlink()
        log.info("restored %s; the files it replaced are in %s", backup_path.name, aside.name)
        return aside
    finally:
        lock.close()


def _copy_in(config: Config, backup_path: Path, master_key: bytes, now, confirm) -> Path:
    db, ring_path, manifest = _source(backup_path)
    if manifest is not None:
        verify_backup(config, master_key, backup_path)
        revision = manifest.get("revision")
        if revision is not None and revision not in migrate.known():
            raise RefuseStart(
                f"{backup_path.name} is at revision {revision}, from a newer MoolaKata than "
                "this one; restore it with that release or a later one"
            )
    else:
        ring = master.read_keyring(ring_path)
        try:
            data_key = master.unwrap(master_key, ring)
        except ValueError as e:
            raise RefuseStart(f"{backup_path.name} does not open with that phrase: {e}") from None
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp) / "moolakata.db"
            shutil.copy2(db, scratch)
            copy.verify(scratch, master.DataKeys.derive(data_key).sqlcipher_key)
    restored = master.read_keyring(ring_path)
    if config.keyring_path.exists():
        current = master.read_keyring(config.keyring_path)
        if current.master_id != restored.master_id:
            question = (
                f"{backup_path.name} was made under {master.fingerprint(restored.master_id)}. "
                f"Restored, the server unlocks with that phrase, and the current one "
                f"({master.fingerprint(current.master_id)}) no longer does. Go on?"
            )
            if confirm is None or not confirm(question):
                raise RefuseStart("nothing was restored: the current phrase stays")
    stamp = (now or clock.now()).strftime("%Y%m%d-%H%M%S")
    aside = config.data_dir / f"before-restore-{stamp}"
    aside.mkdir(mode=0o700)
    for name in RESTORED:
        if (config.data_dir / name).exists():
            os.replace(config.data_dir / name, aside / name)
    shutil.copy2(db, config.db_path)
    shutil.copy2(ring_path, config.keyring_path)
    for p in (config.db_path, config.keyring_path):
        os.chmod(p, 0o600)
    return aside


def _rewrap_restored(config: Config, aside: Path, master_key: bytes, ask) -> list[str]:
    """The receipt files under the restored data key: when they are under the one it replaced
    (a re-encryption since the backup), each is rewritten from that key, asked for by its
    phrase when the one typed doesn't open it (S15.6.8)."""
    from . import reencrypt

    target = master.DataKeys.derive(
        master.unwrap(master_key, master.read_keyring(config.keyring_path))
    )
    folder = config.receipts_dir
    files = sorted(folder.glob("*.mkr")) if folder.is_dir() else []
    if all(reencrypt.opens(p, target.receipts, p.stem) for p in files):
        return []
    replaced_path = aside / "keyring"
    if not replaced_path.exists():
        return reencrypt.rewrap_files(folder, target.receipts, target.receipts)
    replaced = master.read_keyring(replaced_path)
    key = master_key
    if replaced.master_id != master.key_id(master_key):
        if ask is None:
            raise RefuseStart(
                f"the receipt files are under the data key the restore replaced, wrapped by "
                f"{master.fingerprint(replaced.master_id)}: its phrase is needed to re-wrap them"
            )
        key = ask(f"the replaced keyring's phrase ({master.fingerprint(replaced.master_id)}): ")
    try:
        old = master.DataKeys.derive(master.unwrap(key, replaced))
    except ValueError as e:
        raise RefuseStart(f"that phrase doesn't open the replaced keyring: {e}") from None
    return reencrypt.rewrap_files(folder, old.receipts, target.receipts)


def after_restore(config: Config) -> dict | None:
    """At the unlock after a restore: what it left to do (`restored.json`), kept until
    `restore_checked` says it is done, so a failed unlock does it again (CR3-298)."""
    try:
        return json.loads((config.data_dir / RESTORED_MARK).read_text())
    except FileNotFoundError, ValueError:
        return None


def restore_checked(config: Config) -> None:
    (config.data_dir / RESTORED_MARK).unlink(missing_ok=True)


def restore_report(config: Config) -> dict | None:
    try:
        return json.loads((config.data_dir / RESTORE_REPORT).read_text())
    except FileNotFoundError, ValueError:
        return None


def write_restore_report(config: Config, report: dict) -> None:
    (config.data_dir / RESTORE_REPORT).write_text(json.dumps(report, indent=2))


# ---------- the maintenance shell ----------


def shell(config: Config, master_key: bytes) -> int:
    """`moolakata db shell`: SQL against the database, on the host, with the phrase typed.
    Secrets stay encrypted even here (S15.3.4)."""
    try:
        unlocked = master.unlock_keys(config, master_key)
    except master.WrongPhrase as e:
        raise RefuseStart(str(e)) from None
    try:
        conn = connect(config.db_path, unlocked.keys.sqlcipher_key)
    except WrongKey as e:
        raise RefuseStart(str(e)) from None
    print(f"{config.db_path} ({master.fingerprint(unlocked.master_id)}). End with Ctrl-D.")
    buf = ""
    while True:
        try:
            line = input("sql> " if not buf else "...> ")
        except EOFError:
            print()
            break
        buf += line + "\n"
        if not buf.strip().endswith(";"):
            continue
        try:
            cur = conn.execute(buf)
            rows = cur.fetchall()
            if cur.description:
                print(" | ".join(d[0] for d in cur.description))
            for r in rows:
                print(" | ".join("" if v is None else str(v) for v in r))
        except Exception as e:
            print(f"error: {e}")
        buf = ""
    conn.close()
    return 0


def rotate_running(
    config: Config,
    store: Store,
    new_master: bytes,
    choices: dict[str, str] | None = None,
    by: str | None = None,
) -> tuple[Store, dict[str, str]]:
    """Rotation (S15.7.1) in the running server, which holds the data key, so the current
    phrase is not needed to wrap it. The journal comes first, naming the new master key and
    each copy's choice (re-encrypt by default), then the keyring wrapped under the new key
    with the old one recorded (CR3-296); the server then restarts, and the unlock with the new
    phrase re-encrypts and carries out the copies' choices (S15.7.2). Returns the store under
    the new keyring, and what each copy will meet there."""
    from . import copies, reencrypt

    if reencrypt.pending(config):
        raise RefuseStart("a re-encryption is pending: it finishes at the next unlock")
    choices = choices or {}
    found = copies.copies(config)
    planned = {c.name: choices.get(c.name, "reencrypt") for c in found}
    reencrypt.schedule(config, planned, by, "rotation", to=master.key_id(new_master))
    at = master.now()
    ring = master.rotated(store.keys.ring, store.keys.data_key, new_master, at)
    master.write_keyring(config.keyring_path, ring)
    new = master.Unlocked(ring.master_id, ring, store.keys.keys, store.keys.data_key)
    outcomes = {}
    for c in found:
        choice, how = planned[c.name], copies.opens_with(c, store.keys)
        if choice == "delete":
            outcomes[c.name] = "deleted at the restart"
        elif choice == "leave" or c.kind == "keyring":
            outcomes[c.name] = "left"
        elif how == "current":
            outcomes[c.name] = "re-encrypted at the restart"
        elif c.ring is None:
            outcomes[c.name] = "left: its keyring cannot be read"
        else:  # under the old phrase with an earlier data key, or an earlier phrase
            outcomes[c.name] = f"left: needs the phrase of {master.fingerprint(c.ring.master_id)}"
    return Store(store.db, new), outcomes
