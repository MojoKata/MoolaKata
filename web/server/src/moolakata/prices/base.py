"""The TickerSource interface (requirements S4.2.1, S4.2.2)."""

import datetime as dt
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar

from .. import clock
from ..net import Client
from ..tasks import TaskError

SOURCES: dict[str, type[TickerSource]] = {}


class SourceError(TaskError):
    """A source's failure, worded so Settings can show it (no keys, names or amounts)."""


class NotListed(SourceError):
    """A source's answer that it doesn't know a symbol: the next source for the class is asked,
    and one no source knows is recorded so (S4.2.2)."""


@dataclass(frozen=True)
class Quote:
    price: Decimal
    asOf: dt.date


@dataclass(frozen=True)
class Ref:
    """What a source needs to know about an instrument."""

    id: str
    symbol: str
    instrumentClass: str


class TickerSource(ABC):
    """A source of free, daily prices. It declares what it serves and under which terms."""

    name: ClassVar[str]
    label: ClassVar[str]
    classes: ClassVar[frozenset[str]]
    needs_key: ClassVar[bool] = False
    key_url: ClassVar[str | None] = None
    # Calls per window, as (calls, seconds): Tiingo's 50 an hour and 1,000 a day.
    limits: ClassVar[tuple[tuple[int, float], ...]] = ()
    hosts: ClassVar[tuple[str, ...]] = ()
    terms: ClassVar[str] = ""
    terms_checked: ClassVar[dt.date | None] = None
    attribution: ClassVar[str | None] = None
    fetches: ClassVar[bool] = True  # false for sources that are typed, not fetched
    dev_only: ClassVar[bool] = False

    def __init__(
        self, client: Client | None, key: str | None, wait: Callable[[], None] = lambda: None
    ) -> None:
        self.client = client
        self.key = key
        self.wait = wait  # blocks until the source's limits allow one more call

    @abstractmethod
    def history(self, ref: Ref, start: dt.date, end: dt.date) -> list[tuple[dt.date, Decimal]]:
        """Daily closes from start to end, by market day."""

    def quotes(self, refs: list[Ref]) -> dict[str, Quote]:
        """The latest close for each instrument, by its id."""
        out = {}
        today = clock.today()
        for ref in refs:
            closes = self.history(ref, today - dt.timedelta(days=10), today)
            if closes:
                day, price = closes[-1]
                out[ref.id] = Quote(price, day)
        return out

    def get_json(self, url: str, **kw):
        if self.client is None:
            raise SourceError(f"{self.label} has no network client")
        self.wait()
        try:
            r, body = self.client.get_bytes(url, **kw)
        except Exception as e:
            raise SourceError(f"{self.label} could not be reached ({type(e).__name__})") from None
        if r.status_code in (401, 403):
            raise SourceError(f"{self.label} refused the key (HTTP {r.status_code})")
        if r.status_code == 404:
            return None
        if r.status_code == 429:
            raise SourceError(f"{self.label} says the limit is reached (HTTP 429)")
        if r.status_code >= 400:
            raise SourceError(f"{self.label} answered HTTP {r.status_code}")
        import json

        try:
            # Prices as the source wrote them, never through a float (S14.3).
            return json.loads(body, parse_float=Decimal)
        except ValueError:
            raise SourceError(f"{self.label} answered with something that is not JSON") from None


def register(cls: type[TickerSource]) -> type[TickerSource]:
    SOURCES[cls.name] = cls
    return cls
