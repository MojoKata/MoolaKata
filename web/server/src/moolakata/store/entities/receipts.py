import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from ...ids import new_id
from . import Record, SoftDeleted, _now


@dataclass(kw_only=True, eq=False)
class Receipt(Record):
    id: str
    ownerId: str
    fileName: str
    mediaType: str
    size: int
    sha256: str
    fileId: str
    thumbnail: bytes | None = None
    date: dt.date | None = None
    amount: Decimal | None = None
    payee: str | None = None
    notes: str | None = None
    readStatus: str = "waiting"
    readError: str | None = None
    readMethod: str | None = None
    readEngine: str | None = None
    readAt: dt.datetime | None = None
    text: str | None = None
    suggested: str = "{}"
    filled: str = "[]"
    keep: bool = False
    filePrunedAt: dt.datetime | None = None
    filePrunedById: str | None = None


@dataclass(kw_only=True, eq=False)
class ReceiptTag(SoftDeleted):
    receiptId: str
    tagId: str
    createdAt: dt.datetime = field(default_factory=_now)


@dataclass(kw_only=True, eq=False)
class ReceiptLink(Record):
    id: str = field(default_factory=lambda: new_id("RcLnk"))
    receiptId: str
    kind: str
    itemId: str
    linkedById: str | None = None
