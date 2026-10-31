"""Receipts (requirements S9.1–S9.7): files people upload, kept encrypted on disk and written
once, with what is known about them in the database.

- The type is found from the content, never the name: PDF, JPEG, PNG, WebP or HEIC.
- Identical files are stored once, found by their SHA-256: a second upload of the same file
  by the same person gives back the receipt they have; someone else's gets its own receipt
  over the same stored file.
- Thumbnails are made on upload, kept in the (encrypted) database: Pillow for images with
  their EXIF orientation applied, pypdfium2 for a PDF's first page. Images over 40 million
  pixels are refused before they are decoded.
- Who can see a receipt follows what it is attached to (S9.6): its owner always, and whoever
  can read an account one of its transactions is in. An unattached receipt is its owner's
  alone (the inbox).
- A receipt is deleted only by its owner, and only while nothing links to it. Its file stays
  while any receipt row names it, deleted or not (schema.md §4).
"""

import datetime as dt
import hashlib
import io
import logging
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sqlalchemy import and_, exists, false, func, or_, select
from sqlalchemy.orm import Session

from .. import access, clock, ids, settings
from ..checkpoints import checkpoint
from ..errors import Problem, refuse
from ..keys import files
from ..store import scoping
from ..store.entities.accounts import Account, Transaction
from ..store.entities.assets import Item
from ..store.entities.education import QualifiedExpense
from ..store.entities.receipts import Receipt, ReceiptLink
from ..store.rows import by_key
from .ocr import MAX_PIXELS

log = logging.getLogger("moolakata.receipts")

THUMB = 360
MATCH_DAYS = 5
TIP = Decimal("1.25")
TYPES = {
    "application/pdf": "PDF",
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WebP",
    "image/heic": "HEIC",
}


def sniff(head: bytes) -> str | None:
    """The type from the file's first bytes, or None for anything else."""
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    brands = (b"heic", b"heix", b"heim", b"heis", b"mif1", b"msf1")
    if head[4:8] == b"ftyp" and head[8:12] in brands:
        return "image/heic"
    return None


def file_path(receipts_dir: Path, file_id: str) -> Path:
    return receipts_dir / f"{file_id}.mkr"


def _open_image(data: bytes):
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        import pi_heif

        pi_heif.register_heif_opener()
    except ImportError:  # pragma: no cover - always installed
        pass
    img = Image.open(io.BytesIO(data))
    w, h = img.size
    if w * h > MAX_PIXELS:
        raise refuse("file", "image-too-large", "The image is larger than 40 million pixels.")
    return ImageOps.exif_transpose(img)


def thumbnail(data: bytes, media_type: str) -> bytes | None:
    """A small WebP of the image, or of a PDF's first page; None when it can't be drawn."""
    from PIL import Image

    try:
        if media_type == "application/pdf":
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(data)
            try:
                page = pdf[0]
                w, h = page.get_size()
                # Within the pixel cap, whatever size the page claims (S9.8.4.3).
                scale = min(max(THUMB / max(w, h), 0.1), (MAX_PIXELS / max(w * h, 1)) ** 0.5)
                img = page.render(scale=scale).to_pil()
            finally:
                pdf.close()
        else:
            img = _open_image(data)
        img = img.convert("RGB")
        img.thumbnail((THUMB, THUMB), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, "WEBP", quality=80)
        return out.getvalue()
    except Problem:
        raise
    except Exception as e:  # a broken file still uploads; it just has no picture
        log.info("no thumbnail for a %s: %s", media_type, type(e).__name__)
        return None


def _parsing():
    from .. import parsing

    return parsing


def as_jpeg(data: bytes) -> bytes:
    """An iPhone photo (HEIC) as JPEG for the browser, turned the way it was taken."""
    img = _open_image(data).convert("RGB")
    out = io.BytesIO()
    img.save(out, "JPEG", quality=88)
    return out.getvalue()


@dataclass
class Stored:
    receipt: Receipt
    existing: bool


@dataclass
class Prepared:
    """A file made ready to be a receipt, outside any transaction (S9.5): checked, hashed,
    written encrypted and its thumbnail drawn, or found to be one its owner has already."""

    name: str
    media: str
    size: int
    digest: str
    fileId: str | None = None
    thumbnail: bytes | None = None
    existing: str | None = None  # the owner's receipt of the same file


