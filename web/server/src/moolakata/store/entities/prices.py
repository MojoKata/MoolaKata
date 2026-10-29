import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from ...ids import new_id
from . import Record, _now


@dataclass(kw_only=True, eq=False)
class PriceSource(Record):
    id: str
    name: str
    enabled: bool = False
    preference: str = "{}"
    lastRunAt: dt.datetime | None = None
    lastOkAt: dt.datetime | None = None
    lastError: str | None = None
    createdById: str | None = None


@dataclass(kw_only=True, eq=False)
class Price(Record):
    id: str = field(default_factory=lambda: new_id("Price"))
    instrumentId: str
    date: dt.date
    close: Decimal
    source: str
    fetchedAt: dt.datetime = field(default_factory=_now)
    enteredById: str | None = None


@dataclass(kw_only=True, eq=False)
class TypedPrice(Record):
    id: str = field(default_factory=lambda: new_id("TyPrc"))
    instrumentId: str
    userId: str
    date: dt.date
    close: Decimal
