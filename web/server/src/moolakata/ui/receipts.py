"""Receipts (requirements S9.1–S9.7): upload, the list and inbox, a receipt's fields and links,
its file and thumbnail, and the transactions it may belong to."""

import datetime as dt
import json
import logging
import urllib.parse
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import Field

from .. import access, activity, clock, exactjson, ids, parsing, receipts, settings, tags
from ..access import Perms
from ..errors import Problem, new_error_id, refuse
from ..keys.files import FileError
from ..receipts import reading, retention
from ..store import scoping
from ..store.entities.accounts import Account, Transaction
from ..store.entities.assets import Item
from ..store.entities.education import QualifiedExpense
from ..store.entities.receipts import Receipt, ReceiptLink
from ..store.entities.users import User
from . import save
from .conventions import Access, ExactRoute, IdOf, Model, Money
from .deps import Caller, caller, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["receipts"])
log = logging.getLogger("moolakata.receipts")


class LinkOut(Model):
    """A transaction it supports, the account it is kept on (a statement), or what else it is
    kept with: an item, a qualified expense, a gift, a donation, a tax document. `id` and
    `version` are the link's own (`ReceiptLink`); a tax document's file has none."""

    id: str | None
    version: int | None
    kind: str  # transaction, account, item, expense, gift, donation, tax-document
    itemId: str
    transactionId: str | None
    accountId: str | None
    accountName: str | None
    date: dt.date | None
    amount: Money | None
    payee: str | None
    label: str  # how it is named in the receipt's dialog
    canDetach: bool = False


class ReceiptRow(Model):
    id: str
    fileName: str
    mediaType: str
    size: int
    uploadedAt: dt.datetime
    ownerId: str
    ownerName: str
    access: Access
    date: dt.date | None
    amount: Money | None
    payee: str | None
    notes: str | None
    tags: list[str]  # the reader's own, by name (S2.6)
    tagIds: list[str]
    links: list[LinkOut]
    # What else it is kept with that this reader can't read: counted, never named (S9.3).
    alsoKeptWith: int
    hasThumbnail: bool
    readStatus: str
    readError: str | None
    filled: list[str]
    keep: bool  # kept for ever, whatever its retention (S14.10.1.3)
    filePrunedAt: dt.datetime | None  # its file removed by file pruning (S14.10.5)
    version: int


class Suggested(Model):
    """A field read from the receipt, with how sure the reader was (0–100)."""

    value: str
    confidence: int


class Suggestion(Model):
    transactionId: str
    accountName: str
    date: dt.date
    amount: Money
    payee: str | None


class ReceiptDetail(ReceiptRow):
    matches: list[Suggestion]
    text: str | None
    suggested: dict[str, Suggested]
    readMethod: str | None
    readEngine: str | None
    readAt: dt.datetime | None
    kept: str  # Kept until Mar 2031, Kept while the lot is open, Kept for ever (S14.10.3)
    keptState: str  # forever, open, until, expired, pruned
    keptUntil: dt.date | None
    keptSoon: bool  # within 90 days
    keptWhy: str | None  # Groceries keeps receipts 3 years


def _own(s, ln, user_id: str | None) -> dict:
    """A link's id and version, and whether this user may detach it (S9.3)."""
    can = user_id is not None and receipts.can_unlink(s, user_id, ln)
    return {"id": ln.id, "version": ln.version, "canDetach": can}


