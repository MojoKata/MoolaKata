"""Linked households for the people they share with (requirements S12.10, S11.9.3): which
households share something with you, and unlocking and locking a household's copy."""

import datetime as dt
import json

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import false, select

from .. import activity, exactjson, settings
from ..errors import Problem, refuse
from ..links import copies
from ..links.changes import waiting
from ..links.copy import CopyError
from ..store.entities.links import Link, LinkedItem
from ..store.entities.users import User
from ..store.rows import by_key
from . import save
from .conventions import ExactRoute, IdOf, Model
from .deps import Caller, caller, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["linked"])


PALETTE = ("teal", "violet", "amber", "rose", "green", "blue")


class Household(Model):
    linkId: str
    colour: str  # the colour you chose for its window
    # Your choice, a record of the save (LinkColour): none while it takes the next free one.
    colourId: str | None = None
    colourVersion: int = 0
    serverName: str | None
    name: str | None
    avatar: dict | None
    items: int  # shared with you
    syncedAt: dt.datetime | None
    locked: bool


class CopyState(Model):
    household: Household
    hasKey: bool  # an admin has created the access key
    waiting: int  # changes pulled while it was locked
    pulledAt: dt.datetime | None
    unlockedBy: str | None
    unlockedAt: dt.datetime | None
    locksInSeconds: int | None


class Unlock(Model):
    words: str


