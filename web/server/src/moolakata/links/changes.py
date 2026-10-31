"""Changes to a linked copy (requirements S11.4, S11.9.5, link-protocol.md §4.4): each signed by
its source's link key, its contents sealed by the source to the copy's key, kept in the copy's
inbox as they came whether or not the copy is unlocked, and applied in order, in one
transaction, once it is, with every signature checked again first.

A change is JSON with two parts. The **registry**, which the receiving server keeps in its main
database: its sequence number at the source (`seq`), its time (`asOf`), whether it replaces the
whole copy (`full`), the items it adds or changes without their names (`items`), those removed
(`removed`), how far a large change has come (`progress`) and the ids of the receipts it sends
(`fetch`). And `sealed`, the rest, which only the copy opens: each item's name, its documents
and files, and what they remove. `signature` is Ed25519 over the registry and the SHA-256 of
`sealed`, as canonical JSON (keys sorted, no spaces)."""

import contextlib
import datetime as dt
import hashlib
import json
import re
import shutil

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from sqlalchemy import delete, func, select

from .. import clock, exactjson
from ..checkpoints import checkpoint
from ..store.entities.links import Link
from . import copydb, sealed
from .copy import folder, private_key
from .keys import b64, unb64

MAX_CHANGES = 1000
MAX_BYTES = 500 * 1024 * 1024


class ChangeError(Exception):
    pass


REGISTRY = ("seq", "asOf", "full", "items", "removed", "progress", "fetch")
CONTENTS = ("names", "docs", "docsRemoved", "files", "filesRemoved")


def _canonical(change: dict) -> bytes:
    body = {k: v for k, v in change.items() if k not in ("signature", "sealed")}
    if change.get("sealed"):
        body["sealed"] = hashlib.sha256(unb64(change["sealed"])).hexdigest()
    return exactjson.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def seal_part(part: dict, copy_key: bytes | None, direction: str) -> dict:
    """A change as it travels: its registry in the open, and the rest sealed to the receiving
    copy's key, or left out when that copy has no key yet."""
    out = {k: part[k] for k in REGISTRY if k in part}
    out["items"] = [{k: v for k, v in it.items() if k != "name"} for it in part.get("items") or []]
    out["fetch"] = [f["id"] for f in part.get("files") or []] if copy_key else []
    if copy_key:
        inner = {k: part.get(k) or [] for k in CONTENTS if k != "names"}
        inner["names"] = {it["id"]: it.get("name") or "" for it in part.get("items") or []}
        raw = exactjson.dumps(inner, separators=(",", ":")).encode()
        out["sealed"] = b64(
            b"".join(sealed.seal(copy_key, sealed.CHANGE, direction, str(part["seq"]), [raw]))
        )
    return out


def open_part(private, change: dict, direction: str, raw_sealed: bytes) -> dict:
    """A change's sealed contents, opened with the copy's key, merged with its registry: names
    back on their items."""
    import io

    inner = exactjson.loads(
        b"".join(
            sealed.open_sealed(
                private, sealed.CHANGE, direction, str(change.get("seq")), io.BytesIO(raw_sealed)
            )
        )
    )
    names = inner.get("names") or {}
    out = {**change, **{k: inner.get(k) or [] for k in CONTENTS if k != "names"}}
    out["items"] = [{**it, "name": names.get(it["id"], "")} for it in change.get("items") or []]
    return out


def sign(key: Ed25519PrivateKey, change: dict) -> dict:
    return {**change, "signature": b64(key.sign(_canonical(change)))}


def verify(public: bytes, change: dict) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(public).verify(
            unb64(change.get("signature", "")), _canonical(change)
        )
    except InvalidSignature, ValueError:
        raise ChangeError(f"change {change.get('seq')} fails its signature check") from None


def inbox(data_dir, link_id: str):
    return folder(data_dir, link_id) / "inbox"


def waiting(data_dir, link_id: str) -> list:
    d = inbox(data_dir, link_id)
    return sorted(d.glob("*.mks")) if d.exists() else []


