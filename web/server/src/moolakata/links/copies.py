"""Linked copies as people and admins use them (requirements S11.9): making the access key,
unlocking, locking and resetting a copy, with each recorded in Activity (S11.8)."""

import contextlib
import json
import logging

from sqlalchemy import false, select

from .. import activity, clock, settings
from ..store.entities.links import Link, LinkedItem
from .copy import CopyError, folder

log = logging.getLogger("moolakata.links")


def named(s, link_id: str, user_id: str) -> bool:
    """Whether any item this link brought in names this user (S11.9.3.2)."""
    for row in s.scalars(select(LinkedItem.viewers).where(LinkedItem.linkId == link_id)):
        if user_id in json.loads(row or "[]"):
            return True
    return False


def _link(s, link_id: str) -> Link:
    link = s.get(Link, link_id)
    if link is None or link.deleted:
        raise CopyError("not-found", "No such link.")
    return link


def make_key(srv, link_id: str, by: str) -> list[str]:
    """Create the access key (S11.9.2.1): the copy made, its words shown once."""
    with srv.db.read() as s:
        link = _link(s, link_id)
        if link.state not in ("active", "paused"):
            raise CopyError("link-not-active", "Only an active link's copy has an access key.")
        if link.copyPublicKey:
            raise CopyError(
                "key-exists", "This copy has its access key. Reset copy makes a new one."
            )
    public, words, name = srv.copies.create(srv.config.data_dir, link_id, by, clock.now())
    with srv.db.tx() as s:
        link = _link(s, link_id)
        link.copyPublicKey, link.copyKeyAt, link.copyKeyById = public, clock.now(), by
        link.copyFolder = name
        link.needsFull = True  # pulls into the copy begin now, with everything
        activity.record(s, "link.copy-key-made", actor=by, for_admins=True)
    return words


def unlock(srv, link_id: str, user_id: str, words: str) -> None:
    with srv.db.read() as s:
        link = _link(s, link_id)
        if not named(s, link_id, user_id):
            raise CopyError("not-named", "Nothing from this household is shared with you.")
        if not link.copyPublicKey:
            raise CopyError("no-key", "An admin hasn't created this copy's access key yet.")
        public = link.copyPublicKey
    try:
        srv.copies.unlock(srv.config.data_dir, link_id, public, words, user_id, clock.now())
    except CopyError:
        with srv.db.tx() as s:
            activity.record(s, "link.copy-unlock-failed", actor=user_id, for_admins=True)
        raise
    with srv.db.tx() as s:
        activity.record(s, "link.copy-unlocked", actor=user_id, for_admins=True)
    from .changes import ChangeError, apply

    # What arrived while it was locked is applied now (S11.9.5.3); a change that fails is
    # reported on the link and the copy stays as it was.
    with contextlib.suppress(ChangeError):
        apply(srv, link_id)


def lock(srv, link_id: str, user_id: str, admin: bool) -> None:
    with srv.db.read() as s:
        _link(s, link_id)
        if not admin and not named(s, link_id, user_id):
            raise CopyError("not-named", "Nothing from this household is shared with you.")
    if srv.copies.release(link_id):
        with srv.db.tx() as s:
            activity.record(
                s,
                "link.copy-locked",
                actor=user_id,
                for_admins=True,
                detail={"why": "Lock now"},
            )


def reset(srv, link_id: str, by: str) -> None:
    """Reset copy (S11.9.8): the folder deleted and the key forgotten; a new access key is made
    next, and everything is pulled again from the source."""
    srv.copies.reset(srv.config.data_dir, link_id)
    with srv.db.tx() as s:
        link = _link(s, link_id)
        link.copyPublicKey = link.copyKeyAt = link.copyKeyById = None
        link.needsFull = True
        activity.record(s, "link.copy-reset", actor=by, for_admins=True)


ORPHAN_MINUTES = 10  # a file this old that no row names was left by a crash


def orphans(srv, link_id: str) -> int:
    """With the copy open: the receipt files no row of it names, and the temporary files a
    write left behind, once old enough not to be one still arriving (S11.9.6.6). A file a
    peer delivered stays until the change that names it comes. Returns how many went."""
    import time

    from sqlalchemy import select

    from . import copydb
    from .routes import DELIVERED

    o = srv.copies.get(link_id, for_person=False)
    d = folder(srv.config.data_dir, link_id) / "receipts"
    if o is None or not d.exists():
        return 0
    with o.engine.connect() as conn:
        kept = set(conn.execute(select(copydb.File.c.fileName)).scalars())
    waiting = DELIVERED.names(link_id)
    # Receipts fetched after their change, waiting to be placed in the copy (S11.4).
    from ..store.entities.links import LinkFile

    with srv.db.read() as s:
        waiting |= set(
            s.scalars(
                select(LinkFile.fileName).where(
                    LinkFile.linkId == link_id, LinkFile.fileName.is_not(None)
                )
            )
        )
    old = time.time() - ORPHAN_MINUTES * 60
    gone = 0
    for f in d.iterdir():
        if f.stat().st_mtime > old or f.name in kept or f.name in waiting:
            continue
        if f.suffix in (".mkr", ".tmp"):
            f.unlink(missing_ok=True)
            gone += 1
    return gone


def sweep(srv) -> list[str]:
    with srv.db.read() as s:
        minutes = settings.get(s, "linkReleaseMinutes")
    for link_id in list(srv.copies.open):
        try:
            orphans(srv, link_id)
        except Exception:  # a sweep never stops the locking that follows
            log.exception("sweeping a linked copy's files failed")
    locked = srv.copies.sweep(minutes)
    if locked:
        with srv.db.tx() as s:
            for _ in locked:
                activity.record(
                    s,
                    "link.copy-locked",
                    actor=None,
                    for_admins=True,
                    detail={"why": "unused"},
                )
    return locked


def size(srv, link_id: str) -> tuple[int, int]:
    """The copy's size on disk and its number of receipts."""
    path = folder(srv.config.data_dir, link_id)
    if not path.exists():
        return 0, 0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    receipts = (
        sum(1 for _ in (path / "receipts").glob("*.mkr")) if (path / "receipts").exists() else 0
    )
    return total, receipts


def live_links(s) -> list[Link]:
    return list(
        s.scalars(select(Link).where(Link.deleted == false(), Link.state.in_(("active", "paused"))))
    )