def _links(s, r: Receipt, user_id: str | None = None) -> list[LinkOut]:
    from ..store.entities.education import Gift
    from ..store.entities.giving import Donation, Organisation
    from ..store.entities.taxes import TaxBook

    out = []
    for ln in receipts.links(s, r.id):
        if ln.kind in ("item", "expense"):
            it = s.get(Item if ln.kind == "item" else QualifiedExpense, ln.itemId)
            a = s.get(Account, it.accountId) if it is not None and not it.deleted else None
            if a is not None and not a.deleted:
                name = it.name if ln.kind == "item" else (it.description or "Expense")
                out.append(
                    LinkOut(
                        **_own(s, ln, user_id),
                        kind=ln.kind,
                        itemId=ln.itemId,
                        transactionId=None,
                        accountId=a.id,
                        accountName=a.name,
                        date=None,
                        amount=None,
                        payee=name,
                        label=f"{name} in {a.name}",
                    )
                )
            continue
        if ln.kind == "account":
            a = s.get(Account, ln.itemId)
            if a is not None and not a.deleted:
                out.append(
                    LinkOut(
                        **_own(s, ln, user_id),
                        kind="account",
                        itemId=a.id,
                        transactionId=None,
                        accountId=a.id,
                        accountName=a.name,
                        date=None,
                        amount=None,
                        payee="Statement",
                        label=f"The statement of {a.name}",
                    )
                )
            continue
        if ln.kind in ("gift", "donation"):
            thing = s.get(Gift if ln.kind == "gift" else Donation, ln.itemId)
            if thing is None or thing.deleted:
                continue
            if ln.kind == "gift":
                label = f"The gift {thing.description}"
                when, amount = None, thing.cost
            else:
                org = s.get(Organisation, thing.organisationId) if thing.organisationId else None
                label = f"The donation to {org.name if org else thing.description or 'a cause'}"
                when, amount = thing.date, thing.amount
            out.append(
                LinkOut(
                    **_own(s, ln, user_id),
                    kind=ln.kind,
                    itemId=ln.itemId,
                    transactionId=None,
                    accountId=None,
                    accountName=None,
                    date=when,
                    amount=amount,
                    payee=None,
                    label=label,
                )
            )
            continue
        t = s.get(Transaction, ln.itemId)
        if t is None or t.deleted:
            continue
        a = s.get(Account, t.accountId)
        out.append(
            LinkOut(
                **_own(s, ln, user_id),
                kind="transaction",
                itemId=t.id,
                transactionId=t.id,
                accountId=a.id,
                accountName=a.name,
                date=t.date,
                amount=t.amount,
                payee=t.payee,
                label=t.payee or "Transaction",
            )
        )
    for doc in receipts.on_tax_documents(s, r.id):
        book = s.get(TaxBook, doc.bookId)
        if book is None or book.deleted:
            continue
        out.append(
            LinkOut(
                id=None,
                version=None,
                kind="tax-document",
                itemId=doc.id,
                transactionId=None,
                accountId=None,
                accountName=None,
                date=None,
                amount=None,
                payee=doc.issuer,
                label=f"{doc.form} in the {book.year} tax book",
            )
        )
    return out


def row(s, r: Receipt, held: Perms, user_id: str | None = None) -> ReceiptRow:
    owner = s.get(User, r.ownerId)
    tagged = tags.of(s, "receipt", user_id, [r.id]).get(r.id, []) if user_id else []
    links = _links(s, r, user_id)
    return ReceiptRow(
        id=r.id,
        fileName=r.fileName,
        mediaType=r.mediaType,
        size=r.size,
        uploadedAt=r.createdAt,
        ownerId=r.ownerId,
        ownerName=owner.displayName if owner else "",
        access=Access.of(held),
        date=r.date,
        amount=r.amount,
        payee=r.payee,
        notes=r.notes,
        tags=[t.name for t in tagged],
        tagIds=[t.id for t in tagged],
        links=links,
        alsoKeptWith=max(
            0, receipts.kept_with(s, r.id) - sum(x.kind != "tax-document" for x in links)
        ),
        hasThumbnail=r.thumbnail is not None,
        readStatus=r.readStatus,
        readError=r.readError,
        filled=json.loads(r.filled or "[]"),
        keep=r.keep,
        filePrunedAt=r.filePrunedAt,
        version=r.version,
    )


def detail(s, user_id: str, r: Receipt, held: Perms) -> ReceiptDetail:
    base = row(s, r, held, user_id)
    # The file's own date, over every link; its reason named only from a link this reader
    # reads (S9.7).
    with scoping.as_server(s, "how long a receipt's file is kept") as srv:
        rt = retention.retention(retention.Context(srv), srv.get(Receipt, r.id))
    named = rt.link is None or access.perms(s, ReceiptLink, rt.link, user_id) is not None
    return ReceiptDetail(
        **base.model_dump(),
        matches=[
            Suggestion(
                transactionId=m.transaction.id,
                accountName=m.account.name,
                date=m.transaction.date,
                amount=m.transaction.amount,
                payee=m.transaction.payee,
            )
            for m in receipts.matches(s, user_id, r)
        ],
        text=r.text,
        suggested={
            k: Suggested(value=v["value"], confidence=v["confidence"])
            for k, v in json.loads(r.suggested or "{}").items()
        },
        readMethod=r.readMethod,
        readEngine=r.readEngine,
        readAt=r.readAt,
        kept=rt.label if rt.state != "pruned" else f"File pruned {r.filePrunedAt:%b %-d, %Y}",
        keptState=rt.state,
        keptUntil=rt.until,
        keptSoon=rt.soon,
        keptWhy=(
            None
            if not rt.years
            else "Kept for something not shared with you"
            if not named
            else f"{rt.category} keeps "
            + ("statements" if rt.category == "Statements" else "receipts")
            + f" {rt.years} year{'s' if rt.years != 1 else ''}"
        ),
    )