def enqueue(srv, link_id: str, change: dict, local: dict | None = None) -> bool:
    """Keep a signed change's sealed part in the inbox as it came, beside its registry and
    what this side added (the random names its receipts were written under); apply it at once
    if the copy is unlocked. Returns False when the inbox overflowed and was discarded: the
    next pull asks for everything."""
    with srv.db.read() as s:
        link = s.get(Link, link_id)
        has_key = bool(link and link.copyPublicKey)
    if not has_key or not change.get("sealed"):
        return True  # no copy yet: nothing is kept until its access key is made
    d = inbox(srv.config.data_dir, link_id)
    d.mkdir(parents=True, exist_ok=True)
    have = waiting(srv.config.data_dir, link_id)
    seq = int(have[-1].stem) + 1 if have else 1
    name = f"{seq:010d}"
    registry = {k: v for k, v in change.items() if k != "sealed"}
    entry = exactjson.dumps({"change": registry, "local": local or {}}, separators=(",", ":"))
    sealed.write(d / f"{name}.json", [entry.encode()])
    sealed.write(d / f"{name}.mks", [unb64(change["sealed"])])
    have = waiting(srv.config.data_dir, link_id)
    if len(have) > MAX_CHANGES or sum(p.stat().st_size for p in have) > MAX_BYTES:
        for p in have:
            p.unlink(missing_ok=True)
            p.with_suffix(".json").unlink(missing_ok=True)
        with srv.db.tx() as s:
            row = s.get(Link, link_id)
            row.needsFull, row.inboxAsOf = True, None
        return False
    with srv.db.tx() as s:
        row = s.get(Link, link_id)
        row.inboxAsOf = _as_of(change) or row.inboxAsOf
    if srv.copies.get(link_id, for_person=False) is not None:
        apply(srv, link_id)
    return True


def _as_of(change: dict) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(change["asOf"])
    except KeyError, ValueError, TypeError:
        return None


def apply(srv, link_id: str) -> int:
    """Apply the inbox to the unlocked copy: every change opened and its signature checked,
    then all of them in one transaction; applied files are deleted. A change that fails stops
    the apply and is reported on the link."""
    o = srv.copies.get(link_id, for_person=False)
    if o is None:
        return 0
    files = waiting(srv.config.data_dir, link_id)
    if not files:
        return 0
    from .keys import direction, fingerprint, public_of

    with srv.db.read() as s:
        peer = unb64(s.get(Link, link_id).peerKey)
        way = direction(fingerprint(peer), fingerprint(public_of(s, srv.keys.secrets)))
    priv = private_key(bytes(o.key))
    with o.engine.connect() as conn:
        last = conn.execute(select(func.max(copydb.Applied.c.seq))).scalar() or 0
    changes = []
    try:
        for p in files:
            entry = exactjson.loads(p.with_suffix(".json").read_bytes())
            raw = p.read_bytes()
            change, local = entry["change"], entry.get("local") or {}
            verify(peer, {**change, "sealed": b64(raw)})
            # Each must follow the last applied, so an older change put back is refused: the
            # sequence is the source's, signed and sealed with the change (S11.9.5.3).
            seq = int(change.get("seq") or 0)
            if seq <= last:
                raise ChangeError(
                    f"change {seq} doesn't follow the last one applied ({last}); if the other "
                    "server was restored from a backup, reset the copy"
                )
            last = seq
            opened = open_part(priv, change, way, raw)
            _shape(opened)
            changes.append((opened, local))
            checkpoint("apply.opened")
    except (
        sealed.SealError,
        ChangeError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        OSError,
    ) as e:
        # Nothing of the inbox is applied: it is set aside, the failure recorded on the link,
        # and the next pull asks for everything (S11.9.5.3).
        aside = folder(srv.config.data_dir, link_id) / "set-aside"
        shutil.rmtree(aside, ignore_errors=True)
        aside.mkdir(parents=True, exist_ok=True)
        for f in files:
            for part in (f, f.with_suffix(".json")):
                with contextlib.suppress(OSError):
                    part.rename(aside / part.name)
        with srv.db.tx() as s:
            row = s.get(Link, link_id)
            row.lastError = f"A pulled change can't be applied, so everything is asked for: {e}"
            row.needsFull, row.inboxAsOf = True, None
        raise ChangeError(str(e)) from None
    receipts_dir = folder(srv.config.data_dir, link_id) / "receipts"
    lost: list[str] = []
    with o.engine.begin() as conn:
        for change, local in changes:
            names = local.get("fileNames") or {}
            # A receipt whose file is gone (whatever took it) is one not yet arrived, asked
            # for again (S11.4), never a row naming a file that isn't there.
            lost += [fid for fid, n in names.items() if not (receipts_dir / n).is_file()]
            names = {fid: n for fid, n in names.items() if (receipts_dir / n).is_file()}
            types = {fid: _type_of(priv, way, fid, receipts_dir / n) for fid, n in names.items()}
            for name in _apply_one(conn, change, names, types):
                (receipts_dir / name).unlink(missing_ok=True)
            conn.execute(
                copydb.Applied.insert().prefix_with("OR REPLACE"),
                {"seq": int(change.get("seq") or 0), "appliedAt": clock.now().isoformat()},
            )
    for p in files:
        p.unlink(missing_ok=True)
        p.with_suffix(".json").unlink(missing_ok=True)
    with srv.db.tx() as s:
        s.get(Link, link_id).inboxAsOf = None
        from ..store.entities.links import LinkFile
        from .receive import _missing

        for fid in lost:
            if _missing(s, link_id, fid) is None:
                s.add(LinkFile(linkId=link_id, fileId=fid, missedAt=clock.now()))
    from .receive import place_arrived

    place_arrived(srv, link_id)
    return len(changes)