def _mine(s, user_id: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in s.scalars(select(LinkedItem)):
        if user_id in json.loads(row.viewers or "[]"):
            out[row.linkId] = out.get(row.linkId, 0) + 1
    return out


def _chosen(s, user_id: str) -> dict:
    """The colours this user chose, by link: each its record."""
    from ..store.entities.links import LinkColour

    rows = s.scalars(
        select(LinkColour).where(LinkColour.userId == user_id, LinkColour.deleted == false())
    )
    return {r.linkId: r for r in rows}


def _colours(s, user_id: str, link_ids: list[str]) -> dict[str, str]:
    """Each household's colour for this user: chosen, or the next one not yet used."""
    from ..store.entities.links import LinkColour

    chosen = {
        r.linkId: r.colour
        for r in s.scalars(select(LinkColour).where(LinkColour.userId == user_id))
    }
    out, used = {}, set(chosen.values())
    for lid in sorted(link_ids):
        if lid in chosen:
            out[lid] = chosen[lid]
        else:
            out[lid] = next((c for c in PALETTE if c not in used), PALETTE[len(out) % 6])
            used.add(out[lid])
    return out


def _household(srv, link: Link, n: int, colour: str = "teal", chosen=None) -> Household:
    return Household(
        linkId=link.id,
        colour=colour,
        colourId=chosen.id if chosen is not None else None,
        colourVersion=chosen.version if chosen is not None else 0,
        serverName=link.peerName,
        name=link.householdName,
        avatar=json.loads(link.householdAvatar) if link.householdAvatar else None,
        items=n,
        syncedAt=link.lastOkAt,
        locked=srv.copies.get(link.id, for_person=False) is None,
    )


@router.get("/linked", response_model=list[Household])
def households(request: Request, c: Caller = Depends(caller)):
    """The households that share something with you (S12.10.1); none share nothing."""
    srv = server(request)
    with srv.db.read() as s:
        mine = _mine(s, c.id)
        rows = s.scalars(
            select(Link).where(
                Link.id.in_(list(mine)),
                Link.deleted == false(),
                Link.state.in_(("active", "paused")),
            )
        )
        rows = list(rows)
        colours = _colours(s, c.id, list(mine))
        chosen = _chosen(s, c.id)
        return [
            _household(srv, link, mine[link.id], colours[link.id], chosen.get(link.id))
            for link in rows
        ]


def _state(srv, s, c: Caller, link_id: str) -> CopyState:
    mine = _mine(s, c.id)
    link = s.get(Link, link_id)
    if (
        link is None
        or link.deleted
        or link.id not in mine
        or link.state not in ("active", "paused")
    ):
        raise Problem(404, "not-found", "Nothing from this household is shared with you.")
    o = srv.copies.get(link_id, for_person=False)
    who = s.get(User, o.by) if o else None
    left = srv.copies.locks_in(link_id, settings.get(s, "linkReleaseMinutes"))
    return CopyState(
        household=_household(
            srv,
            link,
            mine[link.id],
            _colours(s, c.id, list(mine))[link.id],
            _chosen(s, c.id).get(link.id),
        ),
        hasKey=bool(link.copyPublicKey),
        waiting=len(waiting(srv.config.data_dir, link_id)),
        pulledAt=link.pulledAt,
        unlockedBy=who.displayName if who else None,
        unlockedAt=o.at if o else None,
        locksInSeconds=int(left) if left is not None else None,
    )


@router.get("/linked/{link_id}", response_model=CopyState)
def copy_state(link_id: str, request: Request, c: Caller = Depends(caller)):
    srv = server(request)
    with srv.db.read() as s:
        return _state(srv, s, c, link_id)


@router.post("/linked/{link_id}/unlock", response_model=CopyState)
def unlock(link_id: str, body: Unlock, request: Request, c: Caller = Depends(caller)):
    """The 12 words (S11.9.3.1): checked here, held in memory; nothing reaches the browser."""
    srv = server(request)
    with srv.db.read() as s:
        _state(srv, s, c, link_id)
    try:
        copies.unlock(srv, link_id, c.id, body.words)
    except CopyError as e:
        headers = {"Retry-After": str(int(e.wait) + 1)} if e.wait else None
        status = 429 if e.wait else 422
        raise Problem(status, e.code, e.message, headers=headers) from None
    with srv.db.read() as s:
        return _state(srv, s, c, link_id)


@router.post("/linked/{link_id}/lock", response_model=CopyState)
def lock(link_id: str, request: Request, c: Caller = Depends(caller)):
    """Lock now (S11.9.4.3): anyone the copy shares with."""
    srv = server(request)
    with srv.db.read() as s:
        _state(srv, s, c, link_id)
    copies.lock(srv, link_id, c.id, c.admin)
    with srv.db.read() as s:
        return _state(srv, s, c, link_id)


class ColourRecord(Model):
    """The colour of a linked household's window, for its chooser (S12.10.3.2)."""

    linkId: IdOf("Link")  # type: ignore[valid-type]
    colour: str


def _colour_check(ctx, body: ColourRecord) -> None:
    if body.colour not in PALETTE:
        raise refuse("colour", "colour-invalid", "One of the palette's colours.")
    _state(server(ctx.request), ctx.s, ctx.caller, body.linkId)


def _colour_create(ctx, record_id: str, body: ColourRecord) -> None:
    from ..store.entities.links import LinkColour

    _colour_check(ctx, body)
    have = by_key(ctx.s, LinkColour, userId=ctx.caller.id, linkId=body.linkId)
    if have is not None and not have.deleted:
        raise refuse("linkId", "colour-chosen", "A colour is chosen: change it.", 409)
    ctx.s.add(
        LinkColour(id=record_id, userId=ctx.caller.id, linkId=body.linkId, colour=body.colour)
    )


def _colour_editable(ctx, record_id: str):
    from ..store.entities.links import LinkColour

    row = ctx.s.get(LinkColour, record_id)
    if row is None or row.deleted or row.userId != ctx.caller.id:
        raise Problem(404, "not-found", "Not found")
    return row


def _colour_update(ctx, row, body: ColourRecord) -> None:
    if body.linkId != row.linkId:
        raise refuse("linkId", "colour-fixed", "It stays with its household.")
    _colour_check(ctx, body)
    row.colour = body.colour


def _colour_read(ctx, record_id: str) -> CopyState:
    from ..store.entities.links import LinkColour

    row = ctx.s.get(LinkColour, record_id)
    return _state(server(ctx.request), ctx.s, ctx.caller, row.linkId)


def _colour_register() -> None:
    from ..store.entities.links import LinkColour

    save.register(
        save.Kind(
            prefix="LkCol",
            entity=LinkColour,
            fields=ColourRecord,
            create=_colour_create,
            editable=_colour_editable,
            current=lambda ctx, row: {"linkId": row.linkId, "colour": row.colour},
            update=_colour_update,
            delete=lambda ctx, row: row.mark_deleted(ctx.caller.id),
            read=_colour_read,
        )
    )


_colour_register()


class LinkedRow(Model):
    id: str
    kind: str
    name: str
    ownerName: str
    asOf: str
    row: dict | None  # its row in its list, as its source shows it


# Who viewed linked data (S11.8): at most once an hour for each person and link.
VIEWED_EVERY = 3600
_viewed: dict[tuple[str, str], float] = {}


def _open(srv, s, c: Caller, link_id: str):
    """The unlocked copy, for a read made for this person (it counts as a use)."""
    _state(srv, s, c, link_id)
    o = srv.copies.get(link_id)
    if o is None:
        raise Problem(423, "copy-locked", "This household's copy is locked: enter its access key.")
    _note_viewed(srv, c.id, link_id)
    return o


def _note_viewed(srv, user_id: str, link_id: str) -> None:
    import time

    now = time.monotonic()
    if now - _viewed.get((user_id, link_id), -VIEWED_EVERY) < VIEWED_EVERY:
        return
    _viewed[(user_id, link_id)] = now
    with srv.db.tx() as w:
        activity.record(
            w,
            "link.viewed",
            actor=user_id,
            subject_kind="link",
            subject_id=link_id,
            for_admins=True,
        )


@router.get("/linked/{link_id}/items", response_model=list[LinkedRow])
def items(link_id: str, request: Request, c: Caller = Depends(caller)):
    """What this household shares with you, each with its row (S12.10.3.4)."""
    from ..links import copydb

    srv = server(request)
    with srv.db.read() as s:
        o = _open(srv, s, c, link_id)
    out = []
    with o.engine.connect() as conn:
        rows = {
            r.itemId: exactjson.marked(exactjson.loads(r.body))
            for r in conn.execute(
                select(copydb.Doc).where(copydb.Doc.c.path == "", copydb.Doc.c.viewer == c.id)
            )
        }
        for it in conn.execute(
            select(copydb.Item).order_by(copydb.Item.c.kind, copydb.Item.c.name)
        ):
            if c.id not in json.loads(it.viewers or "[]"):
                continue
            out.append(
                LinkedRow(
                    id=it.id,
                    kind=it.kind,
                    name=it.name,
                    ownerName=it.ownerName,
                    asOf=it.asOf,
                    row=rows.get(it.id),
                )
            )
    return out


@router.get("/linked/{link_id}/doc")
def doc(link_id: str, path: str, request: Request, c: Caller = Depends(caller)):
    """One document of an item shared with you, as its source answered it for you."""
    from ..links import copydb

    srv = server(request)
    with srv.db.read() as s:
        o = _open(srv, s, c, link_id)
    with o.engine.connect() as conn:
        body = conn.execute(
            select(copydb.Doc.c.body).where(copydb.Doc.c.path == path, copydb.Doc.c.viewer == c.id)
        ).scalar()
    if body is None:
        raise Problem(404, "not-shared", "That isn't shared with you, or hasn't arrived yet.")
    # Kept as its source wrote it, exact numbers and all (S13.8.2).
    return Response(content=body, media_type="application/json")


class LinkedFile(Model):
    id: str
    itemId: str
    contentType: str
    length: int
    thumbnail: str | None
    meta: dict  # date, amount, payee, the text read, the transaction
    # False while its file hasn't arrived: asked for again at each exchange (S11.4).
    arrived: bool = True


def _mine_items(conn, user_id: str) -> set[str]:
    from ..links import copydb

    return {
        r.id
        for r in conn.execute(select(copydb.Item.c.id, copydb.Item.c.viewers))
        if user_id in json.loads(r.viewers or "[]")
    }


@router.get("/linked/{link_id}/files", response_model=list[LinkedFile])
def files(link_id: str, request: Request, c: Caller = Depends(caller)):
    """The receipts that crossed with items shared with you (S11.5.1)."""
    from ..links import copydb

    srv = server(request)
    with srv.db.read() as s:
        o = _open(srv, s, c, link_id)
    with o.engine.connect() as conn:
        mine = _mine_items(conn, c.id)
        return [
            LinkedFile(
                id=r.id,
                itemId=r.itemId,
                contentType=r.contentType,
                length=r.length,
                thumbnail=r.thumbnail,
                meta=json.loads(r.meta or "{}"),
                arrived=bool(r.fileName),
            )
            for r in conn.execute(select(copydb.File))
            if r.itemId in mine
        ]


@router.get("/linked/{link_id}/files/{file_id}")
def file(link_id: str, file_id: str, request: Request, c: Caller = Depends(caller)):
    """A receipt, streamed through decryption into the answer: its plain bytes never touch the
    disk, and its hash, signed at the source, is checked as it goes (S11.9.6.4, S11.9.6.5)."""
    import hashlib

    from fastapi.responses import StreamingResponse

    from ..links import copydb, sealed
    from ..links.copy import folder, private_key

    srv = server(request)
    with srv.db.read() as s:
        o = _open(srv, s, c, link_id)
    with o.engine.connect() as conn:
        row = conn.execute(select(copydb.File).where(copydb.File.c.id == file_id)).first()
        if row is None or row.itemId not in _mine_items(conn, c.id):
            raise Problem(404, "not-shared", "That receipt isn't shared with you.")
        if not row.fileName:
            raise Problem(
                404,
                "not-arrived",
                "This receipt hasn't arrived yet: it is asked for again at the next exchange.",
            )
    from .. import receipts
    from ..links.keys import direction, fingerprint, public_of, unb64
    from .receipts import _disposition

    with srv.db.read() as s:
        peer = unb64(s.get(Link, link_id).peerKey)
        # Sealed by its source to this copy's key (S11.9.6), named for that direction.
        way = direction(fingerprint(peer), fingerprint(public_of(s, srv.keys.secrets)))
    path = folder(srv.config.data_dir, link_id) / "receipts" / row.fileName
    priv = private_key(bytes(o.key))
    h = hashlib.sha256()
    f = open(path, "rb")  # noqa: SIM115 - closed when the stream ends
    chunks = sealed.open_sealed(priv, sealed.RECEIPT, way, file_id, f)
    try:
        first = next(chunks, b"")
    except sealed.SealError:
        f.close()
        raise Problem(500, "receipt-unreadable", "The receipt's file can't be opened.") from None
    # Its type found from its bytes, when it arrived and again now, as a local receipt's is
    # (S9.4, S11.9.6.5): anything else is never served, whatever the source called it.
    kind = receipts.sniff(first[:16])
    if kind is None or kind != row.contentType:
        f.close()
        raise Problem(415, "receipt-type", "That file isn't a receipt MoolaKata can show.")
    h.update(first)
    meta = json.loads(row.meta or "{}")
    headers = {
        "Content-Disposition": _disposition(str(meta.get("fileName") or "receipt")),
        "Content-Security-Policy": "sandbox",
        "Cache-Control": "private, no-store",
    }

    def checked():
        # Each piece goes once the next is read, so the last goes only after the hash checks:
        # a file that isn't the one its source sent ends the answer with an error (S11.9.6.5).
        held = first
        try:
            for chunk in chunks:
                h.update(chunk)
                yield held
                held = chunk
        finally:
            f.close()
        if h.hexdigest() != row.sha256:
            raise sealed.SealError("the receipt is not the one its source sent")
        yield held

    if kind == "image/heic":
        data = b"".join(checked())
        from .. import parsing

        try:
            jpeg = parsing.as_jpeg(data)  # decoded in the reader's worker (S9.8.4.2)
        except parsing.ReadError:
            raise Problem(415, "receipt-type", "That photo can't be shown.") from None
        return Response(jpeg, media_type="image/jpeg", headers=headers)

    return StreamingResponse(checked(), media_type=kind, headers=headers)