@router.get("/receipts", response_model=list[ReceiptRow])
def list_receipts(
    request: Request, c: Caller = Depends(caller), show: str = "all", q: str | None = None
):
    """Newest first. *inbox*: the caller's receipts attached to nothing yet. The search looks
    in what was read from each receipt (S9.8.5) as well as its fields."""
    with server(request).db.read(user=c.id) as s:
        rows = [row(s, r, p, c.id) for r, p in receipts.visible(s, c.id)]
        in_text = reading.search(s, q) if q else set()
    if show == "inbox":
        rows = [r for r in rows if not r.links and not r.alsoKeptWith and r.access.mine]
    if q:
        words = q.lower().split()
        rows = [
            r
            for r in rows
            if r.id in in_text
            or all(
                w
                in " ".join(
                    filter(
                        None,
                        [r.fileName, r.payee, r.notes, str(r.amount or ""), " ".join(r.tags)],
                    )
                ).lower()
                for w in words
            )
        ]
    return sorted(rows, key=lambda r: r.uploadedAt, reverse=True)


@router.post("/receipts", response_model=ReceiptRow, status_code=201, responses={200: {}})
async def upload(request: Request, file: UploadFile = File(...), c: Caller = Depends(caller)):
    """One file per request; a batch is many requests. The same file again gives back the
    receipt it made (200)."""
    srv = server(request)
    srv.upload_rate.check(c.id, "uploads")
    with srv.db.read(user=c.id) as s:
        limit = settings.get(s, "receiptMaxMb") * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise Problem(413, "too-large", f"Receipts are up to {limit // (1024 * 1024)} MB.")
    if not data:
        raise refuse("file", "file-empty", "The file is empty.")
    with (
        receipts.prepared(srv, c.id, file.filename or "receipt", data) as ready,
        srv.db.tx(user=c.id) as s,
    ):
        stored = receipts.record(s, srv, c.id, ready)
        if not stored.existing:
            activity.record(s, "receipt.uploaded", actor=c.id, owner=c.id)
        out = row(s, stored.receipt, receipts.perms_for(s, c.id, stored.receipt), c.id)
    if out.readStatus == "waiting" and srv.reader is not None:
        srv.reader.queue(out.id)
    return JSONResponse(
        out.model_dump(mode="json"),
        status_code=200 if stored.existing else 201,
        headers={"Location": f"/ui/api/receipts/{out.id}"},
    )


@router.get("/receipts/{receipt_id}", response_model=ReceiptDetail)
def get_receipt(receipt_id: str, request: Request, c: Caller = Depends(caller)):
    with server(request).db.read(user=c.id) as s:
        r, held = receipts.get(s, c.id, receipt_id)
        return detail(s, c.id, r, held)


@router.post("/receipts/{receipt_id}/read", response_model=ReceiptDetail)
def read_again(receipt_id: str, request: Request, c: Caller = Depends(caller)):
    """Read it again (S9.8.6): only empty or suggested fields are replaced."""
    srv = server(request)
    with srv.db.tx(user=c.id) as s:
        r, held = receipts.get(s, c.id, receipt_id, "write")
        if not settings.get(s, "readReceipts"):
            raise Problem(409, "reading-off", "Reading receipts is off in Settings › Receipts.")
        reading.read_again(s, r)
        s.flush()
        out = detail(s, c.id, r, held)
    if srv.reader is not None:
        srv.reader.queue(receipt_id)
    return out


class ReceiptRecord(Model):
    """A receipt as a draft saves it (S9.8): what was read from it, or typed, and whether it is
    kept for ever. It is made by uploading its file; what it is attached to are pairs of their
    own (S13.8.6)."""

    date: dt.date | None = None
    amount: Money | None = None
    payee: str | None = None
    notes: str | None = None
    tagIds: list[IdOf("Tag")] = Field(  # type: ignore[valid-type]  # the saver's own
        default_factory=list, json_schema_extra={"uniqueItems": True}
    )
    keep: bool = False