def _shape(c: dict) -> None:
    """A change's shape, checked before any of it is applied: a signed change that isn't one
    is refused here, never part-way through the copy's transaction (S11.9.5.3)."""

    def texts(v) -> bool:
        return isinstance(v, list) and all(isinstance(x, str) for x in v)

    def rows(v, *keys: str) -> bool:
        return isinstance(v, list) and all(
            isinstance(x, dict) and all(isinstance(x.get(k), str) for k in keys) for x in v
        )

    def whole(v) -> bool:
        return v is None or (isinstance(v, int) and not isinstance(v, bool))

    ok = (
        whole(c.get("seq"))
        and texts(c.get("removed") or [])
        and rows(c.get("items") or [], "id", "kind")
        and all(whole(it.get("version")) for it in c.get("items") or [])
        and rows(c.get("docsRemoved") or [], "itemId", "path", "viewer")
        and rows(c.get("docs") or [], "itemId", "path", "viewer")
        and all("body" in d for d in c.get("docs") or [])
        and all(
            isinstance(d["body"], dict) and isinstance(d["body"].get("items"), list)
            for d in c.get("docs") or []
            if d.get("append")
        )
        and texts(c.get("filesRemoved") or [])
        and rows(c.get("files") or [], "id", "itemId", "sha256")
        and all(whole(f.get("length")) for f in c.get("files") or [])
    )
    if not ok:
        raise ChangeError(f"change {c.get('seq')} isn't in the shape of a change")


def _type_of(private, way: str, file_id: str, path) -> str:
    """A linked receipt's type, from its first bytes once the copy opens them, never from what
    the change calls it (S11.9.6.5); one that isn't a receipt's type is unknown, and never
    shown."""
    from ..receipts import sniff

    try:
        with open(path, "rb") as f:
            first = next(sealed.open_sealed(private, sealed.RECEIPT, way, file_id, f), b"")
    except OSError, sealed.SealError:
        return "application/octet-stream"
    return sniff(first[:16]) or "application/octet-stream"


def received_type(srv, o, link_id: str, file_id: str, path) -> str:
    """`_type_of` for a receipt that arrived after its change, the copy `o` open."""
    from .keys import direction, fingerprint, public_of

    with srv.db.read() as s:
        peer = unb64(s.get(Link, link_id).peerKey)
        way = direction(fingerprint(peer), fingerprint(public_of(s, srv.keys.secrets)))
    return _type_of(private_key(bytes(o.key)), way, file_id, path)


