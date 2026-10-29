import datetime as dt
from dataclasses import dataclass, field

from ...ids import new_id


@dataclass(kw_only=True, eq=False)
class Alert:
    id: str
    kind: str
    causeKey: str
    title: str
    seenSince: dt.datetime
    userId: str | None = None
    about: str = ""
    link: str | None = None
    fix: str | None = None
    icon: str = "alert"
    openedAt: dt.datetime | None = None
    resolvedAt: dt.datetime | None = None
    resolution: str | None = None


@dataclass(kw_only=True, eq=False)
class AlertState:
    id: str = field(default_factory=lambda: new_id("AlSt"))
    alertId: str
    userId: str
    seenAt: dt.datetime | None = None
    dismissedAt: dt.datetime | None = None
    emailedAt: dt.datetime | None = None
