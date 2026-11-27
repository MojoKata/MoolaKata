"""The copies on this host (requirements S15.7): backups in the backup directory, the copies
made before a migration (`pre-upgrade/`), the folders a restore set aside
(`before-restore-*/`), and a new keyring a re-encryption left unexplained, set aside beside the
keyring (`keyring.next.set-aside-*`: a data key nothing was written under). Each carries its
own keyring, so it opens with the phrase of its day for as long as it exists, and so a
re-encryption, which every rotation brings (S15.7.1), can rewrite it. The host's own
snapshots and backups are copies too, which nothing here can see."""

import contextlib
import datetime as dt
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..keys import master
from . import copy

BACKUP_PREFIX = "moolakata-"
PRE_UPGRADE = "pre-upgrade"
BEFORE_RESTORE = "before-restore-"
SET_ASIDE_RING = "keyring.next.set-aside-"


@dataclass
class Copy:
    kind: str  # backup, pre-upgrade, before-restore, keyring
    name: str
    path: Path  # the folder (a backup, a before-restore) or the database file (pre-upgrade)
    keyring: Path
    made: dt.datetime
    bytes: int
    ring: master.Keyring | None  # None when its keyring is missing or unreadable
    what: str

    @property
    def db_path(self) -> Path:
        return self.path if self.kind == "pre-upgrade" else self.path / "moolakata.db"


def _bytes(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _ring(path: Path) -> master.Keyring | None:
    try:
        return master.read_keyring(path)
    except Exception:
        return None


def _mtime(path: Path) -> dt.datetime:
    return dt.datetime.fromtimestamp(path.stat().st_mtime, dt.UTC).replace(microsecond=0)


def copies(config: Config) -> list[Copy]:
    """Every copy on this host, oldest first within each kind."""
    out: list[Copy] = []
    if config.backup_dir.is_dir():
        for p in sorted(config.backup_dir.iterdir()):
            if not (p.is_dir() and p.name.startswith(BACKUP_PREFIX)) or p.name.endswith(".part"):
                continue
            made = _mtime(p)
            with contextlib.suppress(OSError, ValueError, KeyError):
                made = dt.datetime.fromisoformat(
                    json.loads((p / "manifest.json").read_text())["made"]
                )
            out.append(
                Copy(
                    "backup",
                    p.name,
                    p,
                    p / "keyring",
                    made,
                    _bytes(p),
                    _ring(p / "keyring"),
                    "a backup",
                )
            )
    older = config.data_dir / PRE_UPGRADE
    if older.is_dir():
        for p in sorted(older.glob("moolakata-before-*.db")):
            rev = p.name.removeprefix("moolakata-before-").split("-")[0]
            ring = p.with_suffix(".keyring")
            out.append(
                Copy(
                    "pre-upgrade",
                    p.name,
                    p,
                    ring,
                    _mtime(p),
                    _bytes(p) + (_bytes(ring) if ring.exists() else 0),
                    _ring(ring),
                    f"the database before migrating to revision {rev}",
                )
            )
    for p in sorted(config.data_dir.glob(BEFORE_RESTORE + "*")):
        if p.is_dir():
            out.append(
                Copy(
                    "before-restore",
                    p.name,
                    p,
                    p / "keyring",
                    _mtime(p),
                    _bytes(p),
                    _ring(p / "keyring"),
                    "what a restore replaced",
                )
            )
    # Listed so it can be removed like any copy: it holds a data key, wrapped.
    for p in sorted(config.data_dir.glob(SET_ASIDE_RING + "*")):
        if p.is_file():
            out.append(
                Copy(
                    "keyring",
                    p.name,
                    p,
                    p,
                    _mtime(p),
                    _bytes(p),
                    _ring(p),
                    "a new keyring a re-encryption left unexplained, set aside",
                )
            )
    return out


def find(config: Config, name: str) -> Copy | None:
    return next((c for c in copies(config) if c.name == name), None)


def opens_with(c: Copy, current: master.Unlocked) -> str:
    """How a copy opens: `current` (this phrase, and the data key the server holds),
    `phrase` (this phrase, an earlier data key), `previous` (an earlier phrase), or
    `unknown` (no readable keyring)."""
    if c.ring is None:
        return "unknown"
    if c.ring.master_id != current.master_id:
        return "previous"
    if c.ring.data_key_id and c.ring.data_key_id == current.ring.data_key_id:
        return "current"
    return "phrase"


def remove(c: Copy) -> None:
    if c.kind == "keyring":
        c.path.unlink(missing_ok=True)
    elif c.kind == "pre-upgrade":
        c.path.unlink(missing_ok=True)
        c.keyring.unlink(missing_ok=True)
    else:
        shutil.rmtree(c.path)


def _refresh_manifest(c: Copy, ring: master.Keyring, data_key: bytes) -> None:
    """A backup's manifest names its files' hashes and its master key, signed under its data
    key: kept true after a re-wrap or a rewrite (S14.6)."""
    import hashlib

    from .maintenance import write_manifest

    p = c.path / "manifest.json"
    try:
        m = json.loads(p.read_text())
    except OSError, ValueError:
        return
    files = m.setdefault("files", {})
    for name in ("keyring", "moolakata.db"):
        f = c.path / name
        if f.exists():
            h = hashlib.sha256()
            with open(f, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            files[name] = {"bytes": f.stat().st_size, "sha256": h.hexdigest()}
    m["masterKey"] = master.fingerprint(ring.master_id)
    write_manifest(p, m, data_key)


def reencrypt_with(c: Copy, old_data_key: bytes, new_data_key: bytes, master_key: bytes) -> None:
    """Rewrite a copy that holds the data key a re-encryption replaced under the new one, and
    wrap its keyring under this phrase (S15.7.2), whatever phrase it was under before. Its new
    keyring is written aside first, so a crash between the two leaves a copy that opens: on a
    second run the database, already re-keyed, only takes its keyring."""
    assert c.ring is not None
    old_keys, new_keys = master.DataKeys.derive(old_data_key), master.DataKeys.derive(new_data_key)
    ring = master.wrap(master_key, new_data_key, master.now(), master.now(), (*c.ring.previous,))
    aside = c.keyring.with_name(c.keyring.name + ".next")
    master.write_keyring(aside, ring)
    if c.db_path.exists():
        try:
            copy.verify(c.db_path, new_keys.sqlcipher_key)
        except Exception:
            copy.rekey(c.db_path, old_keys.sqlcipher_key, new_keys.sqlcipher_key)
    receipts = c.path / "receipts" if c.kind == "before-restore" else None
    if receipts is not None and receipts.is_dir():
        from .reencrypt import rewrap_files

        rewrap_files(receipts, old_keys.receipts, new_keys.receipts)
    os.replace(aside, c.keyring)
    if c.kind == "backup":
        _refresh_manifest(c, ring, new_data_key)


def forget_previous(config: Config, fingerprint: str) -> bool:
    """Drop a previous master key from the keyring's list (S15.7.1.4), once every copy that
    needed it is gone. No key is needed: the list is in the clear."""
    ring = master.read_keyring(config.keyring_path)
    kept = tuple(p for p in ring.previous if master.fingerprint(p.master_id) != fingerprint)
    if len(kept) == len(ring.previous):
        return False
    master.write_keyring(
        config.keyring_path,
        master.Keyring(
            ring.master_id,
            ring.master_created,
            ring.data_key_created,
            ring.nonce,
            ring.wrapped,
            kept,
            ring.data_key_id,
        ),
    )
    return True


def chown_to_server(path: Path) -> None:
    if os.geteuid() == 0:
        os.chown(path, 10001, 10001)
