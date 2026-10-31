import datetime as dt
from dataclasses import dataclass

from . import Record


@dataclass(kw_only=True, eq=False)
class Connector(Record):
    id: str
    state: str
    codeHash: str | None = None
    codeExpiresAt: dt.datetime | None = None
    actionKey: str | None = None
    sealingKey: str | None = None
    pairedAt: dt.datetime | None = None
    pairedById: str | None = None
    endedAt: dt.datetime | None = None
    endedById: str | None = None
    lastReportAt: dt.datetime | None = None
    locked: bool = True
    connectorVersion: str | None = None
    lastAddress: str | None = None
    knownAddress: str | None = None
    newAddress: str | None = None
    sealingSignature: str | None = None
    protocol: int | None = None
    pageAddress: str | None = None
    statusKey: str | None = None


@dataclass(kw_only=True, eq=False)
class Connection(Record):
    id: str
    ownerId: str
    connectorId: str
    driver: str
    label: str
    state: str
    message: str | None = None
    lastRunAt: dt.datetime | None = None
    lastRunAdded: int | None = None
    institutionAccounts: str = "[]"
    settings: str = "{}"
    sealedCredential: str | None = None
    sealedAt: dt.datetime | None = None
    signInAddress: str | None = None
    removedAt: dt.datetime | None = None