def _apply_one(conn, c: dict, names: dict[str, str], types: dict[str, str]) -> list[str]:
    """Apply one change; returns the sealed files it leaves unnamed, to delete."""
    gone: list[str] = []
    if c.get("full"):
        gone += list(conn.execute(select(copydb.File.c.fileName)).scalars())
        for t in (copydb.Doc, copydb.File, copydb.Item):
            conn.execute(delete(t))
    for item_id in c.get("removed") or []:
        conn.execute(delete(copydb.Doc).where(copydb.Doc.c.itemId == item_id))
        conn.execute(delete(copydb.File).where(copydb.File.c.itemId == item_id))
        conn.execute(delete(copydb.Item).where(copydb.Item.c.id == item_id))
    for it in c.get("items") or []:
        conn.execute(delete(copydb.Item).where(copydb.Item.c.id == it["id"]))
        conn.execute(
            copydb.Item.insert(),
            {
                "id": it["id"],
                "kind": it["kind"],
                "name": it.get("name") or "",
                "ownerName": it.get("ownerName") or "",
                "viewers": json.dumps(it.get("viewers") or []),
                "version": int(it.get("version") or 0),
                "asOf": it.get("asOf") or c.get("asOf") or "",
            },
        )
    for d in c.get("docsRemoved") or []:
        conn.execute(
            delete(copydb.Doc).where(
                copydb.Doc.c.itemId == d["itemId"],
                copydb.Doc.c.path == d["path"],
                copydb.Doc.c.viewer == d["viewer"],
            )
        )
    for d in c.get("docs") or []:
        body = d["body"]
        if d.get("append"):
            # A later piece of a long list (S11.4): its records go ahead of the older ones.
            had = conn.execute(
                select(copydb.Doc.c.body).where(
                    copydb.Doc.c.itemId == d["itemId"],
                    copydb.Doc.c.path == d["path"],
                    copydb.Doc.c.viewer == d["viewer"],
                )
            ).scalar()
            before = exactjson.loads(had) if had else {}
            body = {**before, **body, "items": body["items"] + (before.get("items") or [])}
        conn.execute(
            copydb.Doc.insert().prefix_with("OR REPLACE"),
            {
                "itemId": d["itemId"],
                "path": d["path"],
                "viewer": d["viewer"],
                "body": exactjson.dumps(body, separators=(",", ":")),
            },
        )
    for fid in c.get("filesRemoved") or []:
        gone += list(
            conn.execute(select(copydb.File.c.fileName).where(copydb.File.c.id == fid)).scalars()
        )
        conn.execute(delete(copydb.File).where(copydb.File.c.id == fid))
    for f in c.get("files") or []:
        if f["id"] not in names:
            # Not arrived (S11.4): its row waits for the file, which is asked for again at each
            # exchange; one already here stays as it is.
            had = conn.execute(select(copydb.File.c.id).where(copydb.File.c.id == f["id"]))
            if had.first() is None:
                conn.execute(
                    copydb.File.insert(),
                    {
                        "id": f["id"],
                        "itemId": f["itemId"],
                        "fileName": "",
                        "contentType": "application/octet-stream",
                        "length": int(f.get("length") or 0),
                        "sha256": f["sha256"],
                        "thumbnail": _thumbnail(f.get("thumbnail")),
                        "meta": json.dumps(f.get("meta") or {}),
                    },
                )
            continue
        gone += list(
            conn.execute(
                select(copydb.File.c.fileName).where(copydb.File.c.id == f["id"])
            ).scalars()
        )
        conn.execute(
            copydb.File.insert().prefix_with("OR REPLACE"),
            {
                "id": f["id"],
                "itemId": f["itemId"],
                "fileName": names[f["id"]],
                # Found from its bytes as it arrived, never the type the change names.
                "contentType": types.get(f["id"], "application/octet-stream"),
                "length": int(f.get("length") or 0),
                "sha256": f["sha256"],
                "thumbnail": _thumbnail(f.get("thumbnail")),
                "meta": json.dumps(f.get("meta") or {}),
            },
        )
    # A row whose file never arrived ("") has none to delete.
    return [g for g in gone if g and g not in names.values()]


THUMBNAIL = re.compile(r"data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/]+=*")


def _thumbnail(value) -> str | None:
    """A thumbnail from the source, kept only as an image's data URL (S11.9.6.5)."""
    if isinstance(value, str) and len(value) < 1_000_000 and THUMBNAIL.fullmatch(value):
        return value
    return None


def orphans(srv, link_id: str) -> int:
    """Remove files no row names, left behind after a crash (S11.9.6.6); needs the copy open.
    Temporary files go whether or not it is."""
    base = folder(srv.config.data_dir, link_id)
    gone = 0
    for p in list(base.rglob("*.tmp")):
        p.unlink(missing_ok=True)
        gone += 1
    o = srv.copies.get(link_id, for_person=False)
    if o is None or not (base / "receipts").exists():
        return gone
    with o.engine.connect() as conn:
        named = set(conn.execute(select(copydb.File.c.fileName)).scalars())
    for p in (base / "receipts").glob("*.mkr"):
        if p.name not in named:
            p.unlink(missing_ok=True)
            gone += 1
    return gone