RECEIPT_FIELDS = ("date", "amount", "payee", "notes")


def _receipt_create(ctx, record_id: str, body: ReceiptRecord) -> None:
    raise refuse(None, "receipt-uploaded", "A receipt is made by uploading its file.")


def _receipt_current(ctx, r: Receipt) -> dict:
    return {
        **{f: getattr(r, f) for f in RECEIPT_FIELDS},
        "tagIds": tags.ids_of(ctx.s, "receipt", ctx.caller.id, r.id),
        "keep": bool(r.keep),
    }


def _receipt_update(ctx, r: Receipt, body: ReceiptRecord) -> None:
    """Its date, amount, payee, notes and tags: by its owner, or by anyone who can write to
    an account it is attached in."""
    if body.payee is not None and len(body.payee) > 200:
        raise refuse("payee", "payee-too-long", "At most 200 characters.")
    if body.notes is not None and len(body.notes) > 2000:
        raise refuse("notes", "notes-too-long", "At most 2,000 characters.")
    filled = set(json.loads(r.filled or "[]"))
    for f in RECEIPT_FIELDS:
        value = getattr(body, f)
        if isinstance(value, str):
            value = value.strip() or None
        if f == "amount" and value is not None:
            value = abs(Decimal(value))
        if value != getattr(r, f):
            # A value a person gives is theirs: reading again won't replace it.
            filled.discard(f)
            setattr(r, f, value)
    r.filled = exactjson.dumps(sorted(filled))
    tags.owned(ctx.s, ctx.caller.id, body.tagIds)
    tags.set_on(ctx.s, "receipt", r.id, ctx.caller.id, body.tagIds, ctx.caller.id)
    r.keep = body.keep
    r.updatedAt = clock.now()


def _receipt_delete(ctx, r: Receipt) -> None:
    s, c = ctx.s, ctx.caller
    receipts.get(s, c.id, r.id, "deletable")
    receipts.delete(s, c.id, r)
    activity.record(s, "receipt.deleted", actor=c.id, owner=c.id)


def _receipt_read(ctx, record_id: str) -> ReceiptDetail:
    r, held = receipts.get(ctx.s, ctx.caller.id, record_id)
    return detail(ctx.s, ctx.caller.id, r, held)


save.register(
    save.Kind(
        prefix="Rcpt",
        entity=Receipt,
        fields=ReceiptRecord,
        create=_receipt_create,
        editable=lambda ctx, record_id: receipts.get(ctx.s, ctx.caller.id, record_id, "write")[0],
        current=_receipt_current,
        update=_receipt_update,
        delete=_receipt_delete,
        read=_receipt_read,
    )
)


class ReceiptLinkRecord(Model):
    """What a receipt is attached to, as a draft makes or takes it away (S9.3): a record of
    its own, never changed. `itemId` names a record of the kind's table."""

    receiptId: IdOf("Rcpt")  # type: ignore[valid-type]
    kind: Literal["transaction", "account", "item", "expense", "gift", "donation"]
    itemId: str


class ReceiptLinkOut(ReceiptLinkRecord):
    id: str
    version: int


def _link_create(ctx, record_id: str, body: ReceiptLinkRecord) -> None:
    s, c = ctx.s, ctx.caller
    if not ids.is_id(body.itemId, receipts.TARGETS[body.kind]):
        raise refuse("itemId", "id-invalid", f"Not an id of {receipts.TARGETS[body.kind]}.")
    r = receipts.to_attach(s, c.id, body.receiptId)
    ln = receipts.link(s, c.id, r, body.kind, body.itemId, record_id)
    if body.kind == "transaction":
        a = receipts._account_of(s, ln)
        activity.record(
            s,
            "receipt.attached",
            actor=c.id,
            subject_kind="account",
            subject_id=a.id,
            owner=a.ownerId,
        )
    srv = server(ctx.request)
    ctx.after(f"receipt:{r.id}", lambda: srv.events.publish("receipt", {"id": r.id}, users=[c.id]))