def _media(name: str, data: bytes) -> str:
    media = sniff(data[:16])
    if media is None:
        raise refuse(
            "file",
            "type-not-allowed",
            f"{name}: only PDF, JPEG, PNG, WebP and HEIC files can be receipts.",
            415,
        )
    return media


@contextmanager
def prepared(server, owner_id: str, name: str, data: bytes) -> Iterator[Prepared]:
    """Everything slow about keeping a file, before the transaction that records it (CR3-48):
    the database's write lock is never held while the reader's worker draws a thumbnail or the
    file is written. The file is kept from the orphan sweep until the block ends; `record`
    holds it on until its row is committed, and a row that never commits leaves the file to
    the sweep (S14.6)."""
    media = _media(name, data)
    digest = hashlib.sha256(data).hexdigest()
    store = server.files.of(server.config.receipts_dir)
    with store.writing() as hold:
        # Whether the file is kept already, the owner's or anyone's: the server's to know, to
        # keep one copy.
        with server.db.read(unscoped="receipts: whether a file is kept already") as s:
            mine = s.scalars(
                select(Receipt.id).where(
                    Receipt.sha256 == digest,
                    Receipt.ownerId == owner_id,
                    Receipt.deleted == false(),
                    Receipt.filePrunedAt.is_(None),
                )
            ).first()
            any_file = s.scalars(select(Receipt.fileId).where(Receipt.sha256 == digest)).first()
        if mine is not None:
            yield Prepared(name, media, len(data), digest, existing=mine)
            return
        path = None
        if any_file is not None:
            file_id = any_file
            path = file_path(server.config.receipts_dir, file_id)
            # Reused: held from a prune of the receipt it was another's (S14.10.5), held
            # before it is looked for, until this row is committed.
            hold(path.name)
            checkpoint("receipt.reused")
        if path is None or not path.exists():
            file_id = secrets.token_hex(16)
            path = file_path(server.config.receipts_dir, file_id)
            hold(path.name)
            files.write(
                path,
                (data[i : i + files.CHUNK] for i in range(0, len(data), files.CHUNK)),
                server.keys.receipts.public_key(),
                file_id,
            )
        checkpoint("receipt.written")
        # Drawn in the reader's worker, never here (S9.5, S9.8.4.2); None when it can't be.
        thumb = _parsing().thumbnail(data, media)
        yield Prepared(name, media, len(data), digest, file_id, thumb)


def record(s: Session, server, owner_id: str, p: Prepared) -> Stored:
    """The receipt's row, in the caller's transaction: quick, its file already written."""
    mine = s.scalars(
        select(Receipt).where(
            Receipt.sha256 == p.digest,
            Receipt.ownerId == owner_id,
            Receipt.deleted == false(),
            Receipt.filePrunedAt.is_(None),
        )
    ).first()
    if mine is not None:
        return Stored(mine, True)
    store = server.files.of(server.config.receipts_dir)
    # Kept from the orphan sweep until this row is committed (S9.7).
    store.hold_until_done(s, file_path(server.config.receipts_dir, p.fileId).name)
    r = Receipt(
        id=ids.new_id("Rcpt"),
        ownerId=owner_id,
        fileName=Path(p.name).name[:200] or "receipt",
        mediaType=p.media,
        size=p.size,
        sha256=p.digest,
        fileId=p.fileId,
        thumbnail=p.thumbnail,
        readStatus="waiting" if settings.get(s, "readReceipts") else "off",
    )
    s.add(r)
    s.flush()
    return Stored(r, False)


def read_file(server, r: Receipt) -> Iterator[bytes]:
    """The file's plaintext, streamed through decryption; its hash is checked as it goes."""
    path = file_path(server.config.receipts_dir, r.fileId)
    h = hashlib.sha256()
    for chunk in files.open_stream(path, server.keys.receipts, r.fileId):
        h.update(chunk)
        yield chunk
    if h.hexdigest() != r.sha256:
        raise files.FileError("the receipt's file is not the one uploaded")


def whole(server, r: Receipt) -> bytes:
    return b"".join(read_file(server, r))


# ---------- links and who can see what ----------


