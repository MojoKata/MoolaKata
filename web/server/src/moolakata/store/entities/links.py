import datetime as dt
from dataclasses import dataclass, field

from ...ids import new_id
from . import Record


@dataclass(kw_only=True, eq=False)
class Link(Record):
    id: str
    state: str
    role: str
    peerName: str | None = None
    householdName: str | None = None
    householdAvatar: str | None = None
    address: str | None = None
    peerKey: str | None = None
    codeHash: str | None = None
    codeExpiresAt: dt.datetime | None = None
    createdById: str | None = None
    approvedById: str | None = None
    approvedAt: dt.datetime | None = None
    lastOkAt: dt.datetime | None = None
    lastError: str | None = None
    failingSince: dt.datetime | None = None
    peerVersion: str | None = None
    peerProtocol: int | None = None
    endedAt: dt.datetime | None = None
    pausedUntil: dt.datetime | None = None
    syncThrough: dt.date | None = None
    syncBytes: int | None = None
    syncTotal: int | None = None
    copyPublicKey: str | None = None
    copyKeyAt: dt.datetime | None = None
    copyKeyById: str | None = None
    pulledAt: dt.datetime | None = None
    inboxAsOf: dt.datetime | None = None
    needsFull: bool = False
    sentSeq: int = 0
    gotSeq: int = 0
    peerCopyKey: str | None = None
    peerCert: str | None = None
    peerCertNext: str | None = None
    peerCertOffered: str | None = None
    brokenAt: dt.datetime | None = None


@dataclass(kw_only=True, eq=False)
class LinkedItem:
    id: str
    linkId: str
    remoteId: str
    kind: str
    ownerName: str
    sharedAt: dt.datetime
    createdAt: dt.datetime
    viewers: str = "[]"
    includeReceipts: bool = False


@dataclass(kw_only=True, eq=False)
class LinkSent:
    id: str = field(default_factory=lambda: new_id("LkSnt"))
    linkId: str
    itemId: str
    path: str
    viewer: str
    hash: str


@dataclass(kw_only=True, eq=False)
class LinkFile:
    id: str = field(default_factory=lambda: new_id("LkFil"))
    linkId: str
    fileId: str
    missedAt: dt.datetime
    fileName: str | None = None
    tries: int = 0
    error: str | None = None


@dataclass(kw_only=True, eq=False)
class LinkColour(Record):
    id: str = field(default_factory=lambda: new_id("LkCol"))
    userId: str
    linkId: str
    colour: str
