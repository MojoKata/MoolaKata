import datetime as dt
from dataclasses import dataclass, field

from ...ids import new_id
from . import Record, SoftDeleted


@dataclass(kw_only=True, eq=False)
class User(Record):
    id: str
    username: str
    displayName: str
    email: str | None = None
    active: bool = True
    passwordHash: str | None = None
    passwordChangedAt: dt.datetime | None = None
    needsSetup: bool = False
    avatar: str | None = None
    timeZone: str = "auto"
    theme: str = "dark"
    personId: str
    alertEmails: str = "daily"
    bitcoinUnit: str = "btc"
    lastSignInAt: dt.datetime | None = None
    reactivationAskedAt: dt.datetime | None = None
    twoStepAt: dt.datetime | None = None
    totpLastStep: int | None = None
    recentAddresses: str = "{}"
    alertSummaryAt: dt.datetime | None = None
    linkId: str | None = None
    remoteId: str | None = None
    activeBudgetId: str | None = None


@dataclass(kw_only=True, eq=False)
class Group(Record):
    id: str
    name: str
    active: bool = True
    builtIn: str | None = None


@dataclass(kw_only=True, eq=False)
class UserGroup(SoftDeleted):
    userId: str
    groupId: str
    createdAt: dt.datetime
    deletedAt: dt.datetime | None = None
    deletedById: str | None = None


@dataclass(kw_only=True, eq=False)
class Session:
    id: str = field(default_factory=lambda: new_id("Sessn"))
    tokenHash: str
    userId: str
    createdAt: dt.datetime
    lastSeenAt: dt.datetime
    expiresAt: dt.datetime
    authAt: dt.datetime
    address: str | None = None
    admin: bool = False
    needsSetup: bool = False


@dataclass(kw_only=True, eq=False)
class OneTimeToken:
    id: str = field(default_factory=lambda: new_id("OTTkn"))
    tokenHash: str
    purpose: str
    userId: str
    createdAt: dt.datetime
    expiresAt: dt.datetime
    data: str | None = None


@dataclass(kw_only=True, eq=False)
class RecoveryCode:
    id: str = field(default_factory=lambda: new_id("RCode"))
    codeHash: str
    userId: str
    createdAt: dt.datetime


@dataclass(kw_only=True, eq=False)
class SignupRequest(Record):
    id: str
    displayName: str
    username: str
    email: str
    passwordHash: str
    sex: str
    confirmBy: dt.datetime
    status: str = "confirming"
    confirmTokenHash: str | None = None
    confirmedAt: dt.datetime | None = None
    decidedAt: dt.datetime | None = None
    decidedById: str | None = None
    userId: str | None = None


@dataclass(kw_only=True, eq=False)
class AccessToken(Record):
    id: str
    userId: str
    name: str
    scope: str
    secretHash: str
    expiresAt: dt.datetime
    items: str = "[]"
    lastUsedAt: dt.datetime | None = None