def links(s: Session, receipt_id: str) -> list[ReceiptLink]:
    return list(
        s.scalars(
            select(ReceiptLink).where(
                ReceiptLink.receiptId == receipt_id, ReceiptLink.deleted == false()
            )
        )
    )


def on_tax_documents(s: Session, receipt_id: str) -> list:
    from ..store.entities.taxes import TaxDocument

    return list(
        s.scalars(
            select(TaxDocument).where(
                TaxDocument.receiptId == receipt_id, TaxDocument.deleted == false()
            )
        )
    )


def kept_with(s: Session, receipt_id: str) -> int:
    """How many things a receipt is kept with, whoever reads them: its live links to live
    records, counted as the server and never named (S9.3)."""
    from ..store import views
    from ..store.entities.education import Gift
    from ..store.entities.giving import Donation
    from ..store.tables import metadata

    rl = metadata.tables["ReceiptLink"]
    live = views.view_table(rl)
    found = []
    for kind, entity in (
        ("transaction", Transaction),
        ("account", Account),
        ("item", Item),
        ("expense", QualifiedExpense),
        ("gift", Gift),
        ("donation", Donation),
    ):
        t = views.view_table(entity.__mapper__.local_table)
        found.append(
            and_(
                rl.c.kind == kind,
                exists().where(t.c.id == rl.c.itemId, t.c.effectiveDeleted == false()),
            )
        )
    q = (
        select(func.count())
        .select_from(rl)
        .join(live, live.c.id == rl.c.id)
        .where(rl.c.receiptId == receipt_id, live.c.effectiveDeleted == false(), or_(*found))
    )
    return s.scalar(scoping.unscoped(q, "how many things a receipt is kept with"))


def level_for(s: Session, user_id: str, r: Receipt) -> str | None:
    """The user's level on a receipt as the API names it (ReceiptAccess), or None."""
    p = access.perms(s, Receipt, r.id, user_id)
    return None if p is None else p.level(access.RECORD_OWNER)


def get(s: Session, user_id: str, receipt_id: str, need: str = "read") -> tuple[Receipt, str]:
    """`need`: *read*, *write*, or a permission's name (deleting it: *deletable*)."""
    p = access.perms(s, Receipt, receipt_id, user_id)
    r = s.get(Receipt, receipt_id) if p is not None else None
    if r is None:
        raise Problem(404, "not-found", "Not found")
    want = {"read": None, "write": "writable"}.get(need, need)
    if want is not None and not getattr(p, want):
        raise Problem(403, "owner-only", "Only the receipt's owner can do this.")
    return r, p.level(access.RECORD_OWNER)


def to_attach(s: Session, user_id: str, receipt_id: str, field: str = "receiptId") -> Receipt:
    """A receipt this user may attach to something: its owner's, or one they write to through
    what it is attached to. A read share shows a receipt and attaches it nowhere (S9.6)."""
    r, lvl = get(s, user_id, receipt_id)
    if lvl not in ("owner", "write"):
        raise refuse(
            field,
            "receipt-read-only",
            "That receipt is shared with you to read: it can't be attached to anything else.",
            403,
        )
    return r


def visible(s: Session, user_id: str) -> list[tuple[Receipt, str]]:
    """The receipts the user reads (ReceiptAccess): their own, and those kept with what they
    read."""
    return [
        (r, p.level(access.RECORD_OWNER))
        for r, p in access.listing(s, Receipt, user_id, order_by=Receipt.createdAt)
    ]


# What a link of each kind names, by the prefix of its id (schema.md §3).
TARGETS = {
    "transaction": "Txn",
    "account": "Acct",
    "item": "Item",
    "expense": "QExpn",
    "gift": "Gift",
    "donation": "Dnatn",
}


def _account_of(s: Session, ln: ReceiptLink) -> Account | None:
    """The live account a link's transaction, item or expense is in, or its account."""
    if ln.kind == "account":
        a = s.get(Account, ln.itemId)
    else:
        entity = {"transaction": Transaction, "item": Item, "expense": QualifiedExpense}[ln.kind]
        x = s.get(entity, ln.itemId)
        a = s.get(Account, x.accountId) if x is not None and not x.deleted else None
    return a if a is not None and not a.deleted else None


