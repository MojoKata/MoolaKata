import datetime as dt
from dataclasses import dataclass, field

from . import Record, _now


@dataclass(kw_only=True, eq=False)
class Setting(Record):
    id: str
    key: str
    value: str
    updatedById: str | None = None


@dataclass(kw_only=True, eq=False)
class Secret:
    id: str
    recordType: str
    recordId: str
    field: str
    ciphertext: bytes
    nonce: bytes
    wrappedKey: bytes
    setAt: dt.datetime = field(default_factory=_now)
    setById: str | None = None


@dataclass(kw_only=True, eq=False)
class TaskRun:
    name: str
    startedAt: dt.datetime
    finishedAt: dt.datetime | None = None
    error: str | None = None


@dataclass(kw_only=True, eq=False)
class QueuedEmail:
    id: str
    recipient: str
    subject: str
    queuedAt: dt.datetime
    expiresAt: dt.datetime
    message: str | None = None
    refusedAt: dt.datetime | None = None
    error: str | None = None


@dataclass(kw_only=True, eq=False)
class Activity:
    id: str
    kind: str
    at: dt.datetime = field(default_factory=_now)
    actorId: str | None = None
    via: str | None = None
    subjectKind: str | None = None
    subjectId: str | None = None
    ownerId: str | None = None
    forAdmins: bool = False
    detail: str = "{}"


__all__ = ["Activity", "Record", "Secret", "Setting", "TaskRun"]