def _link(ctx, record_id: str) -> ReceiptLink:
    """A live link, of a receipt the caller can see."""
    ln = ctx.s.get(ReceiptLink, record_id)
    if ln is None or ln.deleted:
        raise Problem(404, "not-found", "Not found")
    receipts.get(ctx.s, ctx.caller.id, ln.receiptId)
    return ln


def _link_update(ctx, ln: ReceiptLink, body: ReceiptLinkRecord) -> None:
    raise refuse(None, "link-unchanged", "A link is made or taken away, never changed.")


def _link_read(ctx, record_id: str) -> ReceiptLinkOut:
    ln = ctx.s.get(ReceiptLink, record_id)
    return ReceiptLinkOut(
        id=ln.id, version=ln.version, receiptId=ln.receiptId, kind=ln.kind, itemId=ln.itemId
    )


save.register(
    save.Kind(
        prefix="RcLnk",
        entity=ReceiptLink,
        fields=ReceiptLinkRecord,
        create=_link_create,
        editable=_link,
        current=lambda ctx, ln: {"receiptId": ln.receiptId, "kind": ln.kind, "itemId": ln.itemId},
        update=_link_update,
        delete=lambda ctx, ln: receipts.unlink(ctx.s, ctx.caller.id, ln),
        read=_link_read,
    )
)


def _disposition(name: str) -> str:
    return "inline; filename*=UTF-8''" + urllib.parse.quote(name)


@router.get("/receipts/{receipt_id}/file", response_class=StreamingResponse)
def receipt_file(receipt_id: str, request: Request, c: Caller = Depends(caller)):
    """Streamed through decryption, never written out as plaintext. Served inline in a
    sandbox, with its checked type, so a PDF can't run script in the app (S9.4)."""
    srv = server(request)
    with srv.db.read(user=c.id) as s:
        r, _ = receipts.get(s, c.id, receipt_id)
    if r.filePrunedAt is not None:
        raise Problem(410, "file-pruned", f"Its file was pruned on {r.filePrunedAt:%b %-d, %Y}.")
    headers = {
        "Content-Disposition": _disposition(r.fileName),
        "Content-Security-Policy": "sandbox",
        "Cache-Control": "private, no-store",
    }
    try:
        if r.mediaType == "image/heic":
            # Decoded in the reader's worker, never here (S9.1, S9.8.4.2).
            data = parsing.as_jpeg(receipts.whole(srv, r))
            return Response(data, media_type="image/jpeg", headers=headers)
        stream = receipts.read_file(srv, r)
        first = next(stream)
    except parsing.ReadError as e:
        raise Problem(415, "receipt-unshowable", f"The photo can't be shown: {e}") from None
    except (FileError, OSError) as e:
        # The reason, which may name a path on the host, goes to the log only (S13.7.8).
        error_id = new_error_id()
        log.warning("receipt %s unreadable (%s): %s", r.id, error_id, e)
        raise Problem(
            500, "receipt-unreadable", "The receipt's file can't be read.", error_id=error_id
        ) from None

    def body():
        yield first
        yield from stream

    return StreamingResponse(
        body(), media_type=r.mediaType, headers={**headers, "Content-Length": str(r.size)}
    )


@router.get("/receipts/{receipt_id}/thumbnail", response_class=Response)
def receipt_thumbnail(receipt_id: str, request: Request, c: Caller = Depends(caller)):
    with server(request).db.read(user=c.id) as s:
        r, _ = receipts.get(s, c.id, receipt_id)
        thumb = r.thumbnail
    if thumb is None:
        raise Problem(404, "no-thumbnail", "This receipt has no thumbnail.")
    return Response(
        thumb,
        media_type="image/webp",
        headers={"Cache-Control": "private, max-age=86400", "Content-Security-Policy": "sandbox"},
    )


@router.get("/transactions/{transaction_id}/receipts", response_model=list[ReceiptRow])
def transaction_receipts(transaction_id: str, request: Request, c: Caller = Depends(caller)):
    from .. import access

    with server(request).db.read(user=c.id) as s:
        t = s.get(Transaction, transaction_id)
        if t is None or t.deleted:
            raise Problem(404, "not-found", "Not found")
        access.account(s, c.id, t.accountId)
        ids = receipts.receipts_of(s, [t.id]).get(t.id, [])
        out = []
        for rid in ids:
            r = s.get(Receipt, rid)
            out.append(row(s, r, receipts.perms_for(s, c.id, r) or access.READ, c.id))
        return out