def target(s: Session, user_id: str, kind: str, item_id: str) -> access.Perms | None:
    """The user's permissions on what a link of this kind names, while it is there (S9.6),
    from its own access view."""
    from ..store.entities.education import Gift
    from ..store.entities.giving import Donation

    entity = {
        "transaction": Transaction,
        "account": Account,
        "item": Item,
        "expense": QualifiedExpense,
        "gift": Gift,
        "donation": Donation,
    }[kind]
    return access.perms(s, entity, item_id, user_id)


def can_unlink(s: Session, user_id: str, ln: ReceiptLink) -> bool:
    """Whoever can change what a receipt is kept with can detach it from that (S9.3)."""
    p = target(s, user_id, ln.kind, ln.itemId)
    return p is not None and p.writable


def link(s: Session, user_id: str, r: Receipt, kind: str, item_id: str, link_id: str):
    """A draft's link (S13.8.11): onto what the user can change, once (S9.3)."""
    ln = ReceiptLink(
        id=link_id,
        receiptId=r.id,
        kind=kind,
        itemId=item_id,
        createdAt=clock.now(),
        linkedById=user_id,
    )
    p = target(s, user_id, kind, item_id)
    if p is None:
        raise refuse("itemId", "not-found", "That is not there.", 404)
    if not p.writable:
        raise refuse("itemId", "read-only", "That is shared with you to read.", 403)
    have = by_key(s, ReceiptLink, receiptId=r.id, kind=kind, itemId=item_id)
    if have is not None and not have.deleted:
        raise refuse("itemId", "already-attached", "The receipt is attached to that already.", 409)
    s.add(ln)
    s.flush()
    return ln


def unlink(s: Session, user_id: str, ln: ReceiptLink) -> None:
    """A link taken away by whoever can change what it names, or, once that is gone, by the
    receipt's owner."""
    p = target(s, user_id, ln.kind, ln.itemId)
    owner = s.scalars(
        scoping.unscoped(
            select(Receipt.ownerId).where(Receipt.id == ln.receiptId), "a receipt's owner"
        )
    ).first()
    if p is None and owner != user_id:
        raise Problem(404, "not-found", "Not found")
    if p is not None and not p.writable:
        raise Problem(403, "read-only", "Only who can change it can take its receipt away.")
    ln.mark_deleted(user_id, clock.now())


def attach_account(s: Session, user_id: str, r: Receipt, account_id: str) -> None:
    """A statement kept as a receipt on its account (S1.3.3)."""
    access.account(s, user_id, account_id, "write")
    if by_key(s, ReceiptLink, receiptId=r.id, kind="account", itemId=account_id) is None:
        s.add(
            ReceiptLink(
                receiptId=r.id,
                kind="account",
                itemId=account_id,
                createdAt=clock.now(),
                linkedById=user_id,
            )
        )
        s.flush()


def attach_item(s: Session, user_id: str, r: Receipt, item, kind: str = "item") -> None:
    """A photo or document of a physical-asset item (S1.10.1), or a qualified expense's
    receipt (S1.8.3): kept with it, in the item's account."""
    access.account(s, user_id, item.accountId, "write")
    row = by_key(s, ReceiptLink, receiptId=r.id, kind=kind, itemId=item.id)
    if row is None:
        s.add(
            ReceiptLink(
                receiptId=r.id,
                kind=kind,
                itemId=item.id,
                createdAt=clock.now(),
                linkedById=user_id,
            )
        )
    elif row.deleted:
        row.restore()
    s.flush()


def detach_item(s: Session, user_id: str, r: Receipt, item, kind: str = "item") -> None:
    access.account(s, user_id, item.accountId, "write")
    row = by_key(s, ReceiptLink, receiptId=r.id, kind=kind, itemId=item.id)
    if row is None or row.deleted:
        raise Problem(404, "not-found", "The receipt is not kept with that.")
    row.mark_deleted(user_id, clock.now())


def of_item(s: Session, item_id: str, kind: str = "item") -> list[Receipt]:
    return list(
        s.scalars(
            select(Receipt)
            .join(ReceiptLink, ReceiptLink.receiptId == Receipt.id)
            .where(
                ReceiptLink.kind == kind,
                ReceiptLink.itemId == item_id,
                ReceiptLink.deleted == false(),
                Receipt.deleted == false(),
            )
            .order_by(Receipt.createdAt)
        )
    )


def detach_kept(s: Session, user_id: str, r: Receipt, kind: str, item_id: str) -> None:
    """A receipt's link to a gift or a donation, by someone who can change that (S9.6)."""
    row = by_key(s, ReceiptLink, receiptId=r.id, kind=kind, itemId=item_id)
    if row is None or row.deleted or kind not in ("gift", "donation"):
        raise Problem(404, "not-found", "The receipt is not kept with that.")
    held = target(s, user_id, kind, item_id)
    if held is None or not held.writable:
        raise Problem(403, "read-only", "Only who can change it can take its receipt away.")
    row.mark_deleted(user_id, clock.now())


def keep_set(s: Session, user_id: str, kind: str, item_id: str, was, now) -> None:
    """The receipts kept with a gift or a donation, as its draft's set (S9.6): those added are
    attached, those taken away detached."""
    for receipt_id in sorted(set(now) - set(was)):
        r = to_attach(s, user_id, receipt_id, "receiptIds")
        row = by_key(s, ReceiptLink, receiptId=r.id, kind=kind, itemId=item_id)
        if row is None:
            s.add(
                ReceiptLink(
                    receiptId=r.id,
                    kind=kind,
                    itemId=item_id,
                    createdAt=clock.now(),
                    linkedById=user_id,
                )
            )
        elif row.deleted:
            row.restore()
    for receipt_id in sorted(set(was) - set(now)):
        r, _ = get(s, user_id, receipt_id)
        detach_kept(s, user_id, r, kind, item_id)


def delete(s: Session, user_id: str, r: Receipt) -> None:
    if links(s, r.id) or on_tax_documents(s, r.id):
        raise refuse(
            None,
            "receipt-linked",
            "Detach it from everything first: a receipt is deleted only when nothing links to it.",
            409,
        )
    r.mark_deleted(user_id)


def receipts_of(s: Session, transaction_ids: list[str]) -> dict[str, list[str]]:
    """Per transaction, the ids of the receipts attached to it."""
    out: dict[str, list[str]] = {}
    for chunk in range(0, len(transaction_ids), 500):
        for ln in s.scalars(
            select(ReceiptLink)
            .join(Receipt, Receipt.id == ReceiptLink.receiptId)
            .where(
                ReceiptLink.kind == "transaction",
                ReceiptLink.itemId.in_(transaction_ids[chunk : chunk + 500]),
                ReceiptLink.deleted == false(),
                Receipt.deleted == false(),
            )
        ):
            out.setdefault(ln.itemId, []).append(ln.receiptId)
    return out


# ---------- suggestions (S9.3, S9.8.2.6) ----------


@dataclass
class Match:
    transaction: Transaction
    account: Account
    score: float


def matches(s: Session, user_id: str, r: Receipt, limit: int = 3) -> list[Match]:
    """Transactions in accounts the user can write to with the receipt's amount, within 5 days
    of its date; one up to 25% larger matches too, for a tip added after it was printed.
    Ranked by days apart, then by how alike the payees are."""
    if r.amount is None:
        return []
    amount = abs(r.amount)
    day = r.date or r.createdAt.date()
    writable = [a for a, p in access.accounts(s, user_id) if p.writable]
    by_id = {a.id: a for a in writable}
    if not by_id:
        return []
    rows = s.scalars(
        select(Transaction).where(
            Transaction.accountId.in_(list(by_id)),
            Transaction.deleted == false(),
            Transaction.date >= day - dt.timedelta(days=MATCH_DAYS),
            Transaction.date <= day + dt.timedelta(days=MATCH_DAYS),
        )
    ).all()
    linked = {ln.itemId for ln in links(s, r.id)}
    out = []
    for t in rows:
        paid = abs(t.amount)
        if t.id in linked or not (amount <= paid <= amount * TIP):
            continue
        days = abs((t.date - day).days)
        score = days + (0 if paid == amount else 2) - _alike(r.payee, t.payee)
        out.append(Match(t, by_id[t.accountId], score))
    return sorted(out, key=lambda m: m.score)[:limit]


def _alike(a: str | None, b: str | None) -> float:
    """0 to 1: how many of the shorter name's words the other has."""
    if not a or not b:
        return 0.0
    wa = {w for w in a.lower().split() if len(w) > 2}
    wb = {w for w in b.lower().split() if len(w) > 2}
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))
